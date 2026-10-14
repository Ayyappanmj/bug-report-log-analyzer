"""Group similar problem events, rank the groups, and link groups that share requests.

Severity is derived only from log levels (CRITICAL->CRITICAL, ERROR->HIGH, WARN->MEDIUM); an INFO/DEBUG event
counts as an issue (MEDIUM) only if it carries an exception trace or an HTTP 5xx status.
Ranking is a documented heuristic, not a measurement:
    score = weight[severity] * (1 + log10(count))**2 + 5 (if a stack trace was seen)
    weight = CRITICAL 40, HIGH 10, MEDIUM 3, LOW 1
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Iterable

from .extractor import ExceptionChain, Frame, exception_in_message, parse_exception_chain
from .models import LogEvent
from .normalizer import normalize_message

SEVERITY_WEIGHT = {"CRITICAL": 40, "HIGH": 10, "MEDIUM": 3, "LOW": 1}
_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
_EMPTY_CHAIN = ExceptionChain()


def _max_sev(a: str, b: str) -> str:
    return a if _ORDER[a] >= _ORDER[b] else b


def event_severity(ev: LogEvent, has_exception: bool) -> str | None:
    """Severity of a single event, or None if it is not a problem event."""
    if ev.level == "CRITICAL":
        return "CRITICAL"
    if ev.level == "ERROR":
        return "HIGH"
    if ev.level == "WARN":
        return "MEDIUM"
    if has_exception or (ev.http_status is not None and ev.http_status >= 500):
        return "MEDIUM"
    return None


def _describe(ev: LogEvent) -> str:
    return f"line {ev.line_no} {ev.level or '?'} [{ev.service or '-'}] {ev.message[:160]}"


def _min(a, b):
    return b if a is None else a if b is None else min(a, b)


def _max(a, b):
    return b if a is None else a if b is None else max(a, b)


@dataclass
class ErrorGroup:
    kind: str                       # "exception" | "message"
    key: str
    title: str
    severity: str
    normalized_message: str
    exception_type: str | None = None   # root cause type (exception groups) or a type named in the message
    surfaced_type: str | None = None
    raise_site: str | None = None       # "file:function" where the root exception was raised
    frames: list[Frame] = field(default_factory=list)          # root exception, raise site first
    frames_surfaced: list[Frame] = field(default_factory=list)  # surfaced exception if different
    id: str = ""
    count: int = 0
    levels: Counter = field(default_factory=Counter)
    services: Counter = field(default_factory=Counter)
    http_statuses: Counter = field(default_factory=Counter)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    first_line: int = 0
    last_line: int = 0
    request_ids: set = field(default_factory=set, repr=False)
    timeline: Counter = field(default_factory=Counter)  # events per minute
    samples: list[LogEvent] = field(default_factory=list, repr=False)
    has_stack_trace: bool = False
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def is_recurring(self) -> bool:
        return self.count >= 2

    def add(self, ev: LogEvent, severity: str, chain: ExceptionChain) -> None:
        self.count += 1
        self.severity = _max_sev(self.severity, severity)
        self.levels[ev.level or "UNKNOWN"] += 1
        if ev.service:
            self.services[ev.service] += 1
        if ev.http_status:
            self.http_statuses[ev.http_status] += 1
        if ev.request_id:
            self.request_ids.add(ev.request_id)
        self.first_seen, self.last_seen = _min(self.first_seen, ev.timestamp), _max(self.last_seen, ev.timestamp)
        self.first_line = ev.line_no if not self.first_line else min(self.first_line, ev.line_no)
        self.last_line = max(self.last_line, ev.line_no)
        if ev.timestamp:
            self.timeline[ev.timestamp.strftime("%Y-%m-%d %H:%M")] += 1
        if len(self.samples) < 3:
            self.samples.append(ev)
        if chain.exceptions:
            self.has_stack_trace = True
            if not self.frames:
                root, sur = chain.root, chain.surfaced
                self.frames = chain.inner_first(root)
                if sur is not root:
                    self.frames_surfaced = chain.inner_first(sur)

    def merge(self, other: "ErrorGroup") -> None:
        self.count += other.count
        self.severity = _max_sev(self.severity, other.severity)
        self.levels.update(other.levels)
        self.services.update(other.services)
        self.http_statuses.update(other.http_statuses)
        self.request_ids |= other.request_ids
        self.timeline.update(other.timeline)
        self.first_seen, self.last_seen = _min(self.first_seen, other.first_seen), _max(self.last_seen, other.last_seen)
        self.first_line, self.last_line = min(self.first_line, other.first_line), max(self.last_line, other.last_line)
        self.samples = (self.samples + other.samples)[:3]
        self.has_stack_trace = self.has_stack_trace or other.has_stack_trace
        self.frames = self.frames or other.frames
        self.frames_surfaced = self.frames_surfaced or other.frames_surfaced

    def compute_score(self) -> float:
        base = SEVERITY_WEIGHT[self.severity] * (1 + math.log10(max(self.count, 1))) ** 2
        return base + (5 if self.has_stack_trace else 0)

    def to_dict(self) -> dict:
        ts = lambda d: d.isoformat(sep=" ", timespec="milliseconds") if d else None  # noqa: E731
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "severity": self.severity,
            "count": self.count, "is_recurring": self.is_recurring, "score": round(self.score, 2),
            "exception_type": self.exception_type, "surfaced_type": self.surfaced_type,
            "normalized_message": self.normalized_message, "raise_site": self.raise_site,
            "first_seen": ts(self.first_seen), "last_seen": ts(self.last_seen),
            "first_line": self.first_line, "last_line": self.last_line,
            "levels": dict(self.levels), "services": dict(self.services),
            "http_statuses": {str(k): v for k, v in self.http_statuses.items()},
            "distinct_request_ids": len(self.request_ids),
            "sample_request_ids": sorted(self.request_ids)[:5],
            "frames": [f.to_dict() for f in self.frames],
            "frames_surfaced": [f.to_dict() for f in self.frames_surfaced],
            "samples": [e.to_dict() for e in self.samples],
            "context_before": self.context_before, "context_after": self.context_after,
            "related": self.related, "timeline": dict(sorted(self.timeline.items())),
        }


@dataclass
class GroupingResult:
    groups: list[ErrorGroup]
    summary: dict

    def to_dict(self) -> dict:
        return {"summary": self.summary, "groups": [g.to_dict() for g in self.groups]}


OVERFLOW_KEY = "overflow|additional distinct problems beyond the group limit"
MAX_GROUPS = 20_000


class ErrorGrouper:
    def __init__(self, context_size: int = 6, after_size: int = 3,
                 merge_threshold: float = 0.9, max_merge_groups: int = 2000, max_groups: int = MAX_GROUPS):
        self.context_size, self.after_size = context_size, after_size
        self.merge_threshold, self.max_merge_groups, self.max_groups = merge_threshold, max_merge_groups, max_groups
        self.overflow_events = 0
        self._groups: dict[str, ErrorGroup] = {}
        self._recent: deque[LogEvent] = deque(maxlen=200)
        self._watch: list[tuple[ErrorGroup, int]] = []
        self.total_events = 0
        self._sev_events: Counter = Counter()

    def _before_context(self, ev: LogEvent) -> list[str]:
        picked: dict[int, LogEvent] = {}
        if ev.request_id:
            same = [e for e in reversed(self._recent) if e.request_id == ev.request_id][:3]
            picked.update({e.line_no: e for e in same})
        for e in list(self._recent)[-self.context_size:]:
            picked.setdefault(e.line_no, e)
        return [_describe(e) for _, e in sorted(picked.items())][-(self.context_size + 3):]

    def _make_group(self, ev: LogEvent, sev: str, chain: ExceptionChain) -> tuple[str, ErrorGroup]:
        root = chain.root
        if root is not None:
            site = chain.raise_site
            site_s = f"{site.file}:{site.function}" if site else None
            norm = normalize_message(root.message)
            key = f"exc|{root.short_type}|{norm}|{site_s}"
            title = f"{root.short_type}: {norm}"[:140] if norm else root.short_type
            g = ErrorGroup("exception", key, title, sev, norm, root.short_type,
                           chain.surfaced.short_type if chain.surfaced else None, site_s)
        else:
            norm = normalize_message(ev.message)
            key = f"msg|{ev.level}|{ev.service or ''}|{ev.http_status or ''}|{norm}"
            g = ErrorGroup("message", key, norm[:140] or "(empty message)", sev, norm,
                           exception_type=exception_in_message(ev.message))
        return key, g

    def add(self, ev: LogEvent) -> None:
        self.total_events += 1
        for i, (g, remaining) in enumerate(self._watch):
            if remaining > 0:
                g.context_after.append(_describe(ev))
                self._watch[i] = (g, remaining - 1)
        self._watch = [(g, r) for g, r in self._watch if r > 0]

        chain = parse_exception_chain(ev.continuation) if ev.continuation else _EMPTY_CHAIN
        sev = event_severity(ev, bool(chain.exceptions))
        if sev is not None:
            self._sev_events[sev] += 1
            key, fresh = self._make_group(ev, sev, chain)
            g = self._groups.get(key)
            if g is None and len(self._groups) >= self.max_groups:   # bound memory: fold new distinct problems into one group
                self.overflow_events += 1
                key = OVERFLOW_KEY
                g = self._groups.get(key)
                if g is None:
                    g = self._groups[key] = ErrorGroup("message", key, "(additional distinct problems beyond the group limit)", sev, "")
                    g.context_before = self._before_context(ev)
            if g is None:
                g = self._groups[key] = fresh
                g.context_before = self._before_context(ev)
                self._watch.append((g, self.after_size))
            g.add(ev, sev, chain)
        self._recent.append(ev)

    def _merge_similar(self, groups: list[ErrorGroup]) -> list[ErrorGroup]:
        if len(groups) > self.max_merge_groups:
            return groups
        buckets: dict[tuple, list[ErrorGroup]] = defaultdict(list)
        out: list[ErrorGroup] = []
        for g in sorted(groups, key=lambda x: (-x.count, x.first_line)):
            svc = g.services.most_common(1)[0][0] if g.services else ""
            bkey = (g.kind, g.exception_type, g.raise_site) if g.kind == "exception" else (g.kind, g.severity, svc)
            for rep in buckets[bkey][:200]:
                a, b = rep.normalized_message, g.normalized_message
                sm = SequenceMatcher(None, a, b, autojunk=False)
                if sm.real_quick_ratio() >= self.merge_threshold and sm.quick_ratio() >= self.merge_threshold \
                        and sm.ratio() >= self.merge_threshold:
                    rep.merge(g)
                    break
            else:
                buckets[bkey].append(g)
                out.append(g)
        return out

    @staticmethod
    def _link_related(groups: list[ErrorGroup]) -> None:
        index: dict[str, list[ErrorGroup]] = defaultdict(list)
        for g in groups:
            for rid in g.request_ids:
                index[rid].append(g)
        shared: Counter = Counter()
        for gs in index.values():
            if 1 < len(gs) <= 10:
                for i in range(len(gs)):
                    for j in range(i + 1, len(gs)):
                        shared[(gs[i].id, gs[j].id)] += 1
        by_id = {g.id: g for g in groups}
        for (a, b), n in shared.items():
            ga, gb = by_id[a], by_id[b]
            if n >= 2 and n / min(len(ga.request_ids), len(gb.request_ids)) >= 0.5:
                ga.related.append(b)
                gb.related.append(a)
        for g in groups:
            g.related.sort()

    def finalize(self) -> GroupingResult:
        groups = self._merge_similar(list(self._groups.values()))
        for g in groups:
            g.score = g.compute_score()
        groups.sort(key=lambda g: (-g.score, -g.count, g.first_line))
        for rank, g in enumerate(groups, 1):
            g.id = f"G{rank:03d}"
        self._link_related(groups)
        errors = [g for g in groups if g.severity in ("CRITICAL", "HIGH")]
        summary = {
            "total_events": self.total_events,
            "issue_events": sum(self._sev_events.values()),
            "error_events": self._sev_events["CRITICAL"] + self._sev_events["HIGH"],
            "warning_events": self._sev_events["MEDIUM"],
            "group_count": len(groups),
            "error_groups": len(errors),
            "critical_groups": sum(g.severity == "CRITICAL" for g in groups),
            "warning_groups": sum(g.severity == "MEDIUM" for g in groups),
            "recurring_error_groups": sum(g.is_recurring for g in errors),
            "overflow_events": self.overflow_events,
        }
        return GroupingResult(groups, summary)


def group_events(events: Iterable[LogEvent], **kwargs) -> GroupingResult:
    grouper = ErrorGrouper(**kwargs)
    for ev in events:
        grouper.add(ev)
    return grouper.finalize()
