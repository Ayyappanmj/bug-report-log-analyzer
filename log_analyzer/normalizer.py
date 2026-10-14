"""Timestamp and level normalization. (Message normalization for grouping is added in Phase 4.)"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

TS_PATTERN = r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:\s?(?:Z|[+-]\d{2}:?\d{2}))?"
LEVEL_PATTERN = r"TRACE|DEBUG|INFO|NOTICE|WARNING|WARN|ERROR|ERR|SEVERE|CRITICAL|FATAL"

_LEVELS = {
    "TRACE": "TRACE", "DEBUG": "DEBUG", "INFO": "INFO", "NOTICE": "INFO",
    "WARN": "WARN", "WARNING": "WARN", "ERROR": "ERROR", "ERR": "ERROR", "SEVERE": "ERROR",
    "CRITICAL": "CRITICAL", "FATAL": "CRITICAL", "EMERG": "CRITICAL", "ALERT": "CRITICAL",
}
_NUMERIC_LEVELS = {10: "TRACE", 20: "DEBUG", 30: "INFO", 40: "WARN", 50: "ERROR", 60: "CRITICAL"}

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?\s?(Z|[+-]\d{2}:?\d{2})?$"
)


def normalize_level(value) -> str | None:
    """Map many spellings (WARNING, fatal, 40...) to TRACE/DEBUG/INFO/WARN/ERROR/CRITICAL."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _NUMERIC_LEVELS.get(int(value))
    return _LEVELS.get(str(value).strip().upper())


def parse_timestamp(text: str) -> datetime | None:
    """Parse ISO-like timestamps. Aware values are converted to UTC and returned naive."""
    if not text:
        return None
    text = text.strip()
    m = _TS_RE.match(text)
    try:
        if m:
            y, mo, d, h, mi, s, frac, tz = m.groups()
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), int((frac or "0").ljust(6, "0")))
            if tz and tz != "Z":
                sign = 1 if tz[0] == "+" else -1
                digits = tz[1:].replace(":", "")
                dt -= sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
            return dt
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (ValueError, OverflowError):
        return None


def parse_epoch(value) -> datetime | None:
    """Epoch seconds or milliseconds -> naive UTC datetime."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None


_MSG_MASKS = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<UUID>"),
    (re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}\.[\w.-]{1,63}"), "<EMAIL>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<IP>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?\b"), "<TS>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<HEX>"),
    (re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{6,}\b"), "<HEX>"),
    (re.compile(r"\d+(?:\.\d+)?"), "<N>"),
]
_WS = re.compile(r"\s+")


def normalize_message(text: str) -> str:
    """Mask volatile parts (ids, numbers, IPs, timestamps) so similar messages compare equal."""
    for rx, repl in _MSG_MASKS:
        text = rx.sub(repl, text)
    return _WS.sub(" ", text).strip()
