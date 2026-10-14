from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ["app.py", "config.py", "requirements.txt", "README.md", "LICENSE", "Dockerfile",
            ".gitignore", ".env.example", "pytest.ini", "docs/architecture.md",
            "agent/__init__.py", "log_analyzer/__init__.py", "code_analyzer/__init__.py",
            "ai/base.py", "ai/schemas.py", "reports/__init__.py", "storage/__init__.py",
            "ui/__init__.py", "demo/logs/production_sample.log", "demo/project/src/payment_service.py",
            "demo/project/src/database.py", "demo/project/src/checkout.py",
            "scripts/generate_demo_log.py", "log_analyzer/models.py", "log_analyzer/parser.py",
            "log_analyzer/normalizer.py", "log_analyzer/ingest.py", "docs/log_formats.md",
            "log_analyzer/extractor.py", "log_analyzer/grouper.py", "docs/grouping.md",
            "code_analyzer/models.py", "code_analyzer/scanner.py", "code_analyzer/chunker.py",
            "code_analyzer/search.py", "code_analyzer/retriever.py", "docs/code_retrieval.md",
            "agent/rules.py", "agent/root_cause_agent.py", "agent/orchestrator.py", "docs/root_cause.md",
            "ai/validation.py", "ai/enhancer.py", "ai/prompts.py", "ai/redaction.py", "ai/api_provider.py",
            "ai/ollama_provider.py", "docs/llm.md",
            "reports/jira.py", "reports/exporters.py", "docs/jira_report.md",
            "storage/database.py", "ui/state.py", "ui/components.py", "ui/viewmodels.py", "ui/dashboard.py", "ui/analyzer.py",
            "ui/error_groups.py", "ui/root_cause.py", "ui/code_viewer.py", "ui/reports.py", "ui/history.py",
            "ui/settings_page.py", "docs/ui.md", "docs/testing.md", "requirements-dev.txt", ".coveragerc", ".github/workflows/tests.yml",
            "scripts/mutation_smoke.py", "scripts/run_tests.ps1",
            "benchmarks/loggen.py", "benchmarks/scenarios.py", "benchmarks/machine.py", "benchmarks/report.py", "scripts/benchmark.py",
            "scripts/manual_baseline.py", "scripts/compare_workflows.py", "docs/benchmarking.md",
            "SECURITY.md", "security/policy.py", "reports/sanitize.py", ".streamlit/config.toml", ".dockerignore", ".gitleaks.toml",
            ".pre-commit-config.yaml", "pyproject.toml", "tests/test_security.py", "docs/screenshots.md", "docs/portfolio.md", "docs/case_study.md", "docs/demo.md",
            "scripts/screenshot_markdown.py", "tests/test_readme.py", "scripts/demo_plan.py", "scripts/demo_check.py", "scripts/demo_rehearsal.py",
            "scripts/gif_markdown.py", "tests/test_demo_tools.py", "CHANGELOG.md", "CONTRIBUTING.md", "docs/release_checklist.md", "docs/acceptance.md",
            "scripts/verify_release.py", "scripts/build_release_zip.py", "scripts/make_commits.ps1", "tests/test_release.py",
            ".github/pull_request_template.md"]


def test_required_paths_exist():
    missing = [p for p in REQUIRED if not (ROOT / p).exists()]
    assert not missing, missing


def test_no_secrets_committed():
    assert not (ROOT / ".env").exists()
