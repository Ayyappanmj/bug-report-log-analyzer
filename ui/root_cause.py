"""Root Cause Analysis page: observed evidence and hypothesis kept visibly separate."""
from __future__ import annotations

import streamlit as st

from . import components as C
from . import state as S
from . import viewmodels as vm


def render() -> None:
    st.title("Root Cause Analysis")
    run = S.current()
    if run is None:
        C.no_run_notice()
        return
    C.source_banner()
    gid = C.group_picker(run, "rca_pick")
    if gid is None:
        return
    report = vm.report_for(run, gid)
    if report is None:
        st.info("This incident has not been analyzed yet.")
        if S.is_live():
            if st.button("Analyze this incident", key="rca_analyze", type="primary"):
                with st.spinner("Analyzing…"):
                    problem = S.analyze_more(gid)
                if problem:
                    st.error(problem)
                else:
                    st.rerun()
        return

    st.subheader(vm.md_safe(report["incident"]))
    c1, c2, c3 = st.columns(3)
    c1.metric("Severity", vm.severity_label(report["severity"]))
    c2.metric("Confidence (heuristic)", f"{report['confidence']:.2f}", help=vm.confidence_text(report))
    c3.metric("Source location", "✅ verified" if report["code_location_verified"] else "⚠️ not verified")
    st.caption(f"Category: {report['category']} · {report['frequency']:,} occurrence(s) · {report['first_occurrence'] or '?'} → {report['last_occurrence'] or '?'}")

    t_ev, t_hyp, t_impact, t_fix = st.tabs(["1 · Observed evidence", "2 · Hypothesis", "3 · Impact & alternatives", "4 · Fix & testing"])
    with t_ev:
        st.success("MEASURED from the log and code. Every item names its source.")
        for line in vm.evidence_lines(report):
            st.markdown("- " + line)
        if report["stack_trace"]:
            with st.expander("Stack trace of a sample event"):
                st.code(report["stack_trace"])
    with t_hyp:
        st.warning("HYPOTHESIS: not confirmed fact. Verify it before acting.")
        st.markdown(f"**Probable root cause:** {vm.md_safe(report['probable_root_cause'])}")
        if report["ai_enhanced"]:
            st.caption(f"Written by {vm.md_safe(report['ai_provider'])} from the evidence (format-checked, not truth-checked). "
                       f"The model's own confidence estimate: {report['ai_confidence']}.")
            for item in report["ai_supporting_evidence"]:
                st.markdown(f"- cites **{item['id']}**: {vm.md_safe(item['text'][:200])}")
            for caveat in report["ai_caveats"]:
                st.caption(f"Model caveat: {vm.md_safe(caveat)}")
            for warn in report["ai_warnings"]:
                st.warning(vm.md_safe(warn))
            with st.expander("Rule-based baseline hypothesis"):
                st.write(vm.md_safe(report["baseline_probable_root_cause"]))
        elif report.get("ai_fallback_reason"):
            st.caption(f"AI refinement not used: {report['ai_fallback_reason']}")
        else:
            st.caption("Rule-based hypothesis (no language model involved).")
        with st.expander("How the confidence score was built"):
            st.write(vm.confidence_text(report))
            for line in report["confidence_basis"]:
                st.markdown(f"- {vm.md_safe(line)}")
    with t_impact:
        st.markdown("**Observed impact**")
        for line in report["observed_impact"]:
            st.markdown(f"- {vm.md_safe(line)}")
        st.markdown(f"**Inferred impact (hypothesis):** {vm.md_safe(report['inferred_impact'])}")
        st.markdown("**Alternative possibilities**")
        for line in report["alternative_possibilities"]:
            st.markdown(f"- {vm.md_safe(line)}")
        if report["related_group_ids"]:
            st.caption("Linked incidents (shared request IDs): " + ", ".join(report["related_group_ids"]))
    with t_fix:
        for title, key in (("Recommended investigation", "recommended_investigation"), ("Suggested fix (hypotheses to evaluate)", "recommended_fix"),
                           ("Suggested reproduction steps (derived from the log; not verified)", "reproduction_steps")):
            st.markdown(f"**{title}**")
            for line in report[key]:
                st.markdown(f"- {vm.md_safe(line)}")
    st.caption(report["disclaimer"])
    c1, c2 = st.columns(2)
    c1.button("View code →", key="rca_to_code", on_click=S.goto, args=("Code Explorer",))
    c2.button("Create bug report →", key="rca_to_report", type="primary", on_click=S.goto, args=("Bug Report",))
