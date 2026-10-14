import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent.orchestrator import AnalysisPipeline
from benchmarks import report as R
from benchmarks.loggen import generate_log
from benchmarks.machine import machine_info, peak_memory_mb
from benchmarks.scenarios import build_scenarios, check_truth
from log_analyzer.grouper import group_events
from log_analyzer.ingest import parse_log_file
from scripts import benchmark as B
from scripts import compare_workflows as CW
from scripts import manual_baseline as MB
from scripts.generate_demo_log import SRC

TRIALS = lambda: [  # noqa: E731
    {"scenario": "s1", "mode": "manual", "seconds": 600, "correct": True, "participant": "Sam"},
    {"scenario": "s1", "mode": "manual", "seconds": 900, "correct": True, "participant": "Sam"},
    {"scenario": "s1", "mode": "manual", "seconds": 30, "correct": False, "participant": "Sam"},     # fast but wrong: excluded
    {"scenario": "s1", "mode": "assisted", "seconds": 100, "correct": True, "participant": "Sam"},
    {"scenario": "s1", "mode": "assisted", "seconds": 140, "correct": True, "participant": "Sam"},
    {"scenario": "s2", "mode": "manual", "seconds": 300, "correct": True, "participant": "Sam"},
    {"scenario": "s2", "mode": "assisted", "seconds": 60, "correct": True, "participant": "Sam"},
]


def bench(ai=None, correct=True):
    t = lambda m: {"median": m, "min": m, "max": m, "n": 3}  # noqa: E731
    return {"meta": {"processor": "TestCPU", "os": "T", "cpu_count": 4, "ram_gb": 16, "python": "3.12", "tool_version": "0.11",
                     "timestamp": "2026-01-01T00:00:00", "git_commit": None},
            "settings": {"repeats": 3, "sizes": [1, 10], "ai": "none"},
            "sizes": [{"actual_mb": 1.0, "lines": 1, "events": 1, "error_groups": 2, "correct": True, "timings": {"total": t(0.5), "parse": t(0.4)},
                       "throughput_mb_s": 2.0, "peak_memory_mb": 10},
                      {"actual_mb": 9.7, "lines": 9, "events": 9, "error_groups": 7, "correct": correct,
                       "timings": {k: t(3.21) for k in ("total", "parse", "group", "index", "retrieval", "analysis")},
                       "throughput_mb_s": 3.0, "peak_memory_mb": 99.5}],
            "scenarios": [{"name": "a", "events": 5, "groups": 1, "seconds": t(0.1), "report_generated": True,
                           "checks": {"group_found": True, "raise_site_correct": True, "code_verified_at_truth": True,
                                      "failing_line_shown": True, "rule_correct": True, "all_correct": True}},
                          {"name": "b", "events": 5, "groups": 1, "seconds": t(0.1), "report_generated": True,
                           "checks": {"group_found": True, "raise_site_correct": False, "code_verified_at_truth": False,
                                      "failing_line_shown": False, "rule_correct": True, "all_correct": False}}],
            "ai": ai or {"status": "not measured", "reason": "no"}}


# ------------------------------------------------------------------ generator
def test_generator_is_deterministic_and_hits_the_target_size(tmp_path):
    a = generate_log(tmp_path / "a.log", 0.3, seed=1)
    b = generate_log(tmp_path / "b.log", 0.3, seed=1)
    c = generate_log(tmp_path / "c.log", 0.3, seed=2)
    assert (tmp_path / "a.log").read_bytes() == (tmp_path / "b.log").read_bytes() != (tmp_path / "c.log").read_bytes()
    assert 0.3 * 1024 * 1024 <= a.bytes_written < 0.3 * 1024 * 1024 + 5000 and (tmp_path / "a.log").stat().st_size == a.bytes_written
    assert a.counts == b.counts and a.counts != c.counts


def test_generator_counts_match_what_the_pipeline_finds(tmp_path):
    info = generate_log(tmp_path / "g.log", 0.5)
    r = parse_log_file(tmp_path / "g.log")
    assert r.stats.unparsed_lines == 0 and r.stats.total_lines == info.lines and r.stats.events == info.events
    res = group_events(r.events)
    assert sorted(g.count for g in res.groups) == info.expected_group_counts
    run = AnalysisPipeline(top_n=5).run(tmp_path / "g.log", SRC.parent)
    top = next(g for g in run.grouping.groups if g.exception_type == "DatabaseConnectionTimeout")
    assert top.count == info.counts["db_timeout_chain"] and run.reports[top.id].code_location_verified


