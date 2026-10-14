"""Modular log parsers.

Each LineParser recognises the *start* of an event. Lines that do not start an event
are attached to the previous event only if they look like a continuation (indented,
"Traceback ...", "Caused by:", exception lines...). Anything else is counted as unparsed.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Iterable, Iterator

from .models import LogEvent, ParseStats
from .normalizer import LEVEL_PATTERN, TS_PATTERN, normalize_level, parse_epoch, parse_timestamp

TRUNC_MARK = " ...[truncated]"
MAX_CONTINUATION_LINES = 500

_REQ_RE = re.compile(r"(?i)\b(?:req(?:uest)?[_-]?id|correlation[_-]?id|trace[_-]?id|req)\s*[=:]\s*([\w-]{3,})")
_STATUS_RES = (
    re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+\S+\s+(\d{3})\b"),
    re.compile(r'(?i)\bstatus(?:[_ ]code)?\s*[=:]\s*(\d{3})\b'),
    re.compile(r'\bHTTP/\d(?:\.\d)?"?\s+(\d{3})\b'),
)
_THREAD_RE = re.compile(r"\[(Thread-\d+|pool-\d+-thread-\d+|MainThread|main|http-nio-[\w-]+)\]")
_NOT_SERVICES = {"error", "warning", "warn", "exception", "failed", "failure", "fatal", "info", "debug", "critical"}
_EXC_SUFFIX = re.compile(r"(?:Error|Exception|Timeout|Failure|Fault|Refused|Denied)$")

_CONT_RE = re.compile(
    r"^(?:\s+\S"
    r"|Traceback \(most recent call last\)"
    r"|Caused by:|Suppressed:|The above exception|During handling of the above exception"
    r"|Exception in thread"
    r"|\.\.\. \d+ (?:more|common frames omitted)"
    r"|(?:[\w$]+\.)*[\w$]*(?:Error|Exception|Timeout|Failure|Fault|Refused|Denied)(?::.*)?$)"
)


def looks_like_continuation(line: str) -> bool:
    return bool(_CONT_RE.match(line))


def _enrich(ev: LogEvent) -> LogEvent:
    """Fill request id / HTTP status from the message when not already set."""
    if not ev.request_id:
        m = _REQ_RE.search(ev.message)
        if m:
            ev.request_id = m.group(1)
    if ev.http_status is None:
        for rx in _STATUS_RES:
            m = rx.search(ev.message)
            if m and 100 <= int(m.group(1)) <= 599:
                ev.http_status = int(m.group(1))
                break
    return ev


class LineParser(ABC):
    name = "base"

    @abstractmethod
    def match(self, line: str, line_no: int) -> LogEvent | None:
        """Return a new event if `line` starts one, else None."""


class JsonLineParser(LineParser):
    name = "json"
    _TS = ("timestamp", "ts", "time", "@timestamp", "asctime", "datetime")
    _LEVEL = ("level", "severity", "lvl", "levelname", "log_level")
    _MSG = ("message", "msg", "event", "text")
    _SERVICE = ("service", "app", "application", "service_name")
    _COMPONENT = ("component", "logger", "name", "module")
    _THREAD = ("thread", "thread_name", "threadname")
    _REQ = ("request_id", "req_id", "requestid", "correlation_id", "trace_id", "x-request-id")
    _STATUS = ("status", "status_code", "http_status", "statuscode")
    _STACK = ("stack_trace", "stacktrace", "stack", "traceback", "exception", "exc_info")

    @staticmethod
    def _first(d: dict, keys):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
        return None

    def match(self, line: str, line_no: int) -> LogEvent | None:
        s = line.strip()
        if not (s.startswith("{") and s.endswith("}")):
            return None
        try:
            obj = json.loads(s)
        except (ValueError, RecursionError):
            return None
        if not isinstance(obj, dict):
            return None
        d = {str(k).lower(): v for k, v in obj.items()}
        ts_val, lvl_val, msg_val = self._first(d, self._TS), self._first(d, self._LEVEL), self._first(d, self._MSG)
        if ts_val is None and lvl_val is None and msg_val is None:
            return None
        ts = parse_epoch(ts_val) if isinstance(ts_val, (int, float)) else parse_timestamp(str(ts_val)) if ts_val else None
        status = self._first(d, self._STATUS)
        ev = LogEvent(
            line_no=line_no, fmt=self.name, raw=line,
            message="" if msg_val is None else str(msg_val),
            level=normalize_level(lvl_val), timestamp=ts,
            timestamp_raw=None if ts_val is None else str(ts_val),
            service=self._str(self._first(d, self._SERVICE)),
            component=self._str(self._first(d, self._COMPONENT)),
            thread=self._str(self._first(d, self._THREAD)),
            request_id=self._str(self._first(d, self._REQ)),
            http_status=status if isinstance(status, int) and 100 <= status <= 599 else None,
        )
        stack = self._first(d, self._STACK)
        if isinstance(stack, str):
            ev.continuation = stack.splitlines()[:MAX_CONTINUATION_LINES]
        elif isinstance(stack, list):
            ev.continuation = [str(x) for x in stack][:MAX_CONTINUATION_LINES]
        elif isinstance(stack, dict):
            ev.continuation = [json.dumps(stack)]
        return _enrich(ev)

    @staticmethod
    def _str(v) -> str | None:
        return None if v in (None, "") else str(v)


class BracketedParser(LineParser):
    """`2026-09-30 10:22:14,123 ERROR [Service] [Thread-7] [req=abc123] message`"""

    name = "bracketed"
    _RE = re.compile(
        rf"^(?P<ts>{TS_PATTERN})\s+(?P<level>{LEVEL_PATTERN})\s+\[(?P<service>[^\]]*)\]\s+"
        r"\[(?P<thread>[^\]]*)\]\s+(?:\[(?:req|request[_-]?id|trace|corr(?:elation)?)[=:]\s*(?P<rid>[^\]]*)\]\s*)?"
        r"(?P<msg>.*)$",
        re.I,
    )

    def match(self, line: str, line_no: int) -> LogEvent | None:
        m = self._RE.match(line)
        if not m:
            return None
        rid = (m.group("rid") or "").strip()
        ev = LogEvent(
            line_no=line_no, fmt=self.name, raw=line, message=m.group("msg").strip(),
            level=normalize_level(m.group("level")), timestamp=parse_timestamp(m.group("ts")),
            timestamp_raw=m.group("ts"), service=m.group("service").strip() or None,
            thread=m.group("thread").strip() or None,
            request_id=rid if rid and rid != "-" else None,
        )
        return _enrich(ev)


class GenericParser(LineParser):
    """`<timestamp> <LEVEL> <anything>` with best-effort service/thread extraction."""

    name = "generic"
    _RE = re.compile(rf"^(?P<ts>{TS_PATTERN})\s+\[?(?P<level>{LEVEL_PATTERN})\]?(?:\s*[:\-]\s*|\s+|$)(?P<rest>.*)$", re.I)
    _BRACKET_SVC = re.compile(r"^\[(?P<s>[^\]]+)\]\s*(?P<m>.*)$")
    _COLON_SVC = re.compile(r"^(?P<s>[A-Za-z_][\w.\-]*)\s*(?::|\s-\s)\s*(?P<m>.*)$")
    _TOKEN = re.compile(r"^[A-Za-z_][\w.\-]*$")

    def match(self, line: str, line_no: int) -> LogEvent | None:
        m = self._RE.match(line)
        if not m:
            return None
        rest = m.group("rest").strip()
        ev = LogEvent(
            line_no=line_no, fmt=self.name, raw=line, level=normalize_level(m.group("level")),
            timestamp=parse_timestamp(m.group("ts")), timestamp_raw=m.group("ts"), message=rest,
        )
        tm = _THREAD_RE.search(rest)
        if tm:
            ev.thread = tm.group(1)
        b = self._BRACKET_SVC.match(rest)
        c = self._COLON_SVC.match(rest)
        if b and not _THREAD_RE.fullmatch("[" + b.group("s") + "]"):
            ev.service, ev.message = b.group("s").strip(), b.group("m").strip()
        elif c and c.group("s").lower() not in _NOT_SERVICES and not _EXC_SUFFIX.search(c.group("s")):
            ev.service, ev.message = c.group("s"), c.group("m").strip()
        elif self._TOKEN.match(rest) and not _EXC_SUFFIX.search(rest):
            ev._lone_token = True  # resolved when the event is finished
        return _enrich(ev)


DEFAULT_PARSERS: tuple[LineParser, ...] = (JsonLineParser(), BracketedParser(), GenericParser())


class LogParser:
    """Streaming parser: feed lines, get events. Statistics are in `.stats` (final after iteration)."""

    def __init__(self, parsers: Iterable[LineParser] | None = None, max_continuation: int = MAX_CONTINUATION_LINES):
        self.parsers = tuple(parsers) if parsers is not None else DEFAULT_PARSERS
        self.max_continuation = max_continuation
        self.stats = ParseStats()

    def _match(self, line: str, line_no: int) -> LogEvent | None:
        for p in self.parsers:
            ev = p.match(line, line_no)
            if ev is not None:
                return ev
        return None

    def _finish(self, ev: LogEvent) -> LogEvent:
        while ev.continuation and not ev.continuation[-1].strip():
            ev.continuation.pop()
        if ev._lone_token:
            first = next((l.strip() for l in ev.continuation if l.strip()), "")
            if first:
                ev.service, ev.message = ev.message, first
        elif not ev.message and ev.continuation:
            ev.message = next((l.strip() for l in ev.continuation if l.strip()), "")
        return ev

    def _attach(self, ev: LogEvent, line: str, line_no: int) -> None:
        self.stats.continuation_lines += 1
        ev.end_line = line_no
        if len(ev.continuation) >= self.max_continuation:
            self.stats.dropped_continuation_lines += 1
        else:
            ev.continuation.append(line)

    def parse_lines(self, lines: Iterable[str]) -> Iterator[LogEvent]:
        st = self.stats
        current: LogEvent | None = None
        for raw in lines:
            st.total_lines += 1
            n = st.total_lines
            if raw.endswith(TRUNC_MARK):
                st.truncated_lines += 1
            ev = self._match(raw, n)
            if ev is not None:
                if current is not None:
                    yield self._finish(current)
                current = ev
                st.events += 1
                st.events_by_level[ev.level or "UNKNOWN"] += 1
                st.events_by_format[ev.fmt] += 1
                continue
            if not raw.strip():
                if current is not None and current.continuation:
                    self._attach(current, raw, n)
                else:
                    st.blank_lines += 1
                continue
            if current is not None and looks_like_continuation(raw):
                self._attach(current, raw, n)
                continue
            st.unparsed_lines += 1
            if len(st.unparsed_samples) < 20:
                st.unparsed_samples.append(raw[:200])
            if current is not None:  # a stray line ends the open event
                yield self._finish(current)
                current = None
        if current is not None:
            yield self._finish(current)
