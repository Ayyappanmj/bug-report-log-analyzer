"""Large-input behaviour. Assertions are about correctness and bounded memory, never wall-clock speed."""
import io
import random
import tracemalloc

import pytest
from pytest import raises

from agent.orchestrator import AnalysisPipeline
from log_analyzer.grouper import group_events
from log_analyzer.ingest import IngestError, iter_log_lines, parse_log_file
from log_analyzer.models import LogEvent
from scripts.generate_demo_log import SRC

TEMPLATES = [
    ("ERROR", "PaymentService", "Charge failed for order=ORD-{n} after {m}ms"),
    ("ERROR", "Inventory", "Stock lookup failed sku=SKU-{n}"),
    ("WARN", "Cache", "Eviction storm detected size={n}"),
]


def write_big_log(path, target_bytes, seed=5):
    """Interleaves INFO noise with three known problem templates; returns the exact count of each template."""
    rng = random.Random(seed)
    counts = [0, 0, 0]
    written, i = 0, 0
    with open(path, "w", encoding="utf-8") as f:
        while written < target_bytes:
            i += 1
            ts = f"2026-09-30 {10 + (i // 3600) % 10:02d}:{(i // 60) % 60:02d}:{i % 60:02d},{i % 1000:03d}"
            if rng.random() < 0.08:
                k = rng.randrange(3)
                lvl, svc, msg = TEMPLATES[k]
                counts[k] += 1
                line = f"{ts} {lvl:<5} [{svc}] [Thread-{i % 9}] [req={i:06x}] {msg.format(n=rng.randint(1, 10**6), m=rng.randint(10, 9999))}\n"
            else:
                line = f"{ts} INFO  [Svc] [Thread-1] [req={i:06x}] request handled ok in {i % 500}ms path=/api/items/{i}\n"
            f.write(line)
            written += len(line)
    return counts


@pytest.mark.slow
def test_5mb_log_parses_and_groups_exactly(tmp_path):
    p = tmp_path / "big.log"
    counts = write_big_log(p, 5 * 1024 * 1024)
    assert p.stat().st_size >= 5 * 1024 * 1024
    r = parse_log_file(p)
    assert r.stats.unparsed_lines == 0 and r.stats.events == r.stats.total_lines > 30000
    res = group_events(r.events)
    assert sorted(g.count for g in res.groups) == sorted(counts) and len(res.groups) == 3
    assert res.summary["total_events"] == r.stats.events


@pytest.mark.slow
def test_5mb_log_runs_through_the_whole_pipeline(tmp_path):
    p = tmp_path / "big.log"
    counts = write_big_log(p, 5 * 1024 * 1024, seed=11)
    run = AnalysisPipeline(top_n=3).run(p, SRC.parent)
    assert run.dashboard["total_events"] == run.parse_stats.events
    assert sorted(g.count for g in run.grouping.groups) == sorted(counts) and len(run.reports) == 3
    assert run.timings["total"] >= run.timings["parse"]


def test_reading_a_huge_file_is_streamed_not_loaded(tmp_path):
    p = tmp_path / "huge.log"
    line = "2026-09-30 10:00:00 INFO [S] [T] [req=1] " + "x" * 80 + "\n"
    with open(p, "w") as f:
        for _ in range(300_000):                       # ~ 36 MB
            f.write(line)
    assert p.stat().st_size > 30_000_000
    tracemalloc.start()
    first = [l for _, l in zip(range(10), iter_log_lines(p))]
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert len(first) == 10 and peak < 5_000_000


def test_one_giant_line_is_truncated_with_bounded_memory(tmp_path):
    p = tmp_path / "oneline.log"
    p.write_text("2026-09-30 10:00:00 ERROR [S] [T] [req=1] " + "y" * 8_000_000)
    tracemalloc.start()
    r = parse_log_file(p)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert r.stats.events == 1 and r.stats.truncated_lines == 1 and len(r.events[0].raw) < 21_000 and peak < 10_000_000


def test_huge_stack_trace_is_capped_and_counted():
    lines = ["2026-09-30 10:00:00 ERROR [S] [T] [req=1] deep recursion"] + [f"  File \"a.py\", line {i}, in f" for i in range(100_000)]
    from log_analyzer.parser import LogParser
    p = LogParser()
    ev = list(p.parse_lines(lines))
    assert len(ev) == 1 and len(ev[0].continuation) == 500
    assert p.stats.continuation_lines == 100_000 and p.stats.dropped_continuation_lines == 99_500


@pytest.mark.slow
def test_many_distinct_groups_skip_the_quadratic_merge_step():
    rng = random.Random(3)
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima"]
    events = [LogEvent(i, "t", "x", message=" ".join(rng.sample(words, 6)) + f" {''.join(rng.choice('qwxz') for _ in range(12))}",
                       level="ERROR", service=f"S{i % 7}") for i in range(2600)]
    res = group_events(events)
    assert res.summary["total_events"] == 2600 and sum(g.count for g in res.groups) == 2600
    assert len(res.groups) > 2000                          # above max_merge_groups the fuzzy merge is skipped


def test_size_limits_are_enforced_in_the_pipeline(tmp_path):
    p = tmp_path / "two_mb.log"
    p.write_bytes(b"2026-09-30 10:00:00 INFO [S] [T] [req=1] x\n" * 50_000)
    assert p.stat().st_size > 2_000_000
    with raises(IngestError):
        AnalysisPipeline(max_log_mb=1).run(p, None)
    assert AnalysisPipeline(max_log_mb=5).run(p, None).parse_stats.events == 50_000


def test_stream_input_with_many_lines_matches_file_input(tmp_path):
    p = tmp_path / "s.log"
    write_big_log(p, 300_000, seed=2)
    a = AnalysisPipeline(top_n=3).run(p, None)
    b = AnalysisPipeline(top_n=3).run(io.BytesIO(p.read_bytes()), None, log_name="s.log")
    assert a.grouping.summary == b.grouping.summary and a.parse_stats.to_dict() == b.parse_stats.to_dict()