# ------------------------------------------------------------------ machine info
def test_machine_info_and_peak_memory():
    m = machine_info()
    assert {"timestamp", "os", "cpu_count", "ram_gb", "python", "tool_version", "processor"} <= set(m) and m["cpu_count"] >= 1
    mem = peak_memory_mb()
    assert mem is None or mem > 1


# ------------------------------------------------------------------ scenarios
def test_scenarios_have_ground_truth_and_the_tool_gets_them_right(tmp_path):
    scs = build_scenarios(tmp_path)
    assert [s.name for s in scs] == ["demo_db_pool", "inventory_nullref", "report_timeout", "config_missing"]
    for s in scs:
        assert s.log_path.exists() and (s.project_dir / s.truth["file"]).exists()
        run = AnalysisPipeline(top_n=8).run(s.log_path, s.project_dir)
        checks = check_truth(run, s.truth)
        assert checks["all_correct"] and checks["group_rank"] >= 1, (s.name, checks)
        assert MB.failing_line(s) >= 1


def test_scenarios_are_deterministic_and_check_truth_can_fail(tmp_path):
    a = build_scenarios(tmp_path / "a")[1]
    b = build_scenarios(tmp_path / "b")[1]
    assert a.log_path.read_bytes() == b.log_path.read_bytes()
    run = AnalysisPipeline(top_n=8).run(a.log_path, a.project_dir)
    wrong = dict(a.truth, file="src/other.py")
    assert check_truth(run, wrong)["all_correct"] is False and check_truth(run, dict(a.truth, exception_type="NopeError"))["group_found"] is False
    empty_repo = AnalysisPipeline(top_n=8).run(a.log_path, None)
    assert check_truth(empty_repo, a.truth)["all_correct"] is False       # no code -> cannot be 'verified at truth'


# ------------------------------------------------------------------ statistics and bullets
def test_summaries_and_duration_formatting():
    assert R.summarize([3, 1, 2]) == {"median": 2, "min": 1, "max": 3, "n": 3} and R.summarize([])["median"] is None
    assert R.fmt_duration(12.34) == "12.3 s" and R.fmt_duration(150) == "2.5 min"


def test_trial_stats_exclude_wrong_answers():
    s = R.summarize_trials(TRIALS())
    row = next(r for r in s["rows"] if r["scenario"] == "s1")
    assert row["manual"]["median"] == 750 and row["manual"]["n"] == 2 and row["manual_invalid"] == 1
    assert row["assisted"]["median"] == 120 and row["speedup"] == 6.25
    assert s["paired_scenarios"] == 2 and s["median_manual"] == 525 and s["median_assisted"] == 90 and s["manual_valid"] == 3


def test_bullets_use_only_measured_numbers():
    b = {x["id"]: x for x in R.build_bullets(bench(), R.summarize_trials(TRIALS()))}
    assert "10 MB" in b["A"]["text"] and "7 error groups" in b["A"]["text"] and "3.2 seconds" in b["A"]["text"]
    assert "AI-powered" not in b["A"]["text"] and "rule-based" in b["A"]["text"] and b["A"]["note"]
    assert "for 1 benchmark scenarios" in b["B"]["text"] and "local LLM inference" not in b["B"]["text"]
    assert b["C"]["text"] and "8.8 min" in b["C"]["text"] and "1.5 min" in b["C"]["text"] and "2 synthetic scenarios" in b["C"]["text"]
    assert "6 answer-checked trials" in b["C"]["text"]      # 2+1 manual and 2+1 assisted valid trials; the wrong-answer trial is excluded


def test_bullets_mention_ai_only_when_it_was_measured():
    ai = {"status": "measured", "model": "m", "reports_attempted": 4, "reports_refined": 3, "seconds_per_report": {"median": 9, "min": 5, "max": 20, "n": 4}, "failures": []}
    b = {x["id"]: x for x in R.build_bullets(bench(ai=ai), None)}
    assert "AI-powered" in b["A"]["text"] and "LLM-assisted" in b["A"]["text"] and "local LLM inference" in b["B"]["text"]
    none_refined = dict(ai, reports_refined=0)
    assert "AI-powered" not in R.build_bullets(bench(ai=none_refined), None)[0]["text"]


