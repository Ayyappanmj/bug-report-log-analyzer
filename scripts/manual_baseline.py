"""Time YOUR OWN manual investigation versus the agent-assisted workflow, on the same scenarios.

    python scripts\\manual_baseline.py prepare                       # build scenario folders and print the task cards
    python scripts\\manual_baseline.py run --participant Sam --mode manual
    python scripts\\manual_baseline.py run --participant Sam --mode assisted
    python scripts\\manual_baseline.py status
    python scripts\\compare_workflows.py                              # medians, speed-up, and resume bullets (only from your data)

A trial only counts if your answers (exception, file, line) match the scenario's ground truth, so a fast wrong answer is not a win.
Protocol and caveats: docs/benchmarking.md.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmarks.scenarios import Scenario, build_scenarios  # noqa: E402

RESULTS = ROOT / "benchmarks" / "results" / "workflow-times.jsonl"
SCENARIOS_DIR = ROOT / "benchmarks" / "scenarios_out"
REPORT_REQUIREMENTS = ("the exception type", "the file and line where it was raised", "the probable cause", "evidence from the log",
                       "impact", "a suggested fix", "how to reproduce it")


def failing_line(scenario: Scenario) -> int:
    lines = (scenario.project_dir / scenario.truth["file"]).read_text(encoding="utf-8").splitlines()
    return next(i for i, l in enumerate(lines, 1) if scenario.truth["marker"] in l)


def check_answers(scenario: Scenario, exception: str, file: str, line: str) -> dict:
    t = scenario.truth
    exc_ok = t["exception_type"].lower() in (exception or "").lower()
    norm = (file or "").replace("\\", "/").strip().strip('"')
    file_ok = norm != "" and (norm == t["file"] or t["file"].endswith("/" + norm.split("/")[-1]) and norm.split("/")[-1] == t["file"].split("/")[-1])
    try:
        line_ok = int(str(line).strip()) == failing_line(scenario)
    except ValueError:
        line_ok = False
    return {"exception_ok": exc_ok, "file_ok": file_ok, "line_ok": line_ok, "correct": exc_ok and file_ok and line_ok}


def task_card(sc: Scenario) -> str:
    return (f"\n=== Scenario: {sc.name} - {sc.title} ===\nTask: {sc.task}\nLog:     {sc.log_path}\nProject: {sc.project_dir}\n"
            f"Deliverable: a bug report draft containing: {', '.join(REPORT_REQUIREMENTS)}.\n")


def append_trial(record: dict, path: Path = RESULTS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_trials(path: Path = RESULTS) -> list[dict]:
    if not Path(path).exists():
        return []
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def run_trial(sc: Scenario, mode: str, participant: str, *, input_fn=input, clock=time.perf_counter, out=print,
              results_path: Path = RESULTS, report_dir: Path | None = None) -> dict:
    out(task_card(sc))
    machine_seconds = 0.0
    if mode == "assisted":
        from agent.orchestrator import AnalysisPipeline
        from reports.exporters import write_exports
        from reports.jira import build_ticket
        run = AnalysisPipeline(top_n=8).run(sc.log_path, sc.project_dir)
        machine_seconds = run.timings["total"]
        gid = next((g.id for g in run.grouping.groups if g.exception_type == sc.truth["exception_type"]), run.grouping.groups[0].id if run.grouping.groups else None)
        if gid is None or gid not in run.reports:
            raise RuntimeError("The agent produced no report for this scenario")
        rdir = report_dir or (ROOT / "benchmarks" / "results" / "reports" / sc.name)
        paths = write_exports(build_ticket(run, gid), rdir, formats=("markdown",))
        out(f"The agent finished in {machine_seconds:.2f} s. Its report is at:\n  {paths[0]}\n"
            "Open it. Your job: verify it and decide it is ready to file (check the evidence, code and fix).")
    else:
        out("Work only with a text editor / search tools of your choice. Do NOT run the analyzer.")
    input_fn("Press Enter to START the clock ")
    t0 = clock()
    input_fn("Press Enter when the report is ready to file " if mode == "assisted" else "Press Enter when the bug report draft is complete ")
    human = clock() - t0
    exc = input_fn("Exception type (e.g. KeyError): ")
    file = input_fn("File where it was raised (e.g. src/x.py): ")
    line = input_fn("Line number of the failing statement: ")
    checks = check_answers(sc, exc, file, line)
    rec = {"schema": 1, "timestamp": datetime.now().isoformat(timespec="seconds"), "participant": participant, "scenario": sc.name,
           "mode": mode, "seconds": round(human + machine_seconds, 2), "human_seconds": round(human, 2),
           "machine_seconds": round(machine_seconds, 3), "correct": checks["correct"], "checks": checks,
           "answers": {"exception": exc, "file": file, "line": line}}
    append_trial(rec, results_path)
    out(f"Recorded: {rec['seconds']:.1f} s total ({'valid' if rec['correct'] else 'INVALID: answers do not match ground truth'}).")
    return rec


def status(trials: list[dict], out=print) -> None:
    if not trials:
        out("No trials recorded yet.")
        return
    from benchmarks.report import summarize_trials
    s = summarize_trials(trials)
    out(f"{'scenario':<22}{'manual (valid/invalid)':<26}{'assisted (valid/invalid)':<26}")
    for r in s["rows"]:
        out(f"{r['scenario']:<22}{str(r['manual']['n']) + '/' + str(r['manual_invalid']):<26}{str(r['assisted']['n']) + '/' + str(r['assisted_invalid']):<26}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    sub.add_parser("status")
    r = sub.add_parser("run")
    r.add_argument("--participant", required=True)
    r.add_argument("--mode", choices=["manual", "assisted"], required=True)
    r.add_argument("--scenario", default="all")
    r.add_argument("--no-shuffle", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "status":
        status(load_trials())
        return 0
    scenarios = build_scenarios(SCENARIOS_DIR)
    if args.cmd == "prepare":
        for sc in scenarios:
            print(task_card(sc))
        print("Tip: do one practice trial first and discard it by deleting its line from benchmarks/results/workflow-times.jsonl.")
        return 0
    chosen = scenarios if args.scenario == "all" else [s for s in scenarios if s.name == args.scenario]
    if not chosen:
        print("Unknown scenario. Available:", ", ".join(s.name for s in scenarios))
        return 2
    if not args.no_shuffle:
        random.shuffle(chosen)
    for sc in chosen:
        run_trial(sc, args.mode, args.participant)
    status(load_trials())
    return 0


if __name__ == "__main__":
    sys.exit(main())
