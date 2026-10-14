import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from scripts import build_release_zip as BZ
from scripts import verify_release as VR

ROOT = Path(__file__).resolve().parent.parent


def statuses(checks):
    return {c.name: c.status for c in checks}


# ------------------------------------------------------------------ verification script
def test_the_real_tree_passes_the_automatic_checks_and_lists_the_open_placeholders():
    checks = VR.run_checks(ROOT)
    st = statuses(checks)
    assert st["required files present"] == "ok" and st["every module imports"] == "ok", [c for c in checks if c.status == "FAIL"]
    assert st["secrets scan (project's own redaction engine)"] == "ok" and st["no secrets, databases, caches or generated results"] == "ok"
    assert st["version consistent (config, changelog, README)"] == "ok"
    assert sorted(c.name for c in checks if c.status == "todo") == ["placeholder in LICENSE", "placeholder in SECURITY.md", "placeholder in docs/portfolio.md"]
    assert not [c for c in checks if c.status == "FAIL"]


def test_forbidden_files_are_detected_in_a_dirty_tree(tmp_path):
    for rel in (".env", "storage/history.db", "x/__pycache__/a.pyc", "dist/old.zip", "benchmarks/results/benchmark-1.json", ".venv/lib/x.py", "ok.py",
                "benchmarks/results/.gitkeep", ".env.example"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    found = VR.forbidden_files(tmp_path)
    assert ".env" in found and "storage/history.db" in found and "dist/old.zip" in found and "benchmarks/results/benchmark-1.json" in found
    assert "ok.py" not in found and ".env.example" not in found and "benchmarks/results/.gitkeep" not in found
    assert not any("__pycache__" in f for f in found) and any("__pycache__" in f for f in VR.forbidden_files(tmp_path, include_cache=True))
    assert VR.check_forbidden(tmp_path)[0].status == "FAIL"


def test_secrets_and_missing_files_make_the_checks_fail(tmp_path):
    shutil.copytree(ROOT / "ai", tmp_path / "ai")
    (tmp_path / "ai" / "leak.py").write_text('KEY = "' + "AK" + "IA" + 'ABCDEFGHIJKLMNOP"\n')
    assert VR.check_secrets(tmp_path)[0].status == "FAIL"
    assert VR.check_required(tmp_path)[0].status == "FAIL" and "README.md" in VR.check_required(tmp_path)[0].detail


def test_version_mismatch_is_reported(tmp_path):
    for f in ("config.py", "CHANGELOG.md", "README.md"):
        shutil.copy(ROOT / f, tmp_path / f)
    assert VR.check_versions(tmp_path)[0].status == "ok"
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 0.0.1\n", encoding="utf-8")
    assert VR.check_versions(tmp_path)[0].status == "FAIL"


def test_import_probe_reports_broken_modules(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "good.py").write_text("X = 1\n")
    (tmp_path / "pkg" / "bad.py").write_text("raise RuntimeError('boom')\n")
    (tmp_path / "pkg" / "opt.py").write_text("import streamlit\n")
    c = VR.check_imports(tmp_path)[0]
    assert c.status == "FAIL" and "pkg.bad" in c.detail and "pkg.opt" not in c.detail


def test_strict_mode_fails_while_placeholders_remain():
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert VR.main([]) == 0
        assert VR.main(["--strict"]) == 1
    assert "not publishable yet (placeholders)" in buf.getvalue() and "all automatic checks passed" in buf.getvalue()


# ------------------------------------------------------------------ release zip
def test_release_zip_is_clean_reproducible_and_verifiable(tmp_path):
    z1 = BZ.build(tmp_path / "a", "r.zip")
    z2 = BZ.build(tmp_path / "b", "r.zip")
    assert z1.read_bytes() == z2.read_bytes()                                  # reproducible: fixed timestamps, sorted order
    names = zipfile.ZipFile(z1).namelist()
    assert all(n.startswith("bug-report-log-analyzer/") for n in names) and "bug-report-log-analyzer/README.md" in names
    bad = [n for n in names if re.search(r"__pycache__|\.pyc$|\.env$|\.db$|\.zip$|/\.git/|/\.venv/|benchmark-.*\.json|scenarios_out", n)]
    assert not bad, bad
    assert "bug-report-log-analyzer/.env.example" in names and "bug-report-log-analyzer/benchmarks/results/.gitkeep" in names
    assert "bug-report-log-analyzer/demo/logs/production_sample.log" in names
    checks = VR.verify_zip(z1)
    assert not [c for c in checks if c.status == "FAIL"], [c for c in checks if c.status == "FAIL"]
    assert checks[0].name == "zip extracts cleanly to one folder"


def test_zip_verification_rejects_dirty_or_unsafe_archives(tmp_path):
    z = tmp_path / "dirty.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("proj/README.md", "x")
        f.writestr("proj/.env", "SECRET=1")
    st = statuses(VR.verify_zip(z))
    assert st["no secrets, databases, caches or generated results"] == "FAIL" and st["required files present"] == "FAIL"
    two = tmp_path / "two.zip"
    with zipfile.ZipFile(two, "w") as f:
        f.writestr("a/x", "1")
        f.writestr("b/y", "2")
    assert VR.verify_zip(two)[0].status == "FAIL"
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as f:
        f.writestr("proj/../escape.txt", "1")
    assert VR.verify_zip(evil)[0].status == "FAIL"


# ------------------------------------------------------------------ commit helper
def parse_commit_script():
    text = (ROOT / "scripts" / "make_commits.ps1").read_text(encoding="utf-8")
    groups = []
    for msg, arr in re.findall(r'Commit-Group "([^"]+)" @\(([^)]*)\)', text):
        groups.append((msg, re.findall(r'"([^"]+)"', arr)))
    return text, groups


def test_commit_script_covers_the_repository_and_creates_a_clean_history(tmp_path):
    text, groups = parse_commit_script()
    messages = [m for m, _ in groups]
    for required in ("feat: add log ingestion pipeline", "feat: implement error extraction", "feat: add error grouping", "feat: implement source code retrieval",
                     "feat: add root cause analysis", "feat: generate Jira bug reports", "feat: add Streamlit dashboard", "test: add log analyzer tests",
                     "docs: add architecture documentation", "docs: add demo instructions"):
        assert required in messages, required
    assert all(re.match(r"(feat|fix|test|docs|chore|refactor): ", m) for m in messages)
    for _, paths in groups:
        for p in paths:
            assert (ROOT / p).exists(), f"make_commits.ps1 stages a path that does not exist: {p}"
    assert "git add -A" in text and "git init" in text
    if not shutil.which("git"):
        return
    work = tmp_path / "repo"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns("__pycache__", ".git", ".venv", "*.db", "dist", ".pytest_cache", "scenarios_out"))
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(work)]
    subprocess.run(git + ["init", "-q"], check=True)
    for msg, paths in groups:                                                  # the same operations the PowerShell script performs
        existing = [p for p in paths if (work / p).exists()]
        if existing:
            subprocess.run(git + ["add", "--"] + existing, check=True)
        if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode != 0:
            subprocess.run(git + ["commit", "-q", "-m", msg], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode != 0:
        subprocess.run(git + ["commit", "-q", "-m", "chore: release tooling, changelog and contributor files"], check=True)
    tracked = set(subprocess.run(git + ["ls-files"], capture_output=True, text=True, check=True).stdout.split())
    assert not [t for t in tracked if t == ".env" or t.endswith((".db", ".pyc")) or "__pycache__" in t], "ignored files were committed"
    assert "README.md" in tracked and "demo/logs/production_sample.log" in tracked and "app.py" in tracked
    status = subprocess.run(git + ["status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip()
    assert status == "", status                                                 # nothing left uncommitted
    count = int(subprocess.run(git + ["rev-list", "--count", "HEAD"], capture_output=True, text=True, check=True).stdout)
    assert 12 <= count <= len(groups) + 1


# ------------------------------------------------------------------ release documents
def test_acceptance_table_covers_every_criterion_and_cites_real_tests():
    doc = (ROOT / "docs" / "acceptance.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d+) \|", doc, flags=re.M)
    assert rows == [str(i) for i in range(1, 21)]
    import ast
    refs = re.findall(r"`(tests/[\w]+\.py)::(\w+)`", doc)
    assert len(refs) >= 20
    for rel, name in refs:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body), f"{rel}::{name}"
    for honest in ("Yours to verify", "Not verified by the author", "Not done by design"):
        assert honest in doc


def test_contributor_and_github_files_exist_and_carry_the_key_rules():
    c = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for needed in ("pytest", "observed evidence", "Never invent", "untrusted", "agent/rules.py", "Conventional"):
        assert needed.lower() in c.lower(), needed
    for f in (".github/ISSUE_TEMPLATE/bug_report.md", ".github/ISSUE_TEMPLATE/feature_request.md", ".github/pull_request_template.md"):
        assert (ROOT / f).read_text(encoding="utf-8").strip(), f
    assert "never paste confidential logs" in (ROOT / ".github/ISSUE_TEMPLATE/bug_report.md").read_text(encoding="utf-8")


def test_checklist_and_changelog_are_consistent_with_the_tools():
    check = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")
    for needed in ("verify_release.py", "build_release_zip.py", "make_commits.ps1", "benchmark.py", "screenshot_markdown.py", "gif_markdown.py", "pytest"):
        assert needed in check, needed
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert log.splitlines()[2].startswith("## 1.0.0-rc1") and "Not included" in log