def test_bullets_refuse_without_data_and_say_what_is_missing():
    a, b, c = R.build_bullets(None, None)
    assert a["text"] is None and b["text"] is None and c["text"] is None and all(x["needs"] for x in (a, b, c))
    wrong = R.build_bullets(bench(correct=False), None)[0]
    assert "1 MB" in wrong["text"]                                         # falls back to the largest size whose output was verified
    only_manual = [t for t in TRIALS() if t["mode"] == "manual"]
    c = R.build_bullets(bench(), R.summarize_trials(only_manual))[2]
    assert c["text"] is None and any("ASSISTED" in n for n in c["needs"])
    few = R.summarize_trials(TRIALS()[:1] + TRIALS()[3:4])
    c2 = R.build_bullets(bench(), few)[2]
    assert c2["text"] is None and any("MANUAL" in n or "common scenarios" in n for n in c2["needs"])
    nothing_ok = bench()
    for s in nothing_ok["scenarios"]:
        s["checks"]["all_correct"] = False
    assert R.build_bullets(nothing_ok, None)[1]["text"] is None


def test_markdown_report_states_scope_and_flags_incorrect_output():
    md = R.render_markdown(bench(correct=False))
    assert "THIS machine and synthetic logs only" in md and "**NO**" in md and "Not measured: no." in md and "not that it generalizes" in md
    ai = {"status": "measured", "model": "m", "reports_attempted": 2, "reports_refined": 1, "seconds_per_report": {"median": 9.0, "min": 5.0, "max": 20.0, "n": 2},
          "failures": ["x/G1: invalid"]}
    assert "1 of 2 report(s) refined" in R.render_markdown(bench(ai=ai)) and "Fallbacks: x/G1: invalid" in R.render_markdown(bench(ai=ai))


# ------------------------------------------------------------------ the benchmark script itself
def test_benchmark_worker_reports_correctness_and_memory(tmp_path):
    info = generate_log(tmp_path / "w.log", 0.3)
    res = B.worker(str(tmp_path / "w.log"), 2, info.expected_group_counts)
    assert res["correct"] and res["repeats"] == 2 and res["events"] == info.events and res["lines"] == info.lines
    assert set(res["timings"]) == set(B.STAGES) and res["timings"]["total"]["n"] == 2 and res["throughput_mb_s"] > 0
    wrong = B.worker(str(tmp_path / "w.log"), 1, [1, 2, 3])
    assert wrong["correct"] is False


def test_full_benchmark_run_writes_json_and_markdown(tmp_path):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = B.main(["--sizes", "0.2", "0.4", "--repeats", "1", "--out", str(tmp_path / "res")])
    assert code == 0
    files = sorted((tmp_path / "res").glob("benchmark-*.json"))
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert [s["requested_mb"] for s in data["sizes"]] == [0.2, 0.4] and all(s["correct"] for s in data["sizes"])
    assert len(data["scenarios"]) == 4 and all(s["checks"]["all_correct"] and s["report_generated"] for s in data["scenarios"])
    assert data["ai"]["status"] == "not measured" and data["meta"]["python"] and (tmp_path / "res" / "latest.md").exists()
    assert "Benchmark results" in out.getvalue()


def test_ai_measurement_reports_unavailable_model_honestly(tmp_path):
    from ai.ollama_provider import OllamaProvider
    with patch.object(OllamaProvider, "is_available", lambda self: False), patch.object(OllamaProvider, "unavailable_reason", lambda self: "server down"):
        ai = B.measure_ai("m", tmp_path, log=lambda *_: None)
    assert ai == {"status": "not measured", "reason": "server down"}


def test_ai_measurement_with_a_fake_model_records_real_latencies(tmp_path):
    from tests.fakes import FakeLLMServer, good_reply
    import os
    with FakeLLMServer(replies=[good_reply()]) as srv:
        old = os.environ.get("OLLAMA_HOST")
        os.environ["OLLAMA_HOST"] = srv.url
        try:
            ai = B.measure_ai("qwen2.5-coder:7b", tmp_path, log=lambda *_: None)
        finally:
            os.environ.pop("OLLAMA_HOST", None) if old is None else os.environ.__setitem__("OLLAMA_HOST", old)
    assert ai["status"] == "measured" and ai["reports_attempted"] == 4 and ai["reports_refined"] == 4
    assert ai["seconds_per_report"]["n"] == 4 and ai["seconds_per_report"]["median"] >= 0


# ------------------------------------------------------------------ manual baseline tool
def scenario(tmp):
    return build_scenarios(tmp)[1]


def scripted(answers):
    it = iter(answers)
    return lambda prompt="": next(it)


def ticking(*values):
    it = iter(values)
    return lambda: next(it)


