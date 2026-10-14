"""Dashboard page: metric cards and an at-a-glance incident overview."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import components as C
from . import state as S
from . import viewmodels as vm


def render() -> None:
    st.title("🐞 Bug Report & Log Analyzer Agent")
    st.caption("Parse a messy log, group the errors, find the code involved, and draft a Jira-ready bug report. "
               "Evidence is measured; conclusions are labeled as hypotheses. Runs locally, no paid API needed.")
    run = S.current()
    if run is None:
        st.subheader("Try it in about a minute")
        st.markdown("1. **Load demo**: a synthetic production log and a small demo project.  \n"
                    "2. **Analyze**: parse, group, locate code, build the analysis.  \n"
                    "3. **Pick an incident**, read the evidence and hypothesis, and **download the bug report**.")
        st.button("▶ Load demo and analyze", key="dash_demo", type="primary", on_click=S.request_demo_run)
        st.button("Use my own log", key="dash_own", on_click=S.goto, args=("Log Analyzer",))
        C.privacy_notice()
        return
    C.source_banner()
    st.subheader(f"Results for {vm.md_safe(run['log_name'])}")
    C.metric_cards(vm.dashboard_cards(run))
    warning = vm.unparsed_warning(run)
    if warning:
        st.warning(warning)
    for err in run.get("errors", []):
        st.warning(f"{err['group_id']} could not be analyzed: {err['error']}")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Top incidents**")
        rows = vm.groups_rows(run)[:5]
        if rows:
            st.dataframe(pd.DataFrame(rows)[["ID", "Severity", "Count", "Incident", "Source code"]], hide_index=True)
        else:
            st.success("No errors or warnings found.")
    with right:
        st.markdown("**Groups by severity**")
        counts = vm.severity_counts(run)
        st.bar_chart(pd.DataFrame({"Groups": list(counts.values())}, index=list(counts.keys())))
    st.button("Investigate error groups →", key="dash_to_groups", type="primary", on_click=S.goto, args=("Error Groups",))

    with st.expander("How long each stage took (measured in this run)"):
        st.dataframe(pd.DataFrame(vm.timing_rows(run)), hide_index=True)
    with st.expander("Parsing details"):
        q = vm.parse_quality(run)
        st.write(f"{q['lines']:,} lines → {q['events']:,} events (+{q['continuation']:,} continuation lines such as stack traces); "
                 f"{q['unparsed']} unparsed, {q['truncated']} truncated.")
        st.write({"formats": q["formats"], "levels": q["levels"]})
        if q["samples"]:
            st.code("\n".join(q["samples"]))
    ai = vm.ai_summary(run)
    st.caption(f"AI: {ai['provider']}" + (f" · refined {ai['refined']}/{ai['attempted']} report(s)" if ai["attempted"] else ""))
