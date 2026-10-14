"""Mutation smoke check: break the code on purpose and see whether the tests notice.

For each mutant a COPY of the project is edited (your working tree is never touched) and the fallback test runner is run
(SKIP_SLOW=1). A mutant is "killed" if any test fails. Surviving mutants point at behaviour the tests do not pin down.
Run:  python scripts\\mutation_smoke.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MUTANTS = [
    ("log_analyzer/grouper.py", 'if ev.level == "ERROR":\n        return "HIGH"', 'if ev.level == "ERROR":\n        return "MEDIUM"', "ERROR level maps to MEDIUM severity"),
    ("log_analyzer/grouper.py", "norm = normalize_message(root.message)\n            key", "norm = root.message\n            key", "exception groups keep volatile message text"),
    ("log_analyzer/extractor.py", 'return self.exceptions[0] if self.style == "python" else self.exceptions[-1]', 'return self.exceptions[-1] if self.style == "python" else self.exceptions[0]', "root cause chosen from the wrong end of the chain"),
    ("log_analyzer/parser.py", "st.unparsed_lines += 1", "st.unparsed_lines += 0", "unparsed lines no longer counted"),
    ("log_analyzer/ingest.py", "if size > max_size_mb * 1024 * 1024:\n        raise IngestError(f\"File is", "if size > max_size_mb * 1024 * 1024 * 100:\n        raise IngestError(f\"File is", "log size limit effectively disabled"),
    ("code_analyzer/retriever.py", "if line_ok and _norm(sf.lines[line - 1]) == want:", "if line_ok and _norm(sf.lines[line - 1]) != want:", "verification logic inverted"),
    ("code_analyzer/scanner.py", "if path.is_symlink():\n                stats.skipped[\"symlink\"] += 1", "if False:\n                stats.skipped[\"symlink\"] += 1", "symlinked files are followed"),
    ("agent/root_cause_agent.py", 'og.severity == "MEDIUM"', 'og.severity != "NONE"', "any group counts as a precursor warning"),
    ("ai/enhancer.py", "valid = [i for i in inf.supporting_evidence if i in bundle.evidence]", "valid = list(inf.supporting_evidence)", "invented evidence ids accepted"),
    ("ai/redaction.py", "(?:AKIA|ASIA)", "(?:AKIB|ASIB)", "AWS keys no longer redacted"),
    ("ai/validation.py", "if isinstance(conf, bool) or not isinstance(conf, (int, float)) or", "if not isinstance(conf, (int, float)) or", "boolean accepted as confidence"),
    ("reports/jira.py", "    if not confirm:\n        raise JiraError", "    if False:\n        raise JiraError", "Jira issue created without confirmation"),
    ("reports/exporters.py", r're.sub(r"([{}\[\]|])", r"\\\1", text)', r're.sub(r"([{}\[\]])", r"\\\1", text)', "pipes not escaped in Jira markup"),
    ("storage/database.py", "if redact_payload:\n            payload = redact_obj", "if False:\n            payload = redact_obj", "history stored without redaction"),
    ("ui/viewmodels.py", "if g[\"count\"] < min_count:", "if g[\"count\"] > min_count:", "min-occurrence filter inverted"),
    ("log_analyzer/ingest.py", 'if "\\x1b" in line:\n        line = _ANSI.sub("", line)', 'if False:\n        line = _ANSI.sub("", line)', "ANSI escape sequences no longer stripped"),
    ("reports/sanitize.py", '_MD = re.compile(r"([\\\\\\[\\]<>])")', '_MD = re.compile(r"([\\\\<>])")', "square brackets no longer escaped in Markdown"),
    ("ai/http.py", "    def redirect_request(self, *args, **kwargs):\n        return None", "    def redirect_request(self, req, fp, code, msg, headers, newurl):\n        return super().redirect_request(req, fp, code, msg, headers, newurl)", "redirects followed with credentials"),
    ("security/policy.py", "if p == Path(p.anchor):", "if False:", "filesystem root no longer refused"),
    ("log_analyzer/grouper.py", "if g is None and len(self._groups) >= self.max_groups:", "if False:", "group cap removed"),
    ("ai/redaction.py", "if 13 <= len(digits) <= 19 and digits[0] in \"3456\" and _luhn(digits):", "if 13 <= len(digits) <= 19:", "card redaction without the Luhn check"),
    ("code_analyzer/scanner.py", "            if not is_inside(Path(os.path.realpath(path)), root_r):\n                stats.skipped[\"outside_root\"] += 1\n                continue\n", "", "files outside the project root are read"),
]


def run_suite(project: Path) -> tuple[bool, str]:
    env = {**os.environ, "SKIP_SLOW": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        r = subprocess.run([sys.executable, "scripts/run_basic_checks.py"], cwd=project, capture_output=True, text=True, env=env, timeout=600)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    return r.returncode == 0, (r.stdout.strip().splitlines() or [""])[-1]


def main() -> int:
    only = sys.argv[1:]  # optional: indexes of mutants to run
    killed = survived = invalid = 0
    for i, (rel, old, new, what) in enumerate(MUTANTS, 1):
        if only and str(i) not in only:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "proj"
            shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns("__pycache__", ".git", ".venv", "*.db", "*.zip", ".pytest_cache"))
            target = work / rel
            text = target.read_text(encoding="utf-8")
            if text.count(old) != 1:
                print(f"{i:>2} INVALID (pattern matched {text.count(old)} times) {rel}: {what}")
                invalid += 1
                continue
            target.write_text(text.replace(old, new), encoding="utf-8")
            ok, last = run_suite(work)
        status = "SURVIVED" if ok else "killed"
        survived += ok
        killed += not ok
        print(f"{i:>2} {status:<8} {rel}: {what}" + (f"  [{last}]" if ok else ""))
    total = killed + survived
    print(f"\n{killed} of {total} mutants killed" + (f", {invalid} invalid pattern(s)" if invalid else ""))
    return 0 if not survived and not invalid else 1


if __name__ == "__main__":
    sys.exit(main())
