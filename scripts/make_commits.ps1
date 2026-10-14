# Creates a readable commit history from the working tree, grouped by area (messages follow the conventional style).
# Run from the project root after `git init`. It only stages files that exist; the final commit adds everything else.
$ErrorActionPreference = "Stop"
if (-not (Test-Path .git)) { Write-Error "Run 'git init' first."; exit 1 }

function Commit-Group([string]$message, [string[]]$paths) {
    $existing = $paths | Where-Object { Test-Path $_ }
    if ($existing) { git add -- $existing }
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) { git commit -m $message | Out-Null; Write-Host "committed: $message" }
}

Commit-Group "chore: project scaffold and configuration" @("config.py", "requirements.txt", "requirements-dev.txt", ".gitignore", ".env.example", "LICENSE", "Dockerfile", ".dockerignore", "pytest.ini", ".coveragerc", "pyproject.toml", "scripts/__init__.py", "tests/__init__.py", "tests/helpers.py")
Commit-Group "feat: add log ingestion pipeline" @("log_analyzer/__init__.py", "log_analyzer/models.py", "log_analyzer/ingest.py", "log_analyzer/parser.py", "log_analyzer/normalizer.py", "docs/log_formats.md", "demo", "scripts/generate_demo_log.py")
Commit-Group "feat: implement error extraction" @("log_analyzer/extractor.py")
Commit-Group "feat: add error grouping" @("log_analyzer/grouper.py", "docs/grouping.md")
Commit-Group "feat: implement source code retrieval" @("code_analyzer", "security", "docs/code_retrieval.md")
Commit-Group "feat: add root cause analysis" @("agent", "docs/root_cause.md")
Commit-Group "feat: add optional local LLM integration" @("ai", "docs/llm.md")
Commit-Group "feat: generate Jira bug reports" @("reports", "docs/jira_report.md")
Commit-Group "feat: add Streamlit dashboard" @("app.py", "ui", "storage", ".streamlit", "docs/ui.md")
Commit-Group "test: add log analyzer tests" @("tests", "scripts/run_basic_checks.py", "scripts/run_tests.ps1", "scripts/mutation_smoke.py", "docs/testing.md", ".github/workflows")
Commit-Group "feat: add benchmark tooling" @("benchmarks", "scripts/benchmark.py", "scripts/manual_baseline.py", "scripts/compare_workflows.py", "docs/benchmarking.md")
Commit-Group "fix: harden inputs, output rendering and credentials handling" @("SECURITY.md", ".gitleaks.toml", ".pre-commit-config.yaml")
Commit-Group "docs: add architecture documentation" @("README.md", "docs/architecture.md", "docs/portfolio.md", "docs/case_study.md")
Commit-Group "docs: add demo instructions" @("docs/demo.md", "docs/screenshots.md", "docs/screenshots", "scripts/demo_plan.py", "scripts/demo_check.py", "scripts/demo_rehearsal.py", "scripts/gif_markdown.py", "scripts/screenshot_markdown.py")
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { git commit -m "chore: release tooling, changelog and contributor files" | Out-Null; Write-Host "committed: release tooling" }
git log --oneline
