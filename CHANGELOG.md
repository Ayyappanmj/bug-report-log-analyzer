# Changelog

## 1.0.0-rc1
Release candidate. Promote to 1.0.0 after you complete the verification steps in [docs/release_checklist.md](docs/release_checklist.md) on your own machine (real `pytest`, real Streamlit run, real Ollama/Jira if you use them).

### Added since 0.1
- 0.1 scaffold: project structure, config, provider abstraction.
- 0.2 synthetic demo project and a generated log whose stack traces point at real lines.
- 0.3 log ingestion and parsers (bracketed, generic, JSON lines), safe reading, encodings.
- 0.4 exception extraction, message normalization, error grouping and ranking.
- 0.5 code scanner, chunker, BM25 search, retrieval with verification statuses.
- 0.6 rule-based root-cause analysis with evidence and hypothesis kept apart; agent controller.
- 0.7 optional LLM (Ollama, OpenAI-compatible) with redaction, validation, retry and fallback.
- 0.8 Jira-ready reports (Markdown, text, JSON, wiki), human review, optional Jira REST creation.
- 0.9 Streamlit UI (8 pages), redacted SQLite history.
- 0.10 hardened tests: fuzzing, large files, error containment, mutation check, CI workflow.
- 0.11 benchmark tooling, scenarios with ground truth, manual-vs-assisted timing tool.
- 0.12 security pass: markup escaping, no-redirect HTTP, path policy, streaming pipeline, group cap, public-demo mode, `SECURITY.md`.
- 0.13 README, architecture diagrams, screenshot guide, portfolio card and case study, documentation-honesty tests.
- 0.14 demo recording plan, rehearsal timer, readiness check and GIF validator.
- 1.0.0-rc1 release tooling: verification script, clean release-zip builder, commit helper, contributor files.

### Fixed during development (found by the project's own tests and review)
- Quadratic redaction regexes (one line took ~19 s) now bounded.
- Deeply nested JSON no longer crashes parsing.
- One failing incident no longer aborts a whole analysis.
- Credentials are no longer forwarded on HTTP redirects.
- Hostile log text can no longer render as live Markdown links, images or HTML.

### Not included
Screenshots, a demo recording, benchmark results and a public deployment. Produce them yourself with the documented tools.
