# Release checklist

The code and tests were developed in an environment without `pytest`, Streamlit, Pydantic, Ollama, Jira or Windows. This list is what **you** must do to turn
the release candidate into a release you can stand behind.

## 1. Replace placeholders
```powershell
python scripts\verify_release.py          # lists every [todo]
```
- `LICENSE`: your name.
- `SECURITY.md`: your real contact in "Reporting a problem".
- `docs\portfolio.md`: your repository URL.

## 2. Verify on your machine
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python scripts\verify_release.py --tests  # structure, secrets scan, imports, and the test suite
pytest --cov=. --cov-report=term-missing  # note the real coverage number if you want to quote it
streamlit run app.py                      # click through the demo; the AppTest cases in pytest also run the real app
```
If anything fails, fix it or send the output back before publishing.

## 3. Produce the evidence the README does not contain
- Benchmarks: `python scripts\benchmark.py`, then paste the tables from `benchmarks\results\latest.md` and the machine line into your README.
- Screenshots: [screenshots.md](screenshots.md), then `python scripts\screenshot_markdown.py`.
- Demo GIF: [demo.md](demo.md), then `python scripts\gif_markdown.py`.
- Optional: real Ollama (`python scripts\analyze_cli.py --ai ollama`, then `--ai ollama` in the benchmark) and real Jira dry run in a test project.
- Check that the Mermaid diagrams render on GitHub.

## 4. Publish
```powershell
git init
.\scripts\make_commits.ps1                # creates the suggested commit history from the working tree
git branch -M main
git remote add origin <your repository URL>
git push -u origin main
```
Enable GitHub Actions (the workflow runs tests on Windows and Linux plus bandit, pip-audit and gitleaks). Tag the release after everything passes:
`git tag v1.0.0; git push --tags`, then update `TOOL_VERSION` in `config.py` and the top of `CHANGELOG.md` from `1.0.0-rc1` to `1.0.0`.

## 5. Rebuild the zip (optional)
```powershell
python scripts\build_release_zip.py --out dist
python scripts\verify_release.py --zip dist\bug-report-log-analyzer-1.0.0-rc1.zip
```

## Do not publish
Your `.env`, `storage\history.db`, benchmark runs that contain machine details you do not want public, and any real log or source code.
