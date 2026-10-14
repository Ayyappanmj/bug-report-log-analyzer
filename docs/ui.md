# Streamlit UI (Phase 9)

Run: `streamlit run app.py` (opens http://localhost:8501).

| Page | What it does |
|---|---|
| Dashboard | Six metric cards from the actual run (events, unique errors, critical, recurring, files, duration), top incidents, severity chart, stage timings, parsing details |
| Log Analyzer | Upload a log or enter a path, optional project folder, **Load demo**, **Analyze** with a live progress bar, optional local-LLM toggle |
| Error Groups | Filter by severity/count/text, per-minute timeline, sample events, surrounding events, related groups, analyze more incidents on demand |
| Root Cause Analysis | Tabs: **Observed evidence** (measured, sourced) / **Hypothesis** (clearly labeled) / impact and alternatives / fix and testing |
| Code Explorer | Retrieved snippets with VERIFIED / NOT verified status, keyword search, file browser |
| Bug Report | Human review (edit, mark reviewed), preview, copy-ready Jira markup, downloads (MD, TXT, JSON, Jira wiki), optional Jira creation |
| History | Saved runs in a local SQLite file (redacted); reopen or delete |
| Settings | Effective configuration (no secrets), session overrides, Ollama connectivity test |

## Demo (about 30-60 seconds)
Dashboard -> **Load demo and analyze** (or Log Analyzer -> Load demo -> Analyze) -> Error Groups -> pick G001 -> Root Cause Analysis ->
Code Explorer -> Bug Report -> mark reviewed -> download.

## Design notes
- Display logic lives in `ui/viewmodels.py` (pure functions, unit tested). Pages are thin.
- Pages read a plain dict (`AnalysisRun.to_dict()`), so live and saved runs render the same way.
- "Copy Jira Report": the Jira-markup tab uses Streamlit's built-in copy icon on code blocks.
- History stores redacted payloads only; Jira creation requires configuration, a confirm checkbox and "I have reviewed this report".

## How it is tested
- `tests/test_ui_pages.py` runs every page with a recording stand-in for Streamlit (checks our code paths and data shapes).
- `tests/test_ui_apptest.py` runs the real `app.py` with Streamlit's `AppTest` and is skipped when Streamlit is not installed.
- Visual layout was not checked by a human in this environment: review the screenshots you take (Phase 13).
