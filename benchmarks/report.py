"""Statistics, Markdown rendering and resume-bullet generation. Bullets are produced ONLY from measured data."""
from __future__ import annotations

import statistics


def summarize(values: list[float]) -> dict:
    vals = [float(v) for v in values]
    if not vals:
        return {"median": None, "min": None, "max": None, "n": 0}
    return {"median": round(statistics.median(vals), 4), "min": round(min(vals), 4), "max": round(max(vals), 4), "n": len(vals)}


def fmt_duration(seconds: float) -> str:
    return f"{seconds:.1f} s" if seconds < 90 else f"{seconds / 60:.1f} min"


def render_markdown(r: dict) -> str:
    m = r["meta"]
    out = ["# Benchmark results", "",
           f"Measured on: {m['os']} · {m['processor']} · {m['cpu_count']} CPU(s) · RAM {m['ram_gb']} GB · Python {m['python']} · "
           f"tool v{m['tool_version']} · {m['timestamp']}" + (f" · commit {m['git_commit'][:10]}" if m.get("git_commit") else ""), "",
           "These numbers describe THIS machine and synthetic logs only. Do not quote them for other hardware or real production logs.", "",
           f"## Log size scaling (median of {r['settings']['repeats']} run(s); seconds)", "",
           "| Log MB | Lines | Events | Error groups | Correct | Parse | Group | Index code | Retrieve code | Analyze | Total | Parse MB/s | Peak memory MB |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in r["sizes"]:
        t = s["timings"]
        g = lambda k: f"{t[k]['median']:.3f}" if t.get(k, {}).get("median") is not None else "-"  # noqa: E731
        out.append(f"| {s['actual_mb']:.1f} | {s['lines']:,} | {s['events']:,} | {s['error_groups']} | {'yes' if s['correct'] else '**NO**'} | "
                   f"{g('parse')} | {g('group')} | {g('index')} | {g('retrieval')} | {g('analysis')} | {g('total')} | "
                   f"{s['throughput_mb_s']:.1f} | {s['peak_memory_mb'] if s['peak_memory_mb'] is not None else 'n/a'} |")
    out += ["", "'Correct' means the group sizes found equal the exact counts the generator wrote.", "",
            "## Scenarios with known root causes (synthetic)", "",
            "| Scenario | Events | Groups | Median seconds | Root-cause group found | Raise site correct | Verified code at truth | Failing line shown | Report generated |",
            "|---|---|---|---|---|---|---|---|---|"]
    yn = lambda b: "yes" if b else "no"  # noqa: E731
    for s in r["scenarios"]:
        c = s["checks"]
        out.append(f"| {s['name']} | {s['events']:,} | {s['groups']} | {s['seconds']['median']:.3f} | {yn(c['group_found'])} | "
                   f"{yn(c['raise_site_correct'])} | {yn(c['code_verified_at_truth'])} | {yn(c['failing_line_shown'])} | {yn(s['report_generated'])} |")
    out += ["", "These scenarios were written by the tool's author together with its rules: passing them shows the pipeline works as designed, "
                "not that it generalizes to unseen systems.", "", "## AI analysis time", ""]
    ai = r.get("ai", {})
    if ai.get("status") == "measured":
        out.append(f"Model `{ai['model']}`: {ai['reports_refined']} of {ai['reports_attempted']} report(s) refined; "
                   f"median {ai['seconds_per_report']['median']:.1f} s per report (min {ai['seconds_per_report']['min']:.1f}, "
                   f"max {ai['seconds_per_report']['max']:.1f}).")
        if ai.get("failures"):
            out.append("Fallbacks: " + "; ".join(ai["failures"]))
    else:
        out.append(f"Not measured: {ai.get('reason', 'AI was not requested')}.")
    return "\n".join(out) + "\n"


def summarize_trials(trials: list[dict]) -> dict:
    """Per scenario and mode medians from VALID (answer-checked) trials only."""
    by: dict = {}
    for t in trials:
        key = (t["scenario"], t["mode"])
        by.setdefault(key, {"valid": [], "invalid": 0})
        if t.get("correct"):
            by[key]["valid"].append(t["seconds"])
        else:
            by[key]["invalid"] += 1
    scenarios = sorted({k[0] for k in by})
    rows = []
    for sc in scenarios:
        man, ass = by.get((sc, "manual"), {"valid": [], "invalid": 0}), by.get((sc, "assisted"), {"valid": [], "invalid": 0})
        row = {"scenario": sc, "manual": summarize(man["valid"]), "assisted": summarize(ass["valid"]),
               "manual_invalid": man["invalid"], "assisted_invalid": ass["invalid"], "speedup": None}
        if man["valid"] and ass["valid"]:
            row["speedup"] = round(row["manual"]["median"] / row["assisted"]["median"], 2)
        rows.append(row)
    paired = [r for r in rows if r["speedup"] is not None]
    return {"rows": rows, "paired_scenarios": len(paired),
            "manual_valid": sum(r["manual"]["n"] for r in rows), "assisted_valid": sum(r["assisted"]["n"] for r in rows),
            "median_manual": summarize([r["manual"]["median"] for r in paired])["median"] if paired else None,
            "median_assisted": summarize([r["assisted"]["median"] for r in paired])["median"] if paired else None,
            "participants": sorted({t.get("participant", "?") for t in trials})}


def build_bullets(bench: dict | None, stats: dict | None, min_trials: int = 3, min_scenarios: int = 2) -> list[dict]:
    """Resume bullets filled ONLY with measured values. Each item: {id, text or None, needs: [what is missing], evidence}."""
    out = []
    ai = (bench or {}).get("ai", {})
    ai_used = ai.get("status") == "measured" and ai.get("reports_refined", 0) > 0

    # A: size / groups / time
    a = {"id": "A", "text": None, "needs": [], "evidence": None}
    good = [s for s in (bench or {}).get("sizes", []) if s["correct"]]
    if not good:
        a["needs"].append("Run: python scripts\\benchmark.py (needs at least one size whose output was checked correct)")
    else:
        s = max(good, key=lambda x: x["actual_mb"])
        z = s["timings"]["total"]["median"]
        how = ("structured log parsing, source-code retrieval, and LLM-assisted root-cause analysis" if ai_used
               else "structured log parsing, source-code retrieval, and rule-based root-cause analysis")
        a["text"] = (f"Developed {'an AI-powered' if ai_used else 'a'} log analysis agent that analyzed {s['actual_mb']:.0f} MB of application logs "
                     f"and identified {s['error_groups']} error groups in {z:.1f} seconds by combining {how}.")
        a["evidence"] = f"largest verified size: {s['actual_mb']:.1f} MB, median of {s['timings']['total']['n']} run(s) on {bench['meta']['processor']}"
        if not ai_used:
            a["note"] = "'AI-powered' is omitted because no LLM run was measured. Run with --ai ollama to measure it."
    out.append(a)

    # B: scenarios
    b = {"id": "B", "text": None, "needs": [], "evidence": None}
    ok = [s for s in (bench or {}).get("scenarios", []) if s["checks"].get("all_correct") and s["report_generated"]]
    if not ok:
        b["needs"].append("Run: python scripts\\benchmark.py (needs scenarios whose root cause and report were checked correct)")
    else:
        tail = "using Python, Streamlit, and local LLM inference" if ai_used else "using Python and Streamlit (local LLM refinement optional)"
        b["text"] = (f"Built a bug-report automation agent that retrieved relevant source-code context and generated Jira-compatible incident "
                     f"reports for {len(ok)} benchmark scenarios {tail}.")
        b["evidence"] = f"{len(ok)} of {len(bench['scenarios'])} synthetic scenarios passed every ground-truth check"
        if not ai_used:
            b["note"] = "'local LLM inference' is omitted because no LLM run was measured."
    out.append(b)

    # C: manual vs assisted
    c = {"id": "C", "text": None, "needs": [], "evidence": None}
    if not stats or not stats["rows"]:
        c["needs"].append("Record timed trials: python scripts\\manual_baseline.py run --mode manual / --mode assisted")
    else:
        if stats["manual_valid"] < min_trials:
            c["needs"].append(f"{min_trials - stats['manual_valid']} more correct MANUAL trial(s) (have {stats['manual_valid']})")
        if stats["assisted_valid"] < min_trials:
            c["needs"].append(f"{min_trials - stats['assisted_valid']} more correct ASSISTED trial(s) (have {stats['assisted_valid']})")
        if stats["paired_scenarios"] < min_scenarios:
            c["needs"].append(f"manual and assisted trials on at least {min_scenarios} common scenarios (have {stats['paired_scenarios']})")
        if not c["needs"]:
            m, a_ = stats["median_manual"], stats["median_assisted"]
            c["text"] = (f"Cut the time to find a root cause and draft a bug report from a median of {fmt_duration(m)} (manual) to "
                         f"{fmt_duration(a_)} (agent-assisted, including human review) across {stats['paired_scenarios']} synthetic scenarios "
                         f"({stats['manual_valid'] + stats['assisted_valid']} answer-checked trials).")
            c["evidence"] = f"participants: {', '.join(stats['participants'])}; per-scenario medians compared"
            c["note"] = "Say 'synthetic scenarios' and the participant count if asked: this is not a study of real incidents."
    out.append(c)
    return out
