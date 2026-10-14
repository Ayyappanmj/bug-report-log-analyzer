"""Runs the real app.py with Streamlit's own headless AppTest. Skipped when streamlit is not installed.

This is the check that the actual Streamlit API calls work (the fake in test_ui_pages.py cannot prove that).
"""
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["Dashboard", "Log Analyzer", "Error Groups", "Root Cause Analysis", "Code Explorer", "Bug Report", "History", "Settings"]


def fresh_app(tmp):
    os.environ["DB_PATH"] = str(Path(tmp) / "history.db")
    for k in ("AI_PROVIDER", "JIRA_BASE_URL", "JIRA_PROJECT_KEY", "JIRA_API_TOKEN"):
        os.environ.pop(k, None)
    return AppTest.from_file(APP, default_timeout=120)


def test_app_starts_and_every_page_renders_without_a_run():
    with tempfile.TemporaryDirectory() as tmp:
        at = fresh_app(tmp).run()
        assert not at.exception
        for page in PAGES:
            at.session_state["page"] = page
            at.run()
            assert not at.exception, (page, [e.value for e in at.exception])


def test_demo_flow_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        at = fresh_app(tmp).run()
        at.button(key="dash_demo").click().run()          # Load demo + analyze
        assert not at.exception and at.session_state["run_dict"] is not None
        at.session_state["page"] = "Dashboard"
        at.run()
        assert not at.exception and len(at.metric) >= 6
        assert [m.label for m in at.metric][:6] == ["Total Events", "Unique Errors", "Critical Errors", "Recurring Errors",
                                                    "Files Analyzed", "Analysis Duration"]
        for page in PAGES[2:]:
            at.session_state["page"] = page
            at.run()
            assert not at.exception, (page, [e.value for e in at.exception])
