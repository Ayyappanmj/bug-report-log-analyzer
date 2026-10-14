"""Check you are ready to record.  python scripts\\demo_check.py [--reset-history]

Verifies the demo data, runs the analysis once and prints the numbers you should see on screen, checks the port, and reports optional LLM status.
--reset-history deletes the saved History file so the History page is empty (only with this flag; it is never done automatically)."""
from __future__ import annotations

import socket
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.orchestrator import AnalysisPipeline  # noqa: E402
from config import Settings  # noqa: E402
from scripts.generate_demo_log import OUT as DEMO_LOG  # noqa: E402
from scripts.generate_demo_log import SRC, build_log  # noqa: E402
from ui import viewmodels as vm  # noqa: E402

DEMO_PROJECT = SRC.parent


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    critical: bool = True


def check_demo_data(log_path: Path = DEMO_LOG, project: Path = DEMO_PROJECT, compare_generator: bool = True) -> list[Check]:
    out = [Check("demo log exists", Path(log_path).is_file(), str(log_path)), Check("demo project exists", (Path(project) / "src").is_dir(), str(project))]
    if out[0].ok and compare_generator:
        same = Path(log_path).read_text(encoding="utf-8").replace("\r\n", "\n") == build_log()
        out.append(Check("demo log matches the demo source", same, "ok" if same else "run: python scripts\\generate_demo_log.py"))
    return out


def expected_screen_values(log_path: Path = DEMO_LOG, project: Path = DEMO_PROJECT) -> dict:
    run = AnalysisPipeline(top_n=8).run(log_path, project)
    d = run.to_dict()
    cards = {c["label"]: c["value"] for c in vm.dashboard_cards(d)}
    g1 = run.grouping.groups[0] if run.grouping.groups else None
    rep = run.reports.get(g1.id) if g1 else None
    return {"cards": cards, "top_group": f"{g1.id} {g1.title[:60]}" if g1 else None, "top_severity": g1.severity if g1 else None,
            "code_verified": bool(rep and rep.code_location_verified), "first_file": rep.affected_files[0] if rep and rep.affected_files else None,
            "analysis_seconds": round(run.timings["total"], 2)}


def port_free(port: int = 8501) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def streamlit_installed() -> bool:
    try:
        import streamlit  # noqa: F401
        return True
    except ImportError:
        return False


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    s = Settings.from_env()
    checks = [Check("Python 3.11 or newer", sys.version_info >= (3, 11), sys.version.split()[0]),
              Check("streamlit is installed", streamlit_installed(), "pip install -r requirements.txt")]
    checks += check_demo_data()
    checks.append(Check("port 8501 is free", port_free(), "close the other Streamlit window or use --server.port 8502", critical=False))
    checks.append(Check("public-demo mode is off (it hides the paths you will click)", not s.public_demo, "unset PUBLIC_DEMO", critical=False))
    for c in checks:
        print(f"[{'ok' if c.ok else ('FAIL' if c.critical else 'warn')}] {c.name}" + ("" if c.ok else f"  -> {c.detail}"))
    if "--reset-history" in args:
        db_path = Path(s.db_path) if Path(s.db_path).is_absolute() else ROOT / s.db_path
        if db_path.exists():
            db_path.unlink()
            print(f"Deleted {db_path}")
    if any(not c.ok and c.critical for c in checks):
        return 1
    v = expected_screen_values()
    print("\nWhat you should see on screen (measured now):")
    for k, val in v["cards"].items():
        print(f"  {k}: {val}")
    print(f"  Top incident: {v['top_group']} ({v['top_severity']}); source file {v['first_file']}; code verified: {v['code_verified']}")
    print(f"  Analysis took {v['analysis_seconds']} s: the progress bar is brief, so narrate over the result.")
    if not v["code_verified"]:
        print("  WARNING: the code is not verified: do not record until this is fixed.")
        return 1
    print("\nOptional LLM: the demo is rule-based and fast. If you enable Ollama for the recording, rehearse: model latency varies and was not measured.")
    print("Next: python scripts\\demo_rehearsal.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
