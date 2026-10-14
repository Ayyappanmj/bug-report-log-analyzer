"""Code Explorer page: retrieved snippets, keyword search and file browsing."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import components as C
from . import state as S
from . import viewmodels as vm

MAX_LINES_SHOWN = 400


def _incident_code(run: dict) -> None:
    gid = C.group_picker(run, "ce_pick")
    if gid is None:
        return
    report = vm.report_for(run, gid)
    if report is None:
        st.info("Analyze this incident first (Error Groups or Root Cause Analysis).")
        return
    contexts = report["code_context"]
    if not contexts:
        st.info("No source code was located for this incident. " + " ".join(report["notes"]))
        return
    st.caption(f"Retrieval strategy: **{report['code_strategy']}** · snippets are real file lines, never generated.")
    numbered = st.toggle("Show line numbers (▶ marks the traced line)", value=False, key="ce_numbers")
    for i, ctx in enumerate(contexts):
        title = vm.md_safe(f"{ctx['file_path']}:{ctx['target_line']} {ctx['qualname'] or ''}") + f" · {vm.status_label(ctx['status'])}"
        with st.expander(title, expanded=(i == 0)):
            (st.success if ctx["verified"] else st.warning)(vm.md_safe(ctx["note"]))
            st.caption(f"Lines {ctx['start_line']}–{ctx['end_line']} · module {vm.md_safe(ctx['module'])}"
                       + (f" · class {vm.md_safe(ctx['class_name'])}" if ctx["class_name"] else ""))
            if numbered:
                st.code(vm.numbered_snippet(ctx))
            else:
                st.code(ctx["snippet"], language=vm.language_for_streamlit(ctx["language"]))
            if ctx["imports"]:
                st.markdown("**Imports in this file:**")
                st.code("\n".join(ctx["imports"]), language=vm.language_for_streamlit(ctx["language"]))
            if ctx["related_functions"]:
                st.markdown("**Related functions called here:** " + ", ".join(
                    f"{vm.md_safe(r['name'])} ({vm.md_safe(r['file'])}:{r['start_line']})" for r in ctx["related_functions"]))
            if ctx["alternatives"]:
                st.caption("Other candidates: " + vm.md_safe("; ".join(ctx["alternatives"])))


def _search(index) -> None:
    c1, c2 = st.columns([3, 1])
    query = c1.text_input("Search the code (symbols and keywords)", key="ce_query", placeholder="database connection timeout")
    lang = c2.selectbox("Language", ["any", "python", "javascript", "typescript", "java"], key="ce_lang")
    if not query.strip():
        return
    hits = index.search(query, k=10, language=None if lang == "any" else lang)
    if not hits:
        st.info("No matching code.")
        return
    st.dataframe(pd.DataFrame([{"File": c.file, "Symbol": c.qualname, "Kind": c.kind, "Lines": f"{c.start_line}-{c.end_line}",
                                "Score": round(s, 2)} for c, s in hits]), hide_index=True)
    labels = [f"{c.file}:{c.start_line} {c.qualname}" for c, _ in hits]
    pick = st.selectbox("Show", range(len(hits)), format_func=lambda i: labels[i], key="ce_hit")
    chunk = hits[pick][0]
    st.code("\n".join(index.chunk_text(chunk)), language=vm.language_for_streamlit(chunk.language))


def _browse(index, run: dict) -> None:
    stats = run["scan_stats"]
    st.write(f"{stats['files_scanned']} file(s), {stats['total_lines']:,} lines · languages: {stats['by_language']} · skipped: {stats['skipped']}")
    files = sorted(index.files)
    if not files:
        st.info("No source files were scanned.")
        return
    path = st.selectbox("File", files, key="ce_file")
    sf = index.files[path]
    st.caption(f"{len(sf.lines)} lines" + (f" (showing the first {MAX_LINES_SHOWN})" if len(sf.lines) > MAX_LINES_SHOWN else ""))
    st.code("\n".join(sf.lines[:MAX_LINES_SHOWN]), language=vm.language_for_streamlit(sf.language))


def render() -> None:
    st.title("Code Explorer")
    run = S.current()
    if run is None:
        C.no_run_notice()
        return
    C.source_banner()
    t_inc, t_search, t_files = st.tabs(["Incident code", "Search code", "Browse files"])
    with t_inc:
        _incident_code(run)
    live = S.live_run()
    index = live.retriever.index if live is not None and live.retriever is not None else None
    with t_search:
        _search(index) if index else st.info("Code search needs a live analysis with a project folder. Re-run the analysis.")
    with t_files:
        _browse(index, run) if index else st.info("File browsing needs a live analysis with a project folder.")
