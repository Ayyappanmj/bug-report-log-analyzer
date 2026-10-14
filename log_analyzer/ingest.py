"""Safe log ingestion: validation, bounded line reading, encoding detection."""
from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import BinaryIO, Iterator

from config import ALLOWED_LOG_EXTENSIONS

from .models import ParseResult
from .parser import TRUNC_MARK, LogParser

MAX_LINE_CHARS = 20_000
# Terminal-escape and look-alike tricks in a log must not reach reports or terminals: strip ANSI sequences, control characters
# and Unicode bidirectional overrides while reading.
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_STRIP = {c: None for c in (*range(0, 9), 0x0B, 0x0C, *range(0x0E, 0x20), 0x7F, *range(0x80, 0xA0), 0x061C, 0x200B, 0x200E, 0x200F,
                            *range(0x202A, 0x202F), 0x2060, *range(0x2066, 0x206A), 0xFEFF)}


def sanitize_line(line: str) -> str:
    if line.isascii() and line.isprintable():       # fast path: nearly every log line
        return line
    if "\x1b" in line:
        line = _ANSI.sub("", line)
    return line.translate(_STRIP)
MAX_JSON_ARRAY_BYTES = 50 * 1024 * 1024


class IngestError(ValueError):
    """The input was rejected (missing, wrong type, too large, unsafe path...)."""


def _check_extension(name: str, allowed) -> None:
    ext = Path(name).suffix.lower()
    if ext not in allowed:
        raise IngestError(f"Unsupported file extension '{ext}'. Allowed: {', '.join(allowed)}")


def validate_log_path(path, *, max_size_mb: int = 50, allowed_extensions=ALLOWED_LOG_EXTENSIONS) -> Path:
    p = Path(path)
    if not p.exists():
        raise IngestError(f"File not found: {p}")
    if not p.is_file():
        raise IngestError(f"Not a regular file: {p}")
    _check_extension(p.name, allowed_extensions)
    size = p.stat().st_size
    if size > max_size_mb * 1024 * 1024:
        raise IngestError(f"File is {size / 1024 / 1024:.1f} MB, above the {max_size_mb} MB limit")
    return p


def validate_upload(filename: str, size_bytes: int, *, max_size_mb: int = 50,
                    allowed_extensions=ALLOWED_LOG_EXTENSIONS) -> str:
    """Validate an uploaded file's name and size; returns the bare file name."""
    name = Path(str(filename).replace("\\", "/")).name
    if not name:
        raise IngestError("Missing file name")
    _check_extension(name, allowed_extensions)
    if size_bytes > max_size_mb * 1024 * 1024:
        raise IngestError(f"Upload is {size_bytes / 1024 / 1024:.1f} MB, above the {max_size_mb} MB limit")
    return name


def safe_join(base, *parts) -> Path:
    """Join `parts` under `base`, rejecting anything that resolves outside it (../, symlinks)."""
    base_r = Path(base).resolve()
    target = base_r.joinpath(*parts).resolve()
    if target != base_r and base_r not in target.parents:
        raise IngestError(f"Path escapes the base directory: {'/'.join(map(str, parts))}")
    return target


def _detect_encoding(head: bytes) -> str:
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):  # PowerShell 5 '>' redirection writes UTF-16
        return "utf-16"
    return "utf-8-sig"


def _bounded_lines(stream, max_chars: int) -> Iterator[str]:
    while True:
        chunk = stream.readline(max_chars)
        if chunk == "":
            return
        if chunk.endswith("\n"):
            yield sanitize_line(chunk.rstrip("\r\n"))
            continue
        if len(chunk) < max_chars:  # last line without newline
            yield sanitize_line(chunk)
            return
        while True:  # over-long line: drop the remainder
            rest = stream.readline(max_chars)
            if rest == "" or rest.endswith("\n"):
                break
        yield sanitize_line(chunk) + TRUNC_MARK


def _json_array_lines(path: Path) -> Iterator[str] | None:
    """If `path` is a .json file holding a top-level array, yield one JSON line per element."""
    if path.suffix.lower() != ".json" or path.stat().st_size > MAX_JSON_ARRAY_BYTES:
        return None
    with open(path, "rb") as f:
        head = f.read(4096).lstrip(b"\xef\xbb\xbf \t\r\n")
    if not head.startswith(b"["):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, list):
        return None
    return (json.dumps(x) if isinstance(x, dict) else str(x) for x in data)


def iter_log_lines(source, *, max_line_chars: int = MAX_LINE_CHARS) -> Iterator[str]:
    """Yield lines from a path or a seekable binary file object (e.g. a Streamlit upload).

    Never loads the whole file (except .json arrays); over-long lines are truncated.
    Invalid bytes are replaced rather than raising.
    """
    if isinstance(source, (str, Path)):
        p = Path(source)
        arr = _json_array_lines(p)
        if arr is not None:
            yield from arr
            return
        with open(p, "rb") as f:
            enc = _detect_encoding(f.read(4))
        with open(p, "r", encoding=enc, errors="replace", newline=None) as f:
            yield from _bounded_lines(f, max_line_chars)
        return
    binary: BinaryIO = source
    if not binary.seekable():
        raise IngestError("Input stream must be seekable")
    binary.seek(0)
    enc = _detect_encoding(binary.read(4))
    binary.seek(0)
    wrapper = io.TextIOWrapper(binary, encoding=enc, errors="replace", newline=None)
    try:
        yield from _bounded_lines(wrapper, max_line_chars)
    finally:
        wrapper.detach()  # leave the caller's stream open


def parse_log_file(path, *, max_size_mb: int = 50) -> ParseResult:
    """Validate, read and parse a log file into events (held in memory)."""
    p = validate_log_path(path, max_size_mb=max_size_mb)
    parser = LogParser()
    events = list(parser.parse_lines(iter_log_lines(p)))
    return ParseResult(events=events, stats=parser.stats, source_name=p.name)


def parse_log_stream(stream, name: str = "upload.log") -> ParseResult:
    parser = LogParser()
    events = list(parser.parse_lines(iter_log_lines(stream)))
    return ParseResult(events=events, stats=parser.stats, source_name=name)
