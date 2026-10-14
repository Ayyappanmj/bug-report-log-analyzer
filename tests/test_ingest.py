import io
import json
import os

from pytest import raises  # noqa: E402  (real pytest or the local shim)

from log_analyzer.ingest import (IngestError, iter_log_lines, parse_log_file, parse_log_stream,
                                 safe_join, validate_log_path, validate_upload)
from log_analyzer.parser import TRUNC_MARK

LINE = "2026-09-30 10:00:00 ERROR [A] [T-1] [req=abc] boom\n"


def test_validate_missing_and_directory(tmp_path):
    with raises(IngestError):
        validate_log_path(tmp_path / "nope.log")
    with raises(IngestError):
        validate_log_path(tmp_path)


def test_validate_extension_and_size(tmp_path):
    bad = tmp_path / "x.exe"
    bad.write_text("x")
    with raises(IngestError):
        validate_log_path(bad)
    big = tmp_path / "big.log"
    big.write_bytes(b"a" * (2 * 1024 * 1024))
    with raises(IngestError):
        validate_log_path(big, max_size_mb=1)
    assert validate_log_path(big, max_size_mb=5) == big


def test_validate_upload():
    assert validate_upload("..\\..\\evil\\app.LOG", 10) == "app.LOG"
    with raises(IngestError):
        validate_upload("a.png", 10)
    with raises(IngestError):
        validate_upload("a.log", 10 * 1024 * 1024, max_size_mb=1)


def test_safe_join_blocks_traversal(tmp_path):
    (tmp_path / "src").mkdir()
    assert safe_join(tmp_path, "src", "a.py") == (tmp_path / "src" / "a.py").resolve()
    with raises(IngestError):
        safe_join(tmp_path, "..", "secret.txt")
    with raises(IngestError):
        safe_join(tmp_path, "src", "..", "..", "x")


def test_empty_file(tmp_path):
    p = tmp_path / "e.log"
    p.write_text("")
    r = parse_log_file(p)
    assert r.events == [] and r.stats.total_lines == 0


def test_utf16_bom_file(tmp_path):
    p = tmp_path / "ps.log"
    p.write_bytes(LINE.encode("utf-16"))  # what PowerShell 5 '>' produces
    r = parse_log_file(p)
    assert len(r.events) == 1 and r.events[0].message == "boom"


def test_utf8_bom_and_invalid_bytes(tmp_path):
    p = tmp_path / "b.log"
    p.write_bytes(b"\xef\xbb\xbf" + LINE.encode() + b"2026-09-30 10:00:01 INFO [A] [T] caf\xe9 \xff\n")
    r = parse_log_file(p)
    assert len(r.events) == 2 and r.events[0].timestamp is not None


def test_crlf_line_endings(tmp_path):
    p = tmp_path / "w.log"
    p.write_bytes((LINE.rstrip("\n") + "\r\n").encode() * 3)
    assert len(parse_log_file(p).events) == 3


def test_long_line_truncated_and_counted(tmp_path):
    p = tmp_path / "long.log"
    p.write_text("2026-09-30 10:00:00 INFO [A] [T] " + "x" * 50_000 + "\n" + LINE)
    lines = list(iter_log_lines(p, max_line_chars=1000))
    assert len(lines) == 2 and lines[0].endswith(TRUNC_MARK) and len(lines[0]) < 1100
    r = parse_log_file(p)
    assert r.stats.truncated_lines == 1 and r.stats.events == 2


def test_last_line_without_newline(tmp_path):
    p = tmp_path / "n.log"
    p.write_text(LINE + LINE.rstrip("\n"))
    assert len(parse_log_file(p).events) == 2


def test_json_array_file(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps([{"level": "error", "message": "one"}, {"level": "info", "message": "two"}]))
    r = parse_log_file(p)
    assert [e.message for e in r.events] == ["one", "two"]


def test_jsonl_in_json_file(tmp_path):
    p = tmp_path / "l.json"
    p.write_text('{"level": "error", "message": "one"}\n{"level": "warn", "message": "two"}\n')
    assert len(parse_log_file(p).events) == 2


def test_upload_stream_left_open():
    buf = io.BytesIO((LINE * 2).encode())
    r = parse_log_stream(buf, "up.log")
    assert len(r.events) == 2 and not buf.closed


def test_large_generated_file(tmp_path):
    p = tmp_path / "large.log"
    with open(p, "w") as f:
        for i in range(20_000):
            f.write(f"2026-09-30 10:00:{i % 60:02d} INFO [S] [T-1] [req=r{i}] message number {i}\n")
    r = parse_log_file(p)
    assert r.stats.events == 20_000 and r.stats.unparsed_lines == 0
    assert os.path.getsize(p) > 1_000_000
