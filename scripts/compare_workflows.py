"""Compare your timed manual and agent-assisted trials and print resume bullets built ONLY from measured data.

    python scripts\\compare_workflows.py [--bench benchmarks\\results\\benchmark-....json]   (default: the newest benchmark file)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmarks.report import build_bullets, fmt_duration, summarize_trials  # noqa: E402
from scripts.manual_baseline import RESULTS, load_trials  # noqa: E402


def newest_benchmark(directory: Path) -> Path | None:
    files = sorted(directory.glob("benchmark-*.json"))
    return files[-1] if files else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench")
    ap.add_argument("--trials", default=str(RESULTS))
    ap.add_argument("--min-trials", type=int, default=3)
    args = ap.parse_args(argv)
    bench_path = Path(args.bench) if args.bench else newest_benchmark(ROOT / "benchmarks" / "results")
    bench = json.loads(bench_path.read_text(encoding="utf-8")) if bench_path and bench_path.exists() else None
    trials = load_trials(Path(args.trials))
    stats = summarize_trials(trials) if trials else None
    print(f"Benchmark file: {bench_path or 'none (run python scripts/benchmark.py)'}")
    if stats:
        print(f"\n{'scenario':<22}{'manual median':<18}{'assisted median':<18}{'speed-up':<10}")
        for r in stats["rows"]:
            m = fmt_duration(r["manual"]["median"]) if r["manual"]["n"] else "-"
            a = fmt_duration(r["assisted"]["median"]) if r["assisted"]["n"] else "-"
            print(f"{r['scenario']:<22}{m + ' (n=' + str(r['manual']['n']) + ')':<18}{a + ' (n=' + str(r['assisted']['n']) + ')':<18}"
                  f"{(str(r['speedup']) + 'x') if r['speedup'] else '-':<10}")
        print("\n'assisted' = machine time + your human review time. Trials with wrong answers are excluded.")
    print("\nRESUME BULLETS (only filled when the data supports them)\n")
    for b in build_bullets(bench, stats, min_trials=args.min_trials):
        print(f"[{b['id']}] " + (b["text"] if b["text"] else "NOT AVAILABLE YET"))
        if b["evidence"]:
            print(f"    evidence: {b['evidence']}")
        if b.get("note"):
            print(f"    note: {b['note']}")
        for need in b["needs"]:
            print(f"    needs: {need}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
