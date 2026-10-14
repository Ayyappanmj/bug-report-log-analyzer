"""Streamlit entry point: `streamlit run app.py`."""
import streamlit as st

from ui import analyzer, code_viewer, dashboard, error_groups, history, reports, root_cause, settings_page
from ui import state as S

RENDERERS = {
    "Dashboard": dashboard.render, "Log Analyzer": analyzer.render, "Error Groups": error_groups.render,
    "Root Cause Analysis": root_cause.render, "Code Explorer": code_viewer.render, "Bug Report": reports.render,
    "History": history.render, "Settings": settings_page.render,
}


def main() -> None:
    st.set_page_config(page_title="Bug Report & Log Analyzer Agent", page_icon="🐞", layout="wide")
    S.init()
    st.sidebar.title("🐞 Log Analyzer Agent")
    st.sidebar.radio("Navigation", S.PAGES, key="page", label_visibility="collapsed")
    run = S.current()
    if run is not None:
        st.sidebar.caption(f"Current: {run['log_name']} · {run['dashboard']['total_events']:,} events · "
                           f"{run['dashboard']['unique_errors']} error group(s)")
    st.sidebar.caption(f"AI: {S.settings().ai_provider if S.settings().ai_provider != 'none' else 'deterministic mode'}")
    st.sidebar.warning("Do not upload confidential production logs unless your organization permits it.")
    RENDERERS[st.session_state["page"]]()


main()
