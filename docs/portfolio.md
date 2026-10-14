# Portfolio card

**Title:** Bug Report & Log Analyzer Agent

**Short description:** AI-powered incident investigation system that analyzes application logs, retrieves relevant source code, identifies probable root causes, and generates Jira-ready bug reports.
(Accurate wording note: the analysis is rule-based by default and uses a local LLM only when you enable it. Say "AI-assisted" only for runs where you actually used a model.)

**Tech:** Python · Streamlit · Ollama · Pydantic · SQLite · pytest

**Buttons**
| Button | Value |
|---|---|
| GitHub | `<your repository URL: add it after you publish>` |
| Live Demo | **Run Locally** (see the README). No public deployment exists. |
| Demo Video | not recorded yet (plan: [demo.md](demo.md)) |
| Case Study | [case_study.md](case_study.md) |

**Three-line pitch for a recruiter**
1. Parses messy logs, groups thousands of events into a handful of incidents, and finds the exact code that raised them.
2. Keeps measured evidence separate from hypotheses, and marks every code snippet verified or not.
3. Tested with 350+ tests, fuzzing, a mutation check and a documented threat model.

Do not add numbers to this card unless they come from your own benchmark output (`benchmarks\results\latest.md`).
