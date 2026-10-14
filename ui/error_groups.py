"""Error Groups page: filter, inspect timeline, samples and context."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import components as C
from . import state as S
from . import viewmodels as vm


def _analyze_button(gid: str) -> None:
    if S.is_live():
        if st.button("Analyze this incident", key="eg_analyze", type="primary"):
            with st.spinner("Analyzing…"):
                problem = S.analyze_more(gid)
            if problem:
                st.error(problem)
            else:
                st.rerun()
    else:
        st.caption("Saved runs are read-only: re-run the analysis to analyze more incidents.")


def render() -> None:
    st.title("Error Groups")
    run = S.current()
    if run is None:
        C.no_run_notice()
        return
    C.source_banner()
    groups = run["grouping"]["groups"]
    if not groups:
        st.success("No errors or warnings were found in this log.")
        return
    f1, f2, f3 = st.columns([2, 1, 2])
    with f1:
        severities = st.multiselect("Severity", list(vm.SEVERITY_ORDER), default=list(vm.SEVERITY_ORDER), key="eg_sev")
    with f2:
        top = max(g["count"] for g in groups)
        min_count = st.slider("Min. occurrences", 1, max(top, 2), 1, key="eg_min")
    with f3:
        query = st.text_input("Search", key="eg_query", placeholder="exception, service or message")
    rows = vm.groups_rows(run, severities, min_count, query)
    if not rows:
        st.warning("No groups match these filters.")
        return
    st.caption(f"{len(rows)} of {len(groups)} group(s). Similar events were merged: normalized message, exception type and raise site.")
    st.dataframe(pd.DataFrame(rows), hide_index=True)

    gid = C.group_picker(run, "eg_pick")
    g = vm.group_by_id(run, gid)
    if g is None:
        return
    st.subheader(f"{g['id']} · {vm.md_safe(g['title'])}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Severity", vm.severity_label(g["severity"]))
    c2.metric("Occurrences", f"{g['count']:,}")
    c3.metric("First seen", g["first_seen"] or "-")
    c4.metric("Last seen", g["last_seen"] or "-")
    if g["exception_type"]:
        st.write(f"**Exception:** `{g['exception_type']}`" + (f" (surfaced as `{g['surfaced_type']}`)" if g["surfaced_type"] and g["surfaced_type"] != g["exception_type"] else "")
                 + (f" · raised in `{g['raise_site']}`" if g["raise_site"] else ""))
    st.write("**Services:** " + vm.md_safe(", ".join(f"{k} ({v})" for k, v in g["services"].items()) or "-")
             + ("  \n**HTTP statuses:** " + ", ".join(f"{k} ×{v}" for k, v in g["http_statuses"].items()) if g["http_statuses"] else ""))

    t_time, t_samples, t_context, t_related = st.tabs(["Timeline", "Sample events", "Surrounding events", "Related groups"])
    with t_time:
        points = vm.timeline_rows(g)
        if points:
            st.bar_chart(pd.DataFrame(points, columns=["Minute", "Events"]).set_index("Minute"))
            st.caption("Events per minute, measured from the log timestamps.")
        else:
            st.info("This group has no usable timestamps.")
    with t_samples:
        for i, sample in enumerate(g["samples"], 1):
            with st.expander(f"Sample {i} · log line {sample['line_no']} · {sample['level']} · {vm.md_safe(sample['service'] or '-')}", expanded=(i == 1)):
                st.text(sample["message"])
                if sample["stack_trace"]:
                    st.code(sample["stack_trace"])
                st.caption(f"request id: {sample['request_id'] or '-'} · thread: {sample['thread'] or '-'}")
    with t_context:
        st.markdown("**Before the first occurrence**")
        st.code("\n".join(g["context_before"]) or "(none)")
        st.markdown("**After the first occurrence**")
        st.code("\n".join(g["context_after"]) or "(none)")
    with t_related:
        if g["related"]:
            for rid in g["related"]:
                other = vm.group_by_id(run, rid)
                st.write(f"**{rid}** · {vm.md_safe(other['title'][:90])} (×{other['count']})")
            st.caption("Linked because they share request IDs. That shows the problems occurred together, not that one caused the other.")
        else:
            st.info("No groups share request IDs with this one.")

    if vm.report_for(run, gid) is None:
        _analyze_button(gid)
    else:
        st.button("Open root-cause analysis →", key="eg_to_rca", type="primary", on_click=S.goto, args=("Root Cause Analysis",))
