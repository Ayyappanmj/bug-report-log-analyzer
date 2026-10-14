"""Executes every page's code with a recording stand-in for Streamlit (see fake_streamlit.py)."""
import tempfile
from pathlib import Path

from tests.fake_streamlit import FakeUpload, Rerun, installed, page

PAGES = ["dashboard", "analyzer", "error_groups", "root_cause", "code_viewer", "reports", "history", "settings_page"]


def with_env(tmp, fn):
    import os
    old = {k: os.environ.get(k) for k in ("DB_PATH", "STORE_HISTORY", "JIRA_BASE_URL", "JIRA_PROJECT_KEY", "JIRA_API_TOKEN")}
    os.environ.update({"DB_PATH": str(Path(tmp) / "h.db"), "STORE_HISTORY": "true"})
    for k in ("JIRA_BASE_URL", "JIRA_PROJECT_KEY", "JIRA_API_TOKEN"):
        os.environ.pop(k, None)
    try:
        return fn()
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def analyzed(st, S):
    S.init()
    S.load_demo()
    st.click("analyze")
    page("analyzer").render()
    assert st.session_state["run_dict"] is not None


def test_every_page_renders_without_a_run():
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        from ui import state as S

        def go():
            S.init()
            for name in PAGES:
                page(name).render()
            assert st.session_state["run_dict"] is None
            assert any("Go to Log Analyzer" in str(c) for c in st.calls) and st.metrics() == []
        with_env(tmp, go)


def test_demo_flow_load_analyze_and_dashboard_metrics():
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        from ui import state as S

        def go():
            analyzed(st, S)
            d = st.session_state["run_dict"]
            assert d["dashboard"]["total_events"] > 3000 and st.session_state["source"] == "live" and st.session_state["selected_group"] == "G001"
            assert st.progress_log and st.progress_log[-1][0] == 1.0 and st.progress_log[0][0] < st.progress_log[-1][0]
            assert any("Saved to History" in t for t in st.texts("success") if t)
            st.calls.clear()
            page("dashboard").render()
            labels = [m[0] for m in st.metrics()]
            assert labels == ["Total Events", "Unique Errors", "Critical Errors", "Recurring Errors", "Files Analyzed", "Analysis Duration"]
            assert dict(st.metrics())["Total Events"] == f"{d['dashboard']['total_events']:,}"
        with_env(tmp, go)


def test_dashboard_demo_button_requests_auto_analysis():
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        from ui import state as S

        def go():
            S.init()
            st.click("dash_demo")
            page("dashboard").render()
            assert st.session_state["page"] == "Log Analyzer" and st.session_state["auto_analyze"] is True
            page("analyzer").render()                         # runs without pressing Analyze
            assert st.session_state["run_dict"] is not None and st.session_state["auto_analyze"] is False
        with_env(tmp, go)


def test_all_pages_render_with_a_live_run_and_walk_the_incident_flow():
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        from ui import state as S

        def go():
            analyzed(st, S)
            for name in PAGES:
                page(name).render()
            md = " ".join(st.texts("markdown") + st.texts("code") + [str(t) for t in st.texts("success")])
            assert "MEASURED" in md and "DatabaseConnectionTimeout" in md and "raise DatabaseConnectionTimeout(" in md
            assert "HYPOTHESIS" in " ".join(str(t) for t in st.texts("warning"))
            assert len(st.downloads) == 4 and {d[1] for d in st.downloads} == {
                "bug-report-G001.md", "bug-report-G001.txt", "bug-report-G001.json", "bug-report-G001.jira.txt"}
            S.goto("Root Cause Analysis")
            assert st.session_state["page"] == "Root Cause Analysis"
        with_env(tmp, go)


def test_error_group_filters_and_on_demand_analysis():
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        from ui import state as S

        def go():
            analyzed(st, S)
            st.session_state["selected_group"] = "G006"          # beyond the analyzed top 8? G006 is analyzed; use G009 if present
            groups = st.session_state["run_dict"]["grouping"]["groups"]
            unanalyzed = [g["id"] for g in groups if g["id"] not in st.session_state["run_dict"]["reports"]]
            st.session_state["eg_sev"] = ["CRITICAL"]
            page("error_groups").render()
            assert any("1 of" in str(t) for t in st.texts("caption"))
            st.session_state["eg_sev"] = ["HIGH"]
            st.session_state["eg_query"] = "zzzz-no-match"
            st.calls.clear()
            page("error_groups").render()
            assert "No groups match these filters." in st.texts("warning")
            if unanalyzed:
                st.session_state["eg_query"], st.session_state["eg_sev"] = "", ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
                st.session_state["selected_group"] = unanalyzed[0]
                st.click("eg_analyze")
                try:
                    page("error_groups").render()
                except Rerun:
                    pass
                assert unanalyzed[0] in st.session_state["run_dict"]["reports"]
        with_env(tmp, go)


