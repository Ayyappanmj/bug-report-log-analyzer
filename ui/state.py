"""Session state and the glue between Streamlit and the analysis pipeline."""
from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import streamlit as st

from agent.orchestrator import AnalysisPipeline
from ai.base import AIProviderError, get_provider
from ai.enhancer import LLMEnhancer
from config import Settings, apply_overrides
from reports.jira import JiraTicket, build_ticket
from storage.database import HistoryDB

from . import viewmodels as vm

PAGES = ["Dashboard", "Log Analyzer", "Error Groups", "Root Cause Analysis", "Code Explorer", "Bug Report", "History", "Settings"]
DEFAULTS = {"page": "Dashboard", "run": None, "run_dict": None, "pipeline": None, "source": "none", "tickets": {},
            "selected_group": None, "overrides": {}, "history_id": None, "auto_analyze": False, "history_error": None}


def init() -> None:
    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = dict(value) if isinstance(value, dict) else value


def settings() -> Settings:
    return apply_overrides(Settings.from_env(), st.session_state["overrides"])


def goto(page: str) -> None:
    """Button callback: switch page (callbacks run before the next script run, so this is safe)."""
    st.session_state["page"] = page


def request_demo_run() -> None:
    load_demo()
    st.session_state["auto_analyze"] = True
    goto("Log Analyzer")


def load_demo() -> None:
    st.session_state["log_path_text"] = str(vm.DEMO_LOG)
    st.session_state["repo_path_text"] = str(vm.DEMO_PROJECT)


def current() -> dict | None:
    return st.session_state["run_dict"]


def live_run():
    return st.session_state["run"]


def is_live() -> bool:
    return st.session_state["source"] == "live" and st.session_state["run"] is not None


def make_pipeline(s: Settings, use_ai: bool) -> tuple[AnalysisPipeline, str | None]:
    enhancer, notice = None, None
    if use_ai:
        kind = s.ai_provider if s.ai_provider != "none" else "ollama"
        try:
            enhancer = LLMEnhancer(get_provider(dataclasses.replace(s, ai_provider=kind)), timeout=s.ai_timeout,
                                   redact_emails=s.redact_emails)
        except AIProviderError as exc:
            notice = f"AI refinement skipped: {exc}"
    return AnalysisPipeline(top_n=8, enhancer=enhancer, ai_top_n=s.ai_top_n, max_log_mb=s.max_log_size_mb), notice


def set_live(run, pipeline) -> None:
    groups = run.grouping.groups
    st.session_state.update(run=run, pipeline=pipeline, run_dict=run.to_dict(), source="live", tickets={},
                            selected_group=groups[0].id if groups else None, history_id=None)


def refresh() -> None:
    st.session_state["run_dict"] = st.session_state["run"].to_dict()


def analyze_more(gid: str) -> str | None:
    """Analyze one more group. Returns an error message instead of raising."""
    try:
        st.session_state["pipeline"].analyze_group(st.session_state["run"], gid)
    except Exception as exc:  # noqa: BLE001
        return f"Could not analyze {gid}: {type(exc).__name__}: {exc}"
    st.session_state["tickets"].pop(gid, None)
    refresh()
    return None


def ticket_for(gid: str) -> JiraTicket | None:
    """Ticket draft for an analyzed group (built on demand for live runs, restored for saved runs)."""
    cache = st.session_state["tickets"]
    if is_live():
        if gid not in cache:
            s = settings()
            cache[gid] = build_ticket(st.session_state["run"], gid, redact_emails=s.redact_emails)
        return cache[gid]
    data = cache.get(gid)
    return JiraTicket.from_dict(data) if data else None


def db() -> HistoryDB:
    path = Path(settings().db_path)
    return HistoryDB(path if path.is_absolute() else vm.ROOT / path)


def save_history() -> int | None:
    s = settings()
    if not s.history_enabled or not is_live():
        return None
    st.session_state["history_error"] = None
    try:
        run = st.session_state["run"]
        tickets = {gid: build_ticket(run, gid, redact_emails=s.redact_emails).to_dict() for gid in run.reports}
        return db().save(st.session_state["run_dict"], tickets, redact_emails=s.redact_emails)
    except (sqlite3.Error, OSError, ValueError, KeyError) as exc:
        st.session_state["history_error"] = f"{type(exc).__name__}: {exc}"
        return None


def load_history(run_id: int) -> None:
    data = db().load(run_id)
    if data is None:
        return
    groups = data["run"]["grouping"]["groups"]
    st.session_state.update(run=None, pipeline=None, run_dict=data["run"], source="history", tickets=data["tickets"],
                            selected_group=groups[0]["id"] if groups else None, history_id=run_id, page="Dashboard")


def clear_run() -> None:
    st.session_state.update(run=None, pipeline=None, run_dict=None, source="none", tickets={}, selected_group=None, history_id=None)
