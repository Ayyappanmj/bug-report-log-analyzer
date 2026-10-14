"""Keeps docs/testing.md honest: every test it names must exist."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = re.compile(r"`(tests/[\w]+\.py)::(\w+)`")


def test_every_test_named_in_the_matrix_exists():
    refs = REF.findall((ROOT / "docs" / "testing.md").read_text(encoding="utf-8"))
    assert len(refs) >= 40
    missing = []
    for rel, name in refs:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        if not any(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body):
            missing.append(f"{rel}::{name}")
    assert not missing, missing


def test_matrix_covers_every_required_area():
    text = (ROOT / "docs" / "testing.md").read_text(encoding="utf-8")
    for area in ("Log parser", "Log normalization", "Error extraction", "Error grouping", "Code scanner", "Code search",
                 "Stack-trace parsing", "Source-code retrieval", "Root-cause schema", "Jira report generation", "Invalid AI output",
                 "Large-file handling", "Missing source file", "Malformed logs", "Empty logs", "Timeouts", "Error handling"):
        assert f"| {area} |" in text, area
