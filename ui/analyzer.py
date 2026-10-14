"""Log Analyzer page: choose inputs, preview, run the pipeline with visible progress."""
from __future__ import annotations

import io

import streamlit as st

from ai.base import AIProviderError
from code_analyzer.scanner import ScanError
from log_analyzer.ingest import IngestError

from . import components as C
from . import state as S
from . import viewmodels as vm


def _run_analysis(kind, label, upload, path_text, repo_path, use_ai, s) -> None:
    pipeline, notice = S.make_pipeline(s, use_ai)
    if notice:
        st.warning(notice)
    bar = st.progress(0.0, text="Starting")

    def tick(stage: str, fraction: float) -> None:
        bar.progress(min(max(fraction, 0.0), 1.0), text=stage)

    try:
        if kind == "upload":
            run = pipeline.run(io.BytesIO(upload.getvalue()), repo_path, log_name=label, progress=tick)
        else:
            run = pipeline.run(label, repo_path, progress=tick)
    except (IngestError, ScanError, AIProviderError, OSError, ValueError) as exc:
        bar.empty()
        st.error(f"Analysis failed: {exc}")
        return
    S.set_live(run, pipeline)
    saved = S.save_history()
    st.success(f"Done in {run.dashboard['analysis_seconds']:.2f} s: {run.dashboard['total_events']:,} events, "
               f"{run.dashboard['unique_errors']} error group(s)." + (" Saved to History." if saved else ""))
    if st.session_state.get("history_error"):
        st.warning(f"The analysis worked but could not be saved to History: {st.session_state['history_error']}")
    for err in run.errors:
        st.warning(f"{err['group_id']} could not be analyzed: {err['error']}")
    warning = vm.unparsed_warning(S.current())
    if warning:
        st.warning(warning)
    c1, c2 = st.columns(2)
    c1.button("View dashboard", key="an_to_dash", on_click=S.goto, args=("Dashboard",))
    c2.button("Investigate error groups →", key="an_to_groups", type="primary", on_click=S.goto, args=("Error Groups",))


def render() -> None:
    st.title("Log Analyzer")
    C.privacy_notice()
    s = S.settings()
    left, right = st.columns(2)
    with left:
        st.subheader("1 · Log file")
        upload = st.file_uploader("Upload a log (.log, .txt, .json, .jsonl)", type=["log", "txt", "json", "jsonl"], key="log_upload")
        if s.local_paths_allowed:
            path_text = st.text_input("…or a path on this computer", key="log_path_text", placeholder=r"C:\logs\app.log")
        else:
            path_text = st.session_state.get("log_path_text", "")
            st.caption("Local file paths are disabled in this deployment: upload a file or use the demo.")
        st.button("Load demo", key="load_demo", on_click=S.load_demo)
    with right:
        st.subheader("2 · Source code (optional)")
        if s.local_paths_allowed:
            repo_text = st.text_input("Project folder", key="repo_path_text", placeholder=r"C:\projects\my-app")
        else:
            repo_text = st.session_state.get("repo_path_text", "")
        st.caption("Without a folder you still get grouping and evidence, but no code snippets. Code is only read, never executed.")
        use_ai = False
        if s.ai_allowed:
            use_ai = st.toggle("Refine the hypothesis with an LLM", value=False, key="use_ai",
                               help="Optional. Evidence stays measured; the model only rewrites the hypothesis. Provider is set in .env.")
        notice = vm.ai_privacy_notice(s.ai_provider if s.ai_provider != "none" else "ollama", use_ai)
        if notice:
            st.info(notice)

    source = None
    try:
        kind, label = vm.check_log_source(upload.name if upload else None, upload.size if upload else None, path_text, s.max_log_size_mb,
                                      s.path_policy())
        source = upload.getvalue() if kind == "upload" else str(label)
    except vm.InputError as exc:
        kind = label = None
        st.caption(f"ℹ️ {exc}")
    if source is not None:
        with st.expander(f"Preview of {label}", expanded=False):
            try:
                st.code("\n".join(vm.preview_lines(source, 30)))
            except (IngestError, OSError) as exc:
                st.error(f"Cannot preview: {exc}")

    auto = st.session_state.get("auto_analyze", False)
    clicked = st.button("Analyze", key="analyze", type="primary")
    if clicked or auto:
        st.session_state["auto_analyze"] = False
        if source is None:
            st.error("Choose a log first (upload, path, or Load demo).")
            return
        try:
            repo_path = vm.resolve_repo_path(repo_text, s.path_policy())
        except vm.InputError as exc:
            st.error(str(exc))
            return
        _run_analysis(kind, label, upload, path_text, repo_path, use_ai, s)
