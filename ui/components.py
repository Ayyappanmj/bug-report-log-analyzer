"""Small shared widgets."""
from __future__ import annotations

import streamlit as st

from . import state as S
from . import viewmodels as vm


def no_run_notice() -> None:
    st.info("No analysis yet. Load the demo or provide a log on the Log Analyzer page.")
    st.button("Go to Log Analyzer", key="nr_goto", on_click=S.goto, args=("Log Analyzer",))


def source_banner() -> None:
    if st.session_state["source"] == "history":
        st.info(f"Viewing a saved run (history #{st.session_state['history_id']}). Saved data is redacted and read-only: "
                "re-run the analysis to explore code or analyze more incidents.")


def metric_cards(cards: list[dict]) -> None:
    for start in range(0, len(cards), 3):
        cols = st.columns(3)
        for col, card in zip(cols, cards[start:start + 3]):
            with col:
                st.metric(card["label"], card["value"], help=card.get("help"))


def group_picker(run: dict, key: str) -> str | None:
    groups = run["grouping"]["groups"]
    if not groups:
        st.success("No error or warning groups were found in this log.")
        return None
    ids = [g["id"] for g in groups]
    labels = {g["id"]: f"{g['id']} · {vm.SEVERITY_ICON.get(g['severity'], '')} {g['title'][:70]} (x{g['count']})" for g in groups}
    selected = st.session_state.get("selected_group")
    index = ids.index(selected) if selected in ids else 0
    choice = st.selectbox("Incident", ids, index=index, format_func=lambda i: labels[i], key=key)
    st.session_state["selected_group"] = choice
    return choice


def show_code(text: str, language: str | None = None) -> None:
    st.code(text if text else "(empty)", language=language)


def privacy_notice() -> None:
    st.warning("Do not upload confidential production logs unless your organization permits it. Everything runs on this computer "
               "unless you enable an optional online AI provider.")
