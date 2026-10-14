"""Seeded fuzz and adversarial-input tests: nothing may crash, hang, or break the counting invariants."""
import random
import time

from ai.redaction import redact
from ai.validation import LLMValidationError, extract_json
from code_analyzer.chunker import chunk_file
from code_analyzer.models import SourceFile
from log_analyzer.extractor import parse_exception_chain
from log_analyzer.grouper import group_events
from log_analyzer.normalizer import normalize_message, parse_timestamp
from log_analyzer.parser import LogParser

FRAGMENTS = [
    "2026-09-30 10:22:14,123 ERROR [Svc] [Thread-1] [req=abc123] boom order=ORD-1",
    "2026-09-30T10:22:14Z WARNING: something odd", "2026-09-30 10:22:14 INFO PaymentService", "DatabaseConnectionTimeout",
    "Traceback (most recent call last):", '  File "src/a.py", line 12, in f', "    x = y()", "KeyError: 'k'",
    "Caused by: java.sql.SQLException: down", "\tat com.acme.Db.run(Db.java:5)", "", "   ", "{", "}", '{"level": "error", "msg": "x"}',
    '{"level": "error", "message": ', "-- log rotated --", "\x00\x01\x02", "caf\u00e9 \u2713 \U0001f600", "2026-13-45 99:99:99 ERROR x",
    "ERROR", "[", "][", "password=hunter2", "x" * 3000, "9" * 500, "The above exception was the direct cause of the following exception:",
]


def random_lines(rng, n):
    out = []
    for _ in range(n):
        frag = rng.choice(FRAGMENTS)
        if rng.random() < 0.2:
            frag = frag[: rng.randint(0, len(frag))]
        if rng.random() < 0.1:
            frag = "".join(rng.choice("abc{}[]\"' :=-.0123456789") for _ in range(rng.randint(0, 60)))
        out.append(frag)
    return out


def test_parser_and_grouper_survive_random_input_and_keep_invariants():
    rng = random.Random(1234)
    for _ in range(150):
        lines = random_lines(rng, rng.randint(0, 80))
        p = LogParser(max_continuation=20)
        events = list(p.parse_lines(lines))
        st = p.stats
        assert st.total_lines == len(lines)
        assert st.total_lines == st.events + st.continuation_lines + st.blank_lines + st.unparsed_lines
        assert st.events == len(events)
        starts = [e.line_no for e in events]
        assert starts == sorted(starts) and all(e.end_line >= e.line_no for e in events)
        assert all(len(e.continuation) <= 20 for e in events)
        res = group_events(events)
        assert sum(g.count for g in res.groups) == res.summary["issue_events"] <= res.summary["total_events"] == len(events)
        assert [g.id for g in res.groups] == [f"G{i:03d}" for i in range(1, len(res.groups) + 1)]


def test_extractor_survives_random_lines():
    rng = random.Random(99)
    for _ in range(200):
        chain = parse_exception_chain(random_lines(rng, rng.randint(0, 30)))
        for exc in chain.exceptions:
            assert exc.type and all(isinstance(f.line, int) and f.line >= 0 for f in exc.frames)
        _ = chain.root, chain.surfaced, chain.raise_site, chain.all_frames


def test_helpers_are_total_functions_on_random_text():
    rng = random.Random(7)
    for _ in range(300):
        text = "".join(rng.choice(FRAGMENTS[:12] + ["@", "=", "://", " ", "\n"]) for _ in range(rng.randint(0, 12)))
        assert isinstance(normalize_message(text), str)
        assert redact(text).text is not None
        parse_timestamp(text)
        once = redact(text).text
        assert redact(once).text == once                       # redaction is idempotent


def test_deeply_nested_json_does_not_crash_anything():
    deep = '{"a": ' + "[" * 15000 + "]" * 15000 + "}"
    p = LogParser()
    assert list(p.parse_lines([deep])) == [] and p.stats.unparsed_lines == 1
    try:
        extract_json(deep)
        raise AssertionError("should have been rejected")
    except LLMValidationError as exc:
        assert "nested too deeply" in str(exc)


def test_deeply_nested_code_does_not_crash_the_chunker():
    src = "x = " + "(" * 5000 + "1" + ")" * 5000
    chunks, _ = chunk_file(SourceFile("a.py", __import__("pathlib").Path("a.py"), "python", src.split("\n")))
    assert isinstance(chunks, list)


def test_unclosed_braces_stay_bounded_in_time():
    js = "\n".join(f"function f{i}() {{" for i in range(3000))
    t0 = time.perf_counter()
    chunks, _ = chunk_file(SourceFile("a.js", __import__("pathlib").Path("a.js"), "javascript", js.split("\n")))
    assert len(chunks) >= 3000 and time.perf_counter() - t0 < 30


ADVERSARIAL = ["a." * 10000, "A." * 10000 + "!", "password=" * 2000, "eyJ" * 6000, "sk-" * 6000, "ghp_" * 5000,
               "-----BEGIN PRIVATE KEY-----" * 700, "a@" * 10000, "a" * 20000 + "@", "a://" * 5000 + "u:p", "token:" * 3000,
               "[" * 20000, "9" * 20000, "ab12" * 5000, " " * 20000, "<" * 20000]


def test_regexes_do_not_blow_up_on_adversarial_lines():
    """Regression: redaction used to take ~19 s on a 20,000-character 'a.a.a.' line (quadratic regex)."""
    worst = 0.0
    for text in ADVERSARIAL:
        for fn in (lambda t: redact(t), normalize_message, parse_timestamp,
                   lambda t: list(LogParser().parse_lines([t, "  " + t])), lambda t: parse_exception_chain([t, "  " + t])):
            t0 = time.perf_counter()
            fn(text)
            worst = max(worst, time.perf_counter() - t0)
    assert worst < 3.0, worst
