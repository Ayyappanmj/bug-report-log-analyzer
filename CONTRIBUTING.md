# Contributing

## Set up (Windows PowerShell)
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
```
Run `pytest -m "not slow"` while iterating and the full `pytest` before opening a pull request.

## Ground rules
- **Never present a guess as an observation.** Anything under "observed evidence" must be measured from the log or code and carry a source. Hypotheses go in the inference fields. A test enforces this.
- **Never invent code, metrics or URLs.** Retrieval returns real file lines, marked verified or not. Benchmarks and resume numbers come from measured output only.
- **Treat logs, code and model output as untrusted.** Nothing is executed. Escape text before rendering, redact secrets before it leaves the machine, and keep regexes bounded (see `tests/test_robustness.py`).
- **Every change gets a test**, ideally one that fails without the change. Bug fixes need a regression test.
- Keep display logic in `ui/viewmodels.py` (plain functions) and pages thin.

## Common changes
- **A new failure pattern**: add a `Rule` in `agent/rules.py` (hypothesis, alternatives, investigation, fixes, reproduction), a testing hint in `reports/jira.py`, and cases in `tests/test_rca.py`.
- **A new log format**: add a `LineParser` in `log_analyzer/parser.py`, register it in `DEFAULT_PARSERS`, describe it in `docs/log_formats.md`, and test it in `tests/test_parser.py`.
- **A new language for code retrieval**: extend `code_analyzer/chunker.py` and `scanner.LANGUAGES`, then add chunker and retriever tests.

## Commit messages
Conventional style: `feat: ...`, `fix: ...`, `test: ...`, `docs: ...`, `refactor: ...`, `chore: ...`.

## Security
Report vulnerabilities privately (see [SECURITY.md](SECURITY.md)); do not open a public issue with exploit details.
