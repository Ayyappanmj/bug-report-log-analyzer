"""Check the project is release-ready.  python scripts\\verify_release.py [--tests] [--strict] [--zip PATH]

  (default)  structure, forbidden files, secrets scan, version consistency, imports, open placeholders ([todo])
  --tests    also run the test suite (pytest if installed, otherwise the fallback runner)
  --strict   fail while placeholders (your name, contact, repo URL) remain
  --zip P    extract a release zip into a temporary folder and run the same checks there (a clean-extract test)"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = [
    "README.md", "LICENSE", "SECURITY.md", "CHANGELOG.md", "CONTRIBUTING.md", ".gitignore", ".env.example", "requirements.txt", "requirements-dev.txt",
    "Dockerfile", ".dockerignore", "pytest.ini", "pyproject.toml", "app.py", "config.py", ".github/workflows/tests.yml", ".streamlit/config.toml",
    "demo/logs/production_sample.log", "demo/project/src/database.py", "demo/project/src/payment_service.py", "demo/project/src/checkout.py",
    "docs/architecture.md", "docs/demo.md", "docs/testing.md", "docs/benchmarking.md", "docs/release_checklist.md", "docs/acceptance.md",
    "agent/orchestrator.py", "log_analyzer/parser.py", "code_analyzer/retriever.py", "ai/enhancer.py", "reports/jira.py", "storage/database.py", "ui/dashboard.py",
]
FORBIDDEN_NAMES = {".env", ".venv", "venv", ".git", "history.db", ".coverage", ".pytest_cache"}
FORBIDDEN_SUFFIXES = (".db", ".sqlite", ".pyc", ".zip")
CACHE_DIRS = {"__pycache__", ".pytest_cache"}
PLACEHOLDERS = [("LICENSE", "<YOUR NAME>", "put your name in the license"), ("SECURITY.md", "Replace this paragraph", "add your real security contact"),
                ("docs/portfolio.md", "<your repository URL", "add your repository URL after publishing")]
GENERATED_BENCH = re.compile(r"^benchmarks/results/(?!\.gitkeep)")


@dataclass
class Check:
    name: str
    status: str            # ok | FAIL | todo | warn
    detail: str = ""


def check_required(root: Path) -> list[Check]:
    missing = [f for f in REQUIRED if not (root / f).exists()]
    return [Check("required files present", "FAIL" if missing else "ok", ", ".join(missing) if missing else f"{len(REQUIRED)} files")]


def forbidden_files(root: Path, include_cache: bool = False) -> list[str]:
    bad = []
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        parts = set(rel.parts)
        if (".git" in parts or ".venv" in parts) and not include_cache:
            continue
        if parts & CACHE_DIRS:
            if include_cache:
                bad.append(rel.as_posix())
            continue
        if p.is_file() and (rel.name in FORBIDDEN_NAMES or rel.name.endswith(FORBIDDEN_SUFFIXES) or GENERATED_BENCH.match(rel.as_posix())):
            bad.append(rel.as_posix())
        elif p.is_dir() and rel.name in FORBIDDEN_NAMES:
            bad.append(rel.as_posix() + "/")
    return sorted(bad)


def check_forbidden(root: Path, include_cache: bool = False) -> list[Check]:
    bad = forbidden_files(root, include_cache)
    return [Check("no secrets, databases, caches or generated results", "FAIL" if bad else "ok", ", ".join(bad[:8]) if bad else "clean")]


def scan_secrets(root: Path) -> list[str]:
    # use the project's own engine; if the tree under test lacks it (a broken archive), fall back to this checkout's copy
    sys.path.insert(0, str(root if (root / "ai" / "redaction.py").exists() else ROOT))
    try:
        import importlib
        sys.modules.pop("ai.redaction", None)
        redact = importlib.import_module("ai.redaction").redact
    finally:
        sys.path.pop(0)
    hits = []
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if not p.is_file() or rel.parts[0] in ("tests", "docs", ".git", ".venv", "benchmarks") or "__pycache__" in rel.parts or p.suffix in (".zip", ".db", ".pyc"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found = redact(text, redact_emails=False)
        for noisy in ("secret_assignment", "card"):
            found.counts.pop(noisy, None)
        if found.total:
            hits.append(f"{rel.as_posix()} {dict(found.counts)}")
    return hits


def check_secrets(root: Path) -> list[Check]:
    hits = scan_secrets(root)
    return [Check("secrets scan (project's own redaction engine)", "FAIL" if hits else "ok", "; ".join(hits[:5]) if hits else "nothing found")]


def check_versions(root: Path) -> list[Check]:
    config = (root / "config.py").read_text(encoding="utf-8")
    version = re.search(r'TOOL_VERSION = "([^"]+)"', config).group(1)
    changelog = re.search(r"^## (\S+)", (root / "CHANGELOG.md").read_text(encoding="utf-8"), flags=re.M).group(1)
    readme = (root / "README.md").read_text(encoding="utf-8")
    ok = changelog == version and version in readme
    return [Check("version consistent (config, changelog, README)", "ok" if ok else "FAIL", f"config {version}, changelog {changelog}, README mentions: {version in readme}")]


def check_placeholders(root: Path) -> list[Check]:
    out = []
    for rel, marker, todo in PLACEHOLDERS:
        p = root / rel
        if p.exists() and marker in p.read_text(encoding="utf-8"):
            out.append(Check(f"placeholder in {rel}", "todo", todo))
    return out


IMPORT_PROBE = r'''
import importlib, json, pathlib, sys
root = pathlib.Path(".").resolve(); sys.path.insert(0, str(root))
ok, failed, skipped = [], [], []
OPTIONAL = {"streamlit", "pydantic", "pandas"}
for p in sorted(root.rglob("*.py")):
    rel = p.relative_to(root)
    if rel.parts[0] in ("tests", "demo", ".venv", ".git") or "__pycache__" in rel.parts or rel.name == "app.py":
        continue
    mod = ".".join(rel.with_suffix("").parts)
    if mod.endswith(".__init__"):
        mod = mod[: -len(".__init__")]
    try:
        importlib.import_module(mod); ok.append(mod)
    except ModuleNotFoundError as e:
        (skipped if (e.name or "").split(".")[0] in OPTIONAL else failed).append(f"{mod}: {e}")
    except Exception as e:
        failed.append(f"{mod}: {type(e).__name__}: {e}")
print("PROBE " + json.dumps({"ok": len(ok), "failed": failed, "skipped": skipped}))
'''


def check_imports(root: Path) -> list[Check]:
    r = subprocess.run([sys.executable, "-c", IMPORT_PROBE], cwd=root, capture_output=True, text=True, timeout=300)
    line = next((l for l in r.stdout.splitlines() if l.startswith("PROBE ")), None)
    if line is None:
        return [Check("every module imports", "FAIL", (r.stderr or r.stdout)[-300:])]
    d = json.loads(line[6:])
    status = "FAIL" if d["failed"] else "ok"
    detail = f"{d['ok']} modules imported" + (f"; {len(d['skipped'])} need an optional package (streamlit/pydantic/pandas)" if d["skipped"] else "")
    return [Check("every module imports", status, "; ".join(d["failed"][:4]) if d["failed"] else detail)]


def check_tests(root: Path) -> list[Check]:
    try:
        import pytest  # noqa: F401
        cmd = [sys.executable, "-m", "pytest", "-q", "-x"]
        runner = "pytest"
    except ImportError:
        cmd = [sys.executable, "scripts/run_basic_checks.py"]
        runner = "fallback runner (pytest is not installed)"
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=1800)
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    return [Check(f"test suite via {runner}", "ok" if r.returncode == 0 else "FAIL", tail)]


def _safe(fn, label: str, *args) -> list[Check]:
    """A check that crashes (missing file, broken tree) is reported as a failure, never as a traceback."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        return [Check(label, "FAIL", f"could not run: {type(exc).__name__}: {str(exc)[:120]}")]


