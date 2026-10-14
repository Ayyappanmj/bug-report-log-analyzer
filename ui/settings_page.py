"""Settings page: view effective configuration, session overrides, and a local-LLM connectivity check."""
from __future__ import annotations

import dataclasses

import streamlit as st

from ai.base import AIProviderError, get_provider

from . import state as S


def _jira_state(s) -> str:
    return "configured" if s.jira_base_url and s.jira_project_key and s.jira_api_token else "not configured (optional)"


def render() -> None:
    st.title("Settings")
    s = S.settings()
    st.caption("Defaults come from environment variables or the .env file (see .env.example). Changes here apply to this browser session only.")
    st.json({"ai_provider": s.ai_provider, "ollama_host": s.ollama_host, "ollama_model": s.ollama_model, "api_model": s.api_model or None,
             "api_base_url": s.api_base_url or None, "api_key": "set" if s.api_key else "not set", "ai_top_n": s.ai_top_n,
             "ai_timeout_seconds": s.ai_timeout, "redact_emails": s.redact_emails, "store_history": s.store_history,
             "public_demo": s.public_demo, "local_paths_allowed": s.local_paths_allowed, "max_log_size_mb": s.max_log_size_mb, "excluded_dirs": list(s.excluded_dirs), "jira": _jira_state(s)})

    st.subheader("Session overrides")
    c1, c2 = st.columns(2)
    top_n = c1.slider("Incidents refined by the LLM", 0, 8, s.ai_top_n, key="set_top_n")
    max_mb = c2.number_input("Max log size (MB)", min_value=1, max_value=500, value=s.max_log_size_mb, key="set_max_mb")
    model = st.text_input("Ollama model", value=s.ollama_model, key="set_model")
    redact_emails = st.toggle("Redact email addresses in prompts and exports", value=s.redact_emails, key="set_redact")
    store = st.toggle("Save analyses to History", value=s.store_history, key="set_store")
    b1, b2 = st.columns(2)
    if b1.button("Apply for this session", key="set_apply", type="primary"):
        st.session_state["overrides"] = {"ai_top_n": int(top_n), "max_log_size_mb": int(max_mb), "ollama_model": model.strip() or s.ollama_model,
                                         "redact_emails": bool(redact_emails), "store_history": bool(store)}
        st.success("Applied.")
    if b2.button("Reset overrides", key="set_reset"):
        st.session_state["overrides"] = {}
        st.success("Back to the configured defaults.")

    st.subheader("Check the local LLM")
    st.caption("Optional. Without it the tool runs in deterministic mode.")
    if s.ai_allowed and st.button("Test Ollama connection", key="set_test"):
        try:
            provider = get_provider(dataclasses.replace(s, ai_provider="ollama"))
            if provider.is_available():
                st.success(f"Ollama is reachable and model '{provider.model}' is installed.")
            else:
                st.warning(provider.unavailable_reason())
        except AIProviderError as exc:
            st.error(str(exc))
    st.info("Privacy: logs and code stay on this computer unless you enable an online provider. Even then only redacted evidence is sent.")
