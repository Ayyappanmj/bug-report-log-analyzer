"""Extract exception chains and stack frames from an event's continuation lines."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_SUFFIXES = ("Error", "Exception", "Timeout", "Failure", "Fault", "Refused", "Denied", "Interrupt", "Abort")

_PY_FRAME = re.compile(r'^\s+File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')
_JAVA_FRAME = re.compile(r"^\s+at\s+(?P<func>[\w$.<>]+)\((?P<file>[\w$.\-]+):(?P<line>\d+)\)")
_JS_FRAME = re.compile(r"^\s+at\s+(?:(?P<func>[^\s(]+)\s+\()?(?P<file>.+?):(?P<line>\d+):\d+\)?\s*$")
_CARET = re.compile(r"^\s*[\^~]+\s*$")
_EXC_LINE = re.compile(
    r'^(?:Caused by:\s*|Exception in thread "[^"]*"\s+)?'
    r"(?P<type>(?:[A-Za-z_][\w$]*\.)*[A-Za-z_][\w$]*)(?::\s?(?P<msg>.*))?$"
)
_MSG_EXC = re.compile(r"\b((?:[A-Za-z_][\w$]*\.)*[A-Z][\w$]*(?:Exception|Error|Timeout))\b")


@dataclass(frozen=True)
class Frame:
    file: str
    line: int
    function: str
    code: str | None = None
    language: str = "unknown"

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "function": self.function,
                "code": self.code, "language": self.language}


@dataclass
class ExceptionInfo:
    type: str
    message: str = ""
    frames: list[Frame] = field(default_factory=list)

    @property
    def short_type(self) -> str:
        return self.type.rsplit(".", 1)[-1]


@dataclass
class ExceptionChain:
    style: str = "none"  # python | other | none
    exceptions: list[ExceptionInfo] = field(default_factory=list)
    loose_frames: list[Frame] = field(default_factory=list)  # frames seen with no exception line

    @property
    def surfaced(self) -> ExceptionInfo | None:
        """The exception that reached the top of the stack (what the caller saw)."""
        if not self.exceptions:
            return None
        return self.exceptions[-1] if self.style == "python" else self.exceptions[0]

    @property
    def root(self) -> ExceptionInfo | None:
        """The deepest cause: first raised in Python chains, last 'Caused by' in Java-style traces."""
        if not self.exceptions:
            return None
        return self.exceptions[0] if self.style == "python" else self.exceptions[-1]

    @property
    def raise_site(self) -> Frame | None:
        r = self.root
        if r is None or not r.frames:
            return None
        return r.frames[-1] if self.style == "python" else r.frames[0]

    def inner_first(self, info: "ExceptionInfo") -> list[Frame]:
        """Frames of `info` ordered from where it was raised outward (Python prints the reverse)."""
        return list(reversed(info.frames)) if self.style == "python" else list(info.frames)

    @property
    def all_frames(self) -> list[Frame]:
        return [f for e in self.exceptions for f in e.frames] or list(self.loose_frames)


def _looks_like_exception(type_: str, has_msg: bool) -> bool:
    last = type_.rsplit(".", 1)[-1]
    if type_ == "Traceback":
        return False
    if last.endswith(_SUFFIXES):
        return True
    return "." in type_ and last[:1].isupper() and has_msg


def _frame(lines: list[str], i: int) -> tuple[Frame | None, int]:
    """Try to parse a stack frame at lines[i]; returns (frame, lines consumed)."""
    line = lines[i]
    m = _PY_FRAME.match(line)
    if m:
        code, used = None, 1
        j = i + 1
        while j < len(lines) and _CARET.match(lines[j]):
            j += 1
        if j < len(lines) and lines[j].startswith((" ", "\t")) and not _PY_FRAME.match(lines[j]):
            code = lines[j].strip()
        # consume the code line and any caret lines that follow it
        if code is not None:
            k = j + 1
            while k < len(lines) and _CARET.match(lines[k]):
                k += 1
            used = k - i
        else:
            used = max(j - i, 1)
        return Frame(m["file"], int(m["line"]), m["func"], code, "python"), used
    m = _JAVA_FRAME.match(line)
    if m:
        return Frame(m["file"], int(m["line"]), m["func"], None, "java"), 1
    m = _JS_FRAME.match(line)
    if m:
        return Frame(m["file"], int(m["line"]), m["func"] or "<anonymous>", None, "javascript"), 1
    return None, 0


def parse_exception_chain(lines: list[str]) -> ExceptionChain:
    if not lines:
        return ExceptionChain()
    style = "python" if any(l.startswith("Traceback (most recent call last)") for l in lines) else "other"
    chain = ExceptionChain(style=style)
    pending: list[Frame] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("Traceback (most recent call last)"):
            pending = []
            i += 1
            continue
        frame, used = _frame(lines, i)
        if frame is not None:
            if style == "python":
                pending.append(frame)
            elif chain.exceptions:
                chain.exceptions[-1].frames.append(frame)
            else:
                chain.loose_frames.append(frame)
            i += used
            continue
        m = _EXC_LINE.match(line)
        if m and _looks_like_exception(m["type"], bool(m["msg"])):
            info = ExceptionInfo(m["type"], (m["msg"] or "").strip())
            if style == "python":
                info.frames, pending = pending, []
            chain.exceptions.append(info)
        i += 1
    if not chain.exceptions:
        chain.style = "none"
    return chain


def exception_in_message(message: str) -> str | None:
    """Name of an exception-like token mentioned in a log message, if any (metadata only)."""
    m = _MSG_EXC.search(message or "")
    return m.group(1) if m else None
