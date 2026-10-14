"""Failure containment: one bad component must not take the whole analysis down."""
import ast
import io
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from pytest import raises

from agent.orchestrator import AnalysisPipeline
from agent.root_cause_agent import RootCauseAnalyzer
from ai.base import AIProviderError
from ai.enhancer import LLMEnhancer
from ai.ollama_provider import OllamaProvider
from code_analyzer.retriever import CodeRetriever
from code_analyzer.scanner import scan_repository
from code_analyzer.search import CodeIndex
from log_analyzer.extractor import Frame
from reports.jira import JiraConfig, JiraError, build_ticket, create_issue
from scripts.generate_demo_log import OUT, SRC
from tests.fakes import FakeJiraServer, FakeLLMServer, FakeProvider, demo_report, demo_run, good_reply
from tests.helpers import write_repo

REPO = SRC.parent


class ExplodingAnalyzer(RootCauseAnalyzer):
    def analyze(self, group, retrieval=None, all_groups=None, log_span=None):
        if group.id == "G002":
            raise RuntimeError("boom in analysis")
        return super().analyze(group, retrieval, all_groups, log_span)


def test_one_failing_group_is_contained_and_reported():
    run = AnalysisPipeline(analyzer=ExplodingAnalyzer(), top_n=4).run(OUT, REPO)
    assert sorted(run.reports) == ["G001", "G003", "G004"]
    assert run.errors == [{"group_id": "G002", "stage": "analysis", "error": "RuntimeError: boom in analysis"}]
    assert run.to_dict()["errors"] == run.errors and run.dashboard["total_events"] > 0


class BrokenProvider(FakeProvider):
    def is_available(self):
        raise RuntimeError("availability check exploded")


class BadGenerate(FakeProvider):
    def generate(self, prompt, system=None, timeout=60.0):
        raise ValueError("unexpected provider bug")


def test_enhancer_never_raises_even_for_misbehaving_providers():
    for prov in (BrokenProvider(["x"]), BadGenerate(["x"])):
        out = LLMEnhancer(prov, backoff=0).enhance(demo_report())
        assert not out.used and out.fallback_reason.startswith("unexpected error:") and not out.report.ai_enhanced
        assert out.report.probable_root_cause == demo_report().probable_root_cause


def test_pipeline_survives_a_provider_that_crashes():
    run = AnalysisPipeline(top_n=2, enhancer=LLMEnhancer(BadGenerate(["x"]), backoff=0), ai_top_n=2).run(OUT, REPO)
    assert sorted(run.reports) == ["G001", "G002"] and all(x["fallback_reason"] for x in run.ai_log)


def test_slow_llm_times_out_and_falls_back_end_to_end():
    with FakeLLMServer(replies=[good_reply()]) as srv:
        srv.delay = 1.5
        enhancer = LLMEnhancer(OllamaProvider(srv.url, "qwen2.5-coder:7b"), timeout=0.3, backoff=0, max_retries=1)
        t0 = time.perf_counter()
        run = AnalysisPipeline(top_n=1, enhancer=enhancer, ai_top_n=1).run(OUT, REPO)
        elapsed = time.perf_counter() - t0
    r = run.reports["G001"]
    assert not r.ai_enhanced and "provider error" in r.ai_fallback_reason and r.ai_attempts == 2
    assert elapsed < 20 and run.dashboard["total_events"] > 3000          # analysis finished despite the stalled model


def test_jira_timeout_is_a_clean_error_without_leaking_the_token():
    with FakeJiraServer() as srv:
        srv.delay = 1.5
        with raises(JiraError) as ei:
            create_issue(build_ticket(demo_run(), "G001"), JiraConfig(srv.url, "PAY", "TOKEN123", "a@b.c"), confirm=True, timeout=0.3)
    assert "Cannot reach Jira" in str(ei.value) and "TOKEN123" not in str(ei.value)


def test_malformed_and_binary_inputs_produce_a_valid_empty_run():
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 50
    run = AnalysisPipeline().run(io.BytesIO(png), None, log_name="fake.log")
    assert run.parse_stats.events == 0 and run.reports == {} and run.grouping.groups == []
    assert run.dashboard["unique_errors"] == 0 and run.parse_stats.unparsed_lines > 0
    from ui.viewmodels import unparsed_warning
    assert "No log events were recognized" in unparsed_warning(run.to_dict())


def test_log_with_only_info_events_has_no_groups():
    log = b"2026-09-30 10:00:00 INFO [S] [T] [req=1] fine\n" * 20
    run = AnalysisPipeline().run(io.BytesIO(log), None)
    assert run.parse_stats.events == 20 and run.grouping.groups == [] and run.dashboard["unique_errors"] == 0