def test_upload_flow_and_validation_errors():
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        from ui import state as S

        def go():
            S.init()
            st.session_state["log_path_text"] = ""
            st.click("analyze")
            page("analyzer").render()
            assert "Choose a log first (upload, path, or Load demo)." in st.texts("error")
            st.uploads["log_upload"] = FakeUpload("evil.exe", b"x")
            page("analyzer").render()
            assert st.session_state["run_dict"] is None
            data = (Path(__file__).resolve().parent.parent / "demo" / "logs" / "production_sample.log").read_bytes()
            st.uploads["log_upload"] = FakeUpload("mine.log", data)
            st.session_state["repo_path_text"] = ""
            st.click("analyze")
            page("analyzer").render()
            d = st.session_state["run_dict"]
            assert d["log_name"] == "mine.log" and d["dashboard"]["files_analyzed"] == 0
            st.session_state["repo_path_text"] = str(Path(tmp) / "missing-folder")
            st.uploads["log_upload"] = FakeUpload("mine.log", data)
            st.click("analyze")
            st.calls.clear()
            page("analyzer").render()
            assert any("Project folder not found" in str(t) for t in st.texts("error"))
        with_env(tmp, go)


def test_history_save_open_delete():
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        from ui import state as S

        def go():
            analyzed(st, S)
            assert S.db().count() == 1
            run_id = S.db().list()[0]["id"]
            S.clear_run()
            st.click("hist_open")
            st.session_state["hist_pick"] = run_id
            page("history").render()
            assert st.session_state["source"] == "history" and st.session_state["page"] == "Dashboard"
            for name in ("dashboard", "error_groups", "root_cause", "code_viewer", "reports"):
                page(name).render()
            assert len(st.downloads) >= 4                                   # saved tickets re-render into downloads
            st.session_state["page"] = "History"
            st.click("hist_delete")
            try:
                page("history").render()
            except Rerun:
                pass
            assert S.db().count() == 0
        with_env(tmp, go)


def test_bug_report_review_marks_status_and_blocks_jira_without_config():
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        from ui import state as S

        def go():
            analyzed(st, S)
            st.session_state["br_reviewed_G001"] = True
            st.session_state["br_reviewer_G001"] = "Sam"
            st.session_state["br_title_G001"] = "Edited title"
            page("reports").render()
            assert any(str(t).startswith("REVIEWED by Sam") for t in st.texts("success") if t)
            assert any("Jira is not configured" in str(t) for t in st.texts("caption"))
            code = [c[1][0] for c in st.calls if c[0] == "code"]
            assert any("Edited title" in str(t) for t in code)
        with_env(tmp, go)


def test_settings_overrides_apply_to_the_session():
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        from ui import state as S

        def go():
            S.init()
            st.session_state["set_top_n"], st.session_state["set_max_mb"] = 1, 5
            st.session_state["set_store"] = False
            st.click("set_apply")
            page("settings_page").render()
            s = S.settings()
            assert s.ai_top_n == 1 and s.max_log_size_mb == 5 and s.store_history is False
            st.click("set_reset")
            page("settings_page").render()
            assert S.settings().store_history is True
        with_env(tmp, go)


def test_full_app_script_runs_each_page_via_the_router():
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        def go():
            import importlib
            st.session_state["page"] = "Dashboard"
            for name in ("Dashboard", "Log Analyzer", "Error Groups", "Root Cause Analysis", "Code Explorer", "Bug Report", "History", "Settings"):
                st.session_state["page"] = name
                sys_modules_app = importlib.import_module("app") if "app" not in __import__("sys").modules else importlib.reload(__import__("sys").modules["app"])
                assert sys_modules_app is not None
        with_env(tmp, go)