def test_answer_checking():
    with tempfile.TemporaryDirectory() as d:
        sc = scenario(d)
        line = str(MB.failing_line(sc))
        assert MB.check_answers(sc, "AttributeError", "src/inventory.py", line)["correct"]
        assert MB.check_answers(sc, "attributeerror: 'NoneType'...", "src\\inventory.py", f" {line} ")["correct"]
        assert MB.check_answers(sc, "AttributeError", "inventory.py", line)["correct"]
        for bad in (("KeyError", "src/inventory.py", line), ("AttributeError", "src/orders.py", line), ("AttributeError", "src/inventory.py", "3"),
                    ("AttributeError", "src/inventory.py", "abc"), ("", "", "")):
            assert MB.check_answers(sc, *bad)["correct"] is False


def test_manual_trial_is_timed_checked_and_recorded(tmp_path):
    sc = scenario(tmp_path / "sc")
    res = tmp_path / "t.jsonl"
    msgs = []
    rec = MB.run_trial(sc, "manual", "Sam", input_fn=scripted(["", "", "AttributeError", "src/inventory.py", str(MB.failing_line(sc))]),
                       clock=ticking(100.0, 225.0), out=msgs.append, results_path=res)
    assert rec["seconds"] == 125.0 and rec["correct"] and rec["machine_seconds"] == 0.0 and "Do NOT run the analyzer" in " ".join(msgs)
    bad = MB.run_trial(sc, "manual", "Sam", input_fn=scripted(["", "", "KeyError", "src/x.py", "1"]), clock=ticking(0.0, 10.0), out=msgs.append, results_path=res)
    assert bad["correct"] is False and "INVALID" in msgs[-1]
    trials = MB.load_trials(res)
    assert [t["correct"] for t in trials] == [True, False] and trials[0]["participant"] == "Sam" and trials[0]["scenario"] == "inventory_nullref"


def test_assisted_trial_adds_machine_time_and_writes_the_report(tmp_path):
    sc = scenario(tmp_path / "sc")
    res = tmp_path / "t.jsonl"
    msgs = []
    rec = MB.run_trial(sc, "assisted", "Sam", input_fn=scripted(["", "", "AttributeError", "src/inventory.py", str(MB.failing_line(sc))]),
                       clock=ticking(0.0, 40.0), out=msgs.append, results_path=res, report_dir=tmp_path / "rep")
    assert rec["mode"] == "assisted" and rec["human_seconds"] == 40.0 and rec["machine_seconds"] > 0
    assert abs(rec["seconds"] - (40.0 + rec["machine_seconds"])) < 0.01 and rec["correct"]
    report = next((tmp_path / "rep").glob("*.md"))
    assert "AttributeError" in report.read_text(encoding="utf-8") and str(report) in " ".join(msgs)


def test_trial_file_tolerates_corrupt_lines_and_status_output(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps(TRIALS()[0]) + "\nnot json\n" + json.dumps(TRIALS()[3]) + "\n")
    assert len(MB.load_trials(p)) == 2 and MB.load_trials(tmp_path / "missing") == []
    lines = []
    MB.status(MB.load_trials(p), out=lines.append)
    assert "s1" in " ".join(lines)
    empty = []
    MB.status([], out=empty.append)
    assert empty == ["No trials recorded yet."]


def test_prepare_command_prints_cards_without_touching_the_repo(tmp_path):
    buf = io.StringIO()
    with patch.object(MB, "SCENARIOS_DIR", tmp_path / "out"), contextlib.redirect_stdout(buf):
        assert MB.main(["prepare"]) == 0
    text = buf.getvalue()
    assert "inventory_nullref" in text and "Deliverable:" in text and (tmp_path / "out" / "config_missing" / "app.log").exists()


def test_compare_workflows_prints_bullets_only_from_data(tmp_path):
    (tmp_path / "b.json").write_text(json.dumps(bench()), encoding="utf-8")
    trials = tmp_path / "t.jsonl"
    trials.write_text("\n".join(json.dumps(t) for t in TRIALS()) + "\n", encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        CW.main(["--bench", str(tmp_path / "b.json"), "--trials", str(trials)])
    text = buf.getvalue()
    assert "6.25x" in text and "[C] Cut the time" in text and "8.8 min" in text and "NOT AVAILABLE" not in text
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        CW.main(["--bench", str(tmp_path / "nope.json"), "--trials", str(tmp_path / "none.jsonl")])
    assert buf2.getvalue().count("NOT AVAILABLE YET") == 3
    assert CW.newest_benchmark(tmp_path / "empty") is None