def test_empty_repository_folder_gives_no_code_but_still_analyzes():
    with tempfile.TemporaryDirectory() as d:
        run = AnalysisPipeline(top_n=2).run(OUT, d)
    r = run.reports["G001"]
    assert run.dashboard["files_analyzed"] == 0 and r.code_context == [] and not r.code_location_verified
    assert any("No source code could be located" in e.text for e in r.observed_evidence)


def test_source_file_missing_or_renamed_is_reported_not_invented(tmp_path):
    proj = tmp_path / "p" / "src"
    proj.mkdir(parents=True)
    for f in (REPO / "src").glob("*.py"):
        if f.name != "database.py":                         # the file holding the raise site is gone
            (proj / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    run = AnalysisPipeline(top_n=1).run(OUT, proj.parent)
    r = run.reports["G001"]
    assert not any(c["file_path"] == "src/database.py" for c in r.code_context)
    assert not any("raise DatabaseConnectionTimeout(" in (c.get("snippet") or "") for c in r.code_context)
    assert any("innermost stack frame (src/database.py:" in n for n in r.notes)
    assert {c["file_path"] for c in r.code_context if c["verified"]} == {"src/payment_service.py", "src/checkout.py"}


def test_retriever_tolerates_nonsense_frames(tmp_path):
    rt = CodeRetriever(CodeIndex.build(write_repo(tmp_path, {"src/a.py": "def f():\n    return 1\n", "empty.py": ""})))
    nonsense = [Frame("", 0, "", None, "python"), Frame("..", -5, "f", "x", "python"), Frame("////", 10**9, "<module>", None, "python"),
                Frame("C:", 1, "f", "return 1", "python"), Frame("a" * 5000 + ".py", 1, "f", None, "python"),
                Frame("src/a.py", 10**9, "f", "return 1", "python"), Frame("empty.py", 1, "g", "x", "python"),
                Frame("src/a.py", 0, "f", None, "java"), Frame("\x00.py", 1, "f", None, "javascript")]
    for fr in nonsense:
        ctx = rt.retrieve_for_frame(fr)
        assert ctx.status and isinstance(ctx.verified, bool)
        assert not (ctx.verified and ctx.file_path is None)


def test_unreadable_source_file_is_skipped_not_fatal(tmp_path):
    write_repo(tmp_path, {"a.py": "x = 1\n", "b.py": "y = 2\n"})
    with patch("pathlib.Path.read_bytes", side_effect=PermissionError("denied")):
        scan = scan_repository(tmp_path)
    assert scan.stats.files_scanned == 0 and scan.stats.skipped["unreadable"] == 2


def test_history_failure_does_not_break_the_ui_flow():
    from tests.fake_streamlit import installed, page
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        import os
        os.environ["DB_PATH"] = tmp                      # a directory, so SQLite cannot open it as a file
        os.environ["STORE_HISTORY"] = "true"
        from ui import state as S
        S.init()
        S.load_demo()
        st.click("analyze")
        page("analyzer").render()
        assert st.session_state["run_dict"] is not None and st.session_state["history_error"]
        assert any("could not be saved to History" in str(t) for t in st.texts("warning"))
    os.environ.pop("DB_PATH", None)


def test_ui_analyze_more_returns_an_error_message_instead_of_raising():
    from tests.fake_streamlit import installed
    with installed() as st:
        from ui import state as S
        S.init()

        class Boom:
            def analyze_group(self, *a, **k):
                raise KeyError("nope")
        st.session_state["pipeline"], st.session_state["run"] = Boom(), object()
        msg = S.analyze_more("G009")
        assert msg and "Could not analyze G009" in msg and "KeyError" in msg


def test_bad_environment_values_fall_back_to_defaults():
    from config import Settings
    s = Settings.from_env(env={"AI_TOP_N": "many", "MAX_LOG_SIZE_MB": "", "AI_TIMEOUT_SECONDS": "-"})
    assert (s.ai_top_n, s.max_log_size_mb, s.ai_timeout) == (3, 50, 120)


def test_unreachable_ollama_never_blocks_deterministic_analysis():
    prov = OllamaProvider("http://127.0.0.1:9", "m")
    run = AnalysisPipeline(top_n=1, enhancer=LLMEnhancer(prov, timeout=1), ai_top_n=1).run(OUT, REPO)
    assert "unavailable" in run.ai_log[0]["fallback_reason"] and run.reports["G001"].code_location_verified


def test_report_schema_stays_in_sync_with_the_pydantic_model():
    """Without importing pydantic: every field of RootCauseAnalysis must exist in RootCauseReport.to_dict()."""
    tree = ast.parse((Path(__file__).resolve().parent.parent / "ai" / "schemas.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RootCauseAnalysis")
    fields = {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign)}
    keys = set(demo_report().to_dict())
    assert fields <= keys, sorted(fields - keys)
    omitted = keys - fields
    assert omitted == {"rule_id", "pattern", "code_strategy", "disclaimer", "notes"}, sorted(omitted)
