"""History page: saved (redacted) runs stored in a local SQLite file."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import state as S


def _open(run_id: int) -> None:
    S.load_history(run_id)


def render() -> None:
    st.title("History")
    s = S.settings()
    if s.public_demo:
        st.info("History is disabled in public-demo mode: saved analyses would be visible to every visitor of a shared server.")
        return
    if not s.store_history:
        st.info("Saving history is switched off (Settings or STORE_HISTORY=false).")
    db = S.db()
    rows = db.list()
    st.caption(f"Stored locally in {db.path}. Saved runs are redacted for secrets and keep only the 50 most recent.")
    if not rows:
        st.info("No saved runs yet. Analyses are saved automatically after each run.")
        return
    st.dataframe(pd.DataFrame(rows).rename(columns={
        "id": "ID", "created_at": "Saved at", "log_name": "Log", "total_events": "Events", "error_groups": "Error groups",
        "critical_errors": "Critical", "recurring_errors": "Recurring", "files_analyzed": "Files", "seconds": "Seconds",
        "ai_provider": "AI"}), hide_index=True)
    ids = [r["id"] for r in rows]
    pick = st.selectbox("Saved run", ids, format_func=lambda i: next(f"#{r['id']} · {r['log_name']} · {r['created_at']}" for r in rows if r["id"] == i),
                        key="hist_pick")
    c1, c2, c3 = st.columns(3)
    c1.button("Open", key="hist_open", type="primary", on_click=_open, args=(pick,))
    if c2.button("Delete", key="hist_delete"):
        db.delete(pick)
        st.rerun()
    confirm = c3.checkbox("Confirm delete all", key="hist_confirm")
    if c3.button("Delete all", key="hist_clear", disabled=not confirm):
        db.clear()
        st.rerun()
