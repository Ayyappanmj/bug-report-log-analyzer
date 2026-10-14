"""Benchmark the whole pipeline. Windows:  python scripts\\benchmark.py [--quick] [--sizes 1 5 10 25] [--repeats 3] [--ai ollama]

Every number is measured on THIS machine from synthetic logs. Nothing is estimated, and results record the machine they came from.
Each size runs in a fresh worker process so peak memory is per size. Log generation is not timed.
"""
from __future__ import annotations

import argparse
import gc
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmarks.loggen import generate_log  # noqa: E402
from benchmarks.machine import machine_info, peak_memory_mb  # noqa: E402
from benchmarks.report import render_markdown, summarize  # noqa: E402
from benchmarks.scenarios import build_scenarios, check_truth  # noqa: E402

DEMO_PROJECT = ROOT / "demo" / "project"
STAGES = ("parse", "group", "index", "retrieval", "analysis", "total")


def worker(log: str, repeats: int, expected: list[int]) -> dict:
    from agent.orchestrator import AnalysisPipeline
    timings = {k: [] for k in STAGES}
    run = None
    for _ in range(repeats):
        run = None
        gc.collect()
        run = AnalysisPipeline(top_n=5, max_log_mb=1000).run(log, DEMO_PROJECT)
        for k in STAGES:
            timings[k].append(run.timings[k])
    counts = sorted(g.count for g in run.grouping.groups)
    size_mb = Path(log).stat().st_size / (1024 * 1024)
    return {"actual_mb": round(size_mb, 2), "lines": run.parse_stats.total_lines, "events": run.parse_stats.events,
            "groups": len(run.grouping.groups), "error_groups": run.grouping.summary["error_groups"],
            "correct": counts == sorted(expected) and run.parse_stats.unparsed_lines == 0,
            "timings": {k: summarize(v) for k, v in timings.items()}, "repeats": repeats,
            "throughput_mb_s": round(size_mb / summarize(timings["parse"])["median"], 1), "peak_memory_mb": peak_memory_mb()}


def run_sizes(sizes, repeats, tmp: Path, log=print) -> list[dict]:
    results = []
    for mb in sizes:
        path = tmp / f"bench-{mb}mb.log"
        info = generate_log(path, mb)
        log(f"  {mb} MB: generated {info.megabytes:.1f} MB, {info.lines:,} lines; measuring ({repeats} run(s)) ...")
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--log", str(path), "--repeats", str(repeats),
                               "--expected", ",".join(map(str, info.expected_group_counts))], capture_output=True, text=True, timeout=3600)
        line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
        if proc.returncode != 0 or line is None:
            raise RuntimeError(f"worker failed for {mb} MB:\n{proc.stderr[-800:]}")
        entry = json.loads(line[len("RESULT_JSON "):])
        entry["requested_mb"] = mb
        results.append(entry)
        path.unlink(missing_ok=True)
    return results


def run_scenarios(repeats: int, tmp: Path) -> list[dict]:
    from agent.orchestrator import AnalysisPipeline
    from reports.exporters import render_markdown as ticket_md
    from reports.exporters import render_wiki
    from reports.jira import build_ticket
    out = []
    for sc in build_scenarios(tmp / "scenarios"):
        secs, run = [], None
        for _ in range(repeats):
            t0 = time.perf_counter()
            run = AnalysisPipeline(top_n=8).run(sc.log_path, sc.project_dir)
            secs.append(time.perf_counter() - t0)
        checks = check_truth(run, sc.truth)
        generated = False
        gid = next((g.id for g in run.grouping.groups if g.exception_type == sc.truth["exception_type"]), None)
        if gid and gid in run.reports:
            t = build_ticket(run, gid)
            generated = len(ticket_md(t)) > 500 and len(render_wiki(t)) > 500
        out.append({"name": sc.name, "events": run.parse_stats.events, "groups": len(run.grouping.groups), "seconds": summarize(secs),
                    "checks": checks, "report_generated": generated})
    return out


def measure_ai(model: str, tmp: Path, log=print) -> dict:
    from agent.orchestrator import AnalysisPipeline
    from ai.enhancer import LLMEnhancer
    from ai.ollama_provider import OllamaProvider
    from config import Settings
    s = Settings.from_env()
    provider = OllamaProvider(s.ollama_host, model or s.ollama_model)
    if not provider.is_available():
        return {"status": "not measured", "reason": provider.unavailable_reason()}
    seconds, refined, attempted, failures = [], 0, 0, []
    for sc in build_scenarios(tmp / "scenarios-ai"):
        log(f"  AI: {sc.name} ...")
        run = AnalysisPipeline(top_n=3, enhancer=LLMEnhancer(provider, timeout=s.ai_timeout), ai_top_n=1).run(sc.log_path, sc.project_dir)
        for entry in run.ai_log:
            attempted += 1
            seconds.append(entry["seconds"])
            refined += bool(entry["used"])
            if entry["fallback_reason"]:
                failures.append(f"{sc.name}/{entry['group_id']}: {entry['fallback_reason']}")
    return {"status": "measured", "model": provider.model, "reports_attempted": attempted, "reports_refined": refined,
            "seconds_per_report": summarize(seconds), "failures": failures}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", type=float, nargs="+", default=[1, 5, 10, 25])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--quick", action="store_true", help="1 MB only, 1 repeat (smoke test)")
    ap.add_argument("--ai", choices=["none", "ollama"], default="none")
    ap.add_argument("--ai-model", default="")
    ap.add_argument("--out", default=str(ROOT / "benchmarks" / "results"))
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--log", help=argparse.SUPPRESS)
    ap.add_argument("--expected", default="", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.worker:
        print("RESULT_JSON " + json.dumps(worker(args.log, args.repeats, [int(x) for x in args.expected.split(",") if x])))
        return 0
    sizes, repeats = ([1], 1) if args.quick else (args.sizes, args.repeats)
    print(f"Benchmark: sizes {sizes} MB, {repeats} repeat(s), AI: {args.ai}")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        results = {"schema": 1, "meta": machine_info(ROOT), "settings": {"sizes": sizes, "repeats": repeats, "ai": args.ai}}
        results["sizes"] = run_sizes(sizes, repeats, tmp)
        print("  scenarios ...")
        results["scenarios"] = run_scenarios(repeats, tmp)
        results["ai"] = measure_ai(args.ai_model, tmp) if args.ai == "ollama" else {"status": "not measured", "reason": "AI was not requested (use --ai ollama)"}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out / f"benchmark-{stamp}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out / "latest.md").write_text(render_markdown(results), encoding="utf-8")
    print("\n" + render_markdown(results))
    print(f"Saved {out / ('benchmark-' + stamp + '.json')} and {out / 'latest.md'}")
    return 0 if all(s["correct"] for s in results["sizes"]) else 1


if __name__ == "__main__":
    sys.exit(main())
