"""Rehearse the 60-second demo with a timer.  python scripts\\demo_rehearsal.py

Shows each cue (what to do, what to say). Press Enter when you finish a segment; the script reports how your timing compares with the plan."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.demo_plan import SEGMENTS, TOTAL_SECONDS, plain  # noqa: E402


def summarize(marks: list[float], segments=SEGMENTS) -> dict:
    rows, prev = [], 0.0
    for seg, mark in zip(segments, marks):
        rows.append({"title": seg.title, "planned": seg.length, "actual": round(mark - prev, 1), "cumulative": round(mark, 1),
                     "planned_end": seg.end, "over_by": round(mark - seg.end, 1)})
        prev = mark
    total = marks[-1] if marks else 0.0
    return {"rows": rows, "total": round(total, 1), "planned_total": segments[-1].end,
            "verdict": "on time" if total <= segments[-1].end + 3 else f"over by {total - segments[-1].end:.0f} s: trim narration or skip the preview"}


def run_rehearsal(input_fn=input, clock=time.perf_counter, out=print, segments=SEGMENTS) -> dict:
    out(f"Rehearsal: {len(segments)} segments, planned total {segments[-1].end} s. Perform each action for real in the browser.")
    input_fn("Press Enter to start the clock ")
    t0 = clock()
    marks = []
    for seg in segments:
        out(f"\n[{seg.start:>2}-{seg.end:>2} s] {seg.title}\n   DO:  {plain(seg.action)}\n   SAY: {seg.say}")
        input_fn("   Press Enter when this segment is done ")
        marks.append(clock() - t0)
    result = summarize(marks, segments)
    out("\nSegment                         planned  actual  cumulative")
    for r in result["rows"]:
        out(f"{r['title']:<32}{r['planned']:>5} s {r['actual']:>6} s {r['cumulative']:>8} s" + ("   <-- slow" if r["actual"] > r["planned"] + 3 else ""))
    out(f"\nTotal {result['total']} s of {result['planned_total']} s: {result['verdict']}")
    return result


if __name__ == "__main__":
    run_rehearsal()
