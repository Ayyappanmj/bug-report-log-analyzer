"""Data models for parsed log events (stdlib only)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LogEvent:
    """One logical log event: a start line plus any continuation lines (e.g. a stack trace)."""

    line_no: int                       # 1-based line where the event starts
    fmt: str                           # name of the parser that matched
    raw: str                           # the first physical line, as read
    message: str = ""
    level: str | None = None           # TRACE/DEBUG/INFO/WARN/ERROR/CRITICAL or None
    timestamp: datetime | None = None  # naive; timezone-aware inputs are converted to UTC
    timestamp_raw: str | None = None
    service: str | None = None
    component: str | None = None
    thread: str | None = None
    request_id: str | None = None
    http_status: int | None = None
    continuation: list[str] = field(default_factory=list)
    end_line: int = 0
    _lone_token: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if not self.end_line:
            self.end_line = self.line_no

    @property
    def stack_trace(self) -> str:
        return "\n".join(self.continuation)

    @property
    def full_text(self) -> str:
        return "\n".join([self.raw, *self.continuation])

    def to_dict(self) -> dict:
        return {
            "line_no": self.line_no, "end_line": self.end_line, "format": self.fmt,
            "level": self.level,
            "timestamp": self.timestamp.isoformat(sep=" ", timespec="milliseconds") if self.timestamp else None,
            "service": self.service, "component": self.component, "thread": self.thread,
            "request_id": self.request_id, "http_status": self.http_status,
            "message": self.message, "stack_trace": self.stack_trace,
        }


@dataclass
class ParseStats:
    """Counts measured from the actual input. Identity:
    total_lines == events + continuation_lines + blank_lines + unparsed_lines
    """

    total_lines: int = 0
    events: int = 0
    continuation_lines: int = 0
    blank_lines: int = 0
    unparsed_lines: int = 0
    truncated_lines: int = 0
    dropped_continuation_lines: int = 0
    unparsed_samples: list[str] = field(default_factory=list)
    events_by_level: Counter = field(default_factory=Counter)
    events_by_format: Counter = field(default_factory=Counter)

    def to_dict(self) -> dict:
        return {
            "total_lines": self.total_lines, "events": self.events,
            "continuation_lines": self.continuation_lines, "blank_lines": self.blank_lines,
            "unparsed_lines": self.unparsed_lines, "truncated_lines": self.truncated_lines,
            "dropped_continuation_lines": self.dropped_continuation_lines,
            "unparsed_samples": list(self.unparsed_samples),
            "events_by_level": dict(self.events_by_level),
            "events_by_format": dict(self.events_by_format),
        }


@dataclass
class ParseResult:
    events: list[LogEvent]
    stats: ParseStats
    source_name: str = ""
