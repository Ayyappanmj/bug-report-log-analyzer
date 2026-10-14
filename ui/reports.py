"""Bug Report page: human review, preview, copy, download and optional Jira creation."""
from __future__ import annotations

import json

import streamlit as st

from reports.exporters import export_bytes, render_markdown, render_wiki
from reports.jira import PRIORITIES, JiraConfig, JiraError, apply_review, create_issue

from . import components as C
from . import state as S


def _lines(text: str) -> list[str]:
    return [x.strip() for x in text.splitlines() if x.strip()]


def render() -> None:
    st.title("Bug Report")
    run = S.current()
    if run is None:
        C.no_run_notice()
        return
    C.source_banner()
    analyzed = [g for g in run["grouping"]["groups"] if g["id"] in run["reports"]]
    if not analyzed:
        st.info("Analyze an incident first.")
        return
    sub = {"grouping": {"groups": analyzed}}
    gid = C.group_picker(sub, "br_pick")
    base = S.ticket_for(gid) if gid else None
    if base is None:
        st.info("No report is available for this incident.")
        return

    st.subheader("Human review")
    st.caption("The draft is generated, not authoritative. Edit anything, then mark it reviewed. Edited text is redacted for secrets too.")
    title = st.text_input("Title", value=base.title, key=f"br_title_{gid}")
    summary = st.text_area("Summary", value=base.summary, key=f"br_summary_{gid}", height=100)
    c1, c2 = st.columns(2)
    priority = c1.selectbox("Priority", list(PRIORITIES), index=list(PRIORITIES).index(base.priority) if base.priority in PRIORITIES else 2,
                            key=f"br_priority_{gid}", help=base.priority_rationale)
    reviewer = c2.text_input("Reviewer name", key=f"br_reviewer_{gid}")
    expected = st.text_area("Expected behavior", value=base.expected_behavior, key=f"br_expected_{gid}", height=70)
    steps = st.text_area("Steps to reproduce (one per line)", value="\n".join(base.steps_to_reproduce), key=f"br_steps_{gid}", height=140)
    fixes = st.text_area("Suggested fix (one per line)", value="\n".join(base.suggested_fix), key=f"br_fix_{gid}", height=120)
    reviewed = st.checkbox("I have reviewed this report", key=f"br_reviewed_{gid}")

    ticket = apply_review(base, title=title, summary=summary, priority=priority, expected_behavior=expected,
                          steps_to_reproduce=_lines(steps), suggested_fix=_lines(fixes), reviewer=reviewer, reviewed=reviewed)
    (st.success if reviewed else st.warning)(ticket.review["status"])
    if ticket.redactions:
        st.caption("Masked in this report: " + ", ".join(f"{k} ×{v}" for k, v in sorted(ticket.redactions.items())))

    t_prev, t_copy, t_md, t_json = st.tabs(["Preview", "Copy for Jira", "Markdown", "JSON"])
    with t_prev:
        st.markdown(render_markdown(ticket))
    with t_copy:
        st.caption("Jira wiki markup. Use the copy icon at the top right of the box, then paste into Jira's editor in Text mode.")
        st.code(render_wiki(ticket), language=None)
    with t_md:
        st.code(render_markdown(ticket), language="markdown")
    with t_json:
        st.code(json.dumps(ticket.to_dict(), indent=2, ensure_ascii=False), language="json")

    st.subheader("Download")
    cols = st.columns(4)
    for col, (fmt, label) in zip(cols, (("markdown", "Markdown"), ("text", "TXT"), ("json", "JSON"), ("jira", "Jira wiki"))):
        name, mime, data = export_bytes(ticket, fmt)
        with col:
            st.download_button(f"⬇ {label}", data, file_name=name, mime=mime, key=f"dl_{fmt}_{gid}")

    with st.expander("Create the issue in Jira (optional)"):
        s = S.settings()
        cfg = JiraConfig.from_settings(s)
        if not s.jira_enabled:
            st.caption("Creating Jira issues is disabled in public-demo mode. Download the report instead.")
        elif not (s.jira_base_url and s.jira_project_key and s.jira_api_token):
            st.caption("Jira is not configured. Set JIRA_* values in .env to enable this. Exporting never needs Jira.")
        else:
            st.write(f"Target: project **{cfg.project_key}** at {cfg.base_url} as **{cfg.issue_type}**")
            confirm = st.checkbox("Yes, create a real Jira issue from this report", key=f"br_confirm_{gid}")
            if st.button("Create issue", key=f"br_create_{gid}", disabled=not (confirm and reviewed)):
                try:
                    result = create_issue(ticket, cfg, confirm=True)
                    st.success(f"Created {result['key']}")
                    st.markdown(f"[{result['url']}]({result['url']})")
                except JiraError as exc:
                    st.error(str(exc))
            if not reviewed:
                st.caption("Tick “I have reviewed this report” first.")