def run_checks(root: Path, tests: bool = False, include_cache: bool = False) -> list[Check]:
    checks = (_safe(check_required, "required files present", root) + _safe(check_forbidden, "no secrets, databases, caches or generated results", root, include_cache)
              + _safe(check_secrets, "secrets scan (project's own redaction engine)", root)
              + _safe(check_versions, "version consistent (config, changelog, README)", root)
              + _safe(check_imports, "every module imports", root))
    if tests:
        checks += _safe(check_tests, "test suite", root)
    return checks + _safe(check_placeholders, "placeholders", root)


def verify_zip(zip_path: Path, tests: bool = False) -> list[Check]:
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            tops = {n.split("/")[0] for n in names}
            if len(tops) != 1:
                return [Check("zip has one top-level folder", "FAIL", ", ".join(sorted(tops)[:5]))]
            if any(n.startswith("/") or ".." in Path(n).parts for n in names):
                return [Check("zip paths are safe", "FAIL", "absolute or parent paths found")]
            z.extractall(tmp)
        root = Path(tmp) / tops.pop()
        return [Check("zip extracts cleanly to one folder", "ok", f"{len(names)} entries")] + run_checks(root, tests=tests, include_cache=True)


def report(checks: list[Check], out=print) -> int:
    for c in checks:
        out(f"[{c.status}] {c.name}" + (f": {c.detail}" if c.detail else ""))
    return 1 if any(c.status == "FAIL" for c in checks) else 0


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    strict, tests = "--strict" in args, "--tests" in args
    if "--zip" in args:
        checks = verify_zip(Path(args[args.index("--zip") + 1]), tests=tests)
    else:
        checks = run_checks(ROOT, tests=tests)
    code = report(checks)
    todo = [c for c in checks if c.status == "todo"]
    if todo:
        print(f"\n{len(todo)} placeholder(s) for you to fill before publishing (see docs/release_checklist.md).")
    print("\nRESULT:", "FAILED" if code else ("not publishable yet (placeholders)" if todo and strict else "all automatic checks passed"))
    return 1 if code or (strict and todo) else 0


if __name__ == "__main__":
    sys.exit(main())
