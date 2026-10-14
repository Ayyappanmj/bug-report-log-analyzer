import io
import json

from pytest import raises

from agent.orchestrator import AnalysisPipeline
from code_analyzer.scanner import ScanError
from log_analyzer.ingest import IngestError
from scripts.generate_demo_log import OUT, SRC

REPO = SRC.parent


def test_run_from_paths_reports_measured_dashboard_and_timings():
    run = AnalysisPipeline(top_n=3).run(OUT, REPO)
    d = run.dashboard
    assert d["total_events"] == run.parse_stats.events == run.grouping.summary["total_events"]
    assert d["files_analyzed"] == 3 and d["total_log_lines"] == run.parse_stats.total_lines
    assert list(run.reports) == ["G001", "G002", "G003"]
    t = run.timings
    assert all(t[k] >= 0 for k in ("parse", "group", "index", "retrieval", "analysis", "total"))
    assert t["total"] >= t["parse"] + t["group"] + t["index"] - 1e-6
    assert d["analysis_seconds"] == round(t["total"], 3)
    assert run.ai_provider.startswith("none")


def test_run_from_upload_stream_matches_path_run():
    with open(OUT, "rb") as f:
        stream = io.BytesIO(f.read())
    a = AnalysisPipeline(top_n=2).run(stream, REPO, log_name="up.log")
    b = AnalysisPipeline(top_n=2).run(OUT, REPO)
    assert a.log_name == "up.log" and a.grouping.summary == b.grouping.summary
    assert a.reports["G001"].to_dict() == b.reports["G001"].to_dict()


def test_run_without_repository_still_analyzes():
    run = AnalysisPipeline(top_n=2).run(OUT, None)
    assert run.dashboard["files_analyzed"] == 0
    r = run.reports["G001"]
    assert not r.code_location_verified and r.code_context == [] and r.rule_id == "db_pool_timeout"


def test_progress_callback_is_monotonic_and_finishes():
    seen = []
    AnalysisPipeline(top_n=2).run(OUT, REPO, progress=lambda s, f: seen.append((s, f)))
    fracs = [f for _, f in seen]
    assert fracs == sorted(fracs) and fracs[-1] == 1.0 and len(seen) >= 5


def test_bad_inputs_raise_clear_errors(tmp_path):
    with raises(IngestError):
        AnalysisPipeline().run(tmp_path / "missing.log", None)
    bad = tmp_path / "x.exe"
    bad.write_text("x")
    with raises(IngestError):
        AnalysisPipeline().run(bad, None)
    with raises(ScanError):
        AnalysisPipeline().run(OUT, tmp_path / "no_such_repo")


def test_empty_log_produces_empty_but_valid_run(tmp_path):
    p = tmp_path / "empty.log"
    p.write_text("")
    run = AnalysisPipeline().run(p, REPO)
    assert run.reports == {} and run.dashboard["total_events"] == 0 and run.log_span is None
    json.dumps(run.to_dict())


def test_analyze_group_on_demand_and_unknown_group():
    pipe = AnalysisPipeline(top_n=1)
    run = pipe.run(OUT, REPO)
    assert list(run.reports) == ["G001"]
    r = pipe.analyze_group(run, "G005")
    assert r.exception == "KeyError" and r.code_location_verified and "G005" in run.reports
    assert pipe.analyze_group(run, "G005") is r
    with raises(KeyError):
        pipe.analyze_group(run, "G999")


def test_run_is_json_serialisable_and_has_git_slot():
    run = AnalysisPipeline(top_n=2).run(OUT, REPO)
    d = json.loads(json.dumps(run.to_dict()))
    assert d["dashboard"]["unique_errors"] == run.grouping.summary["error_groups"]
    assert "git" in d and set(d["reports"]) == {"G001", "G002"}
