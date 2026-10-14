"""Build a clean release zip from the working tree.  python scripts\\build_release_zip.py [--out DIR] [--name FILE.zip]

Leaves out virtual environments, caches, secrets (.env), databases, other zips, benchmark results, scenario output and git data."""
from __future__ import annotations

import argparse
import fnmatch
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXCLUDE_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", "dist", "build",
                "scenarios_out", ".idea", ".vscode"}
EXCLUDE_FILES = (".env", ".env.*", "*.db", "*.sqlite", "*.zip", "*.pyc", ".coverage", "coverage.xml", "workflow-times.jsonl", "benchmark-*.json",
                 "latest.md", "Thumbs.db", ".DS_Store")
KEEP = (".env.example",)
PROJECT_DIR = "bug-report-log-analyzer"


def excluded(rel: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]) or rel.parts[0] in EXCLUDE_DIRS:
        return True
    if rel.name in KEEP:
        return False
    if rel.parts[:2] == ("benchmarks", "results") and rel.name != ".gitkeep":
        return True                                   # measurements belong to the machine that made them
    if rel.parts[:3] == ("docs", "screenshots", rel.name) and False:
        return False
    return any(fnmatch.fnmatch(rel.name, pat) for pat in EXCLUDE_FILES)


def collect(root: Path = ROOT) -> list[Path]:
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file() and not excluded(p.relative_to(root)))


def build(out_dir: Path, name: str | None = None, root: Path = ROOT) -> Path:
    from config import TOOL_VERSION
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (name or f"{PROJECT_DIR}-{TOOL_VERSION}.zip")
    files = collect(root)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            info = zipfile.ZipInfo(f"{PROJECT_DIR}/{rel.as_posix()}", date_time=(2026, 1, 1, 0, 0, 0))   # fixed time: reproducible
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (root / rel).read_bytes())
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--name")
    args = ap.parse_args(argv)
    target = build(Path(args.out), args.name)
    print(f"Built {target} ({target.stat().st_size / 1024:.0f} KB, {len(collect())} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
