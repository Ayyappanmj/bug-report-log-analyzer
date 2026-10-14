"""Command-line preview of the pipeline: parse -> group -> retrieve code. (The Streamlit UI arrives in Phase 9.)

    python scripts/analyze_cli.py                      # bundled demo log + demo project
    python scripts/analyze_cli.py --log my.log --repo path\\to\\project --group G002
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.orchestrator import AnalysisPipeline  # noqa: E402
from code_analyzer.scanner import ScanError  # noqa: E402
from log_analyzer.ingest import IngestError  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default=str(ROOT / "demo" / "logs" / "production_sample.log"))
    ap.add_argument("--repo", default=str(ROOT / "demo" / "project"))
    ap.add_argument("--group", default="G001", help="group id to show code for (default: G001)")
    ap.add_argument("--export", metavar="DIR", help="write the Jira-ready report for --group (md, txt, json, jira wiki) into DIR")
    ap.add_argument("--ai", choices=["none", "ollama", "api"], default="none",
                    help="optional LLM refinement (default: none = deterministic only)")
    ap.add_argument("--model", help="override the model name from .env / defaults")
    args = ap.parse_args(argv)
    enhancer = None
    if args.ai != "none":
        import dataclasses

        from ai.base import AIProviderError, get_provider
        from ai.enhancer import LLMEnhancer
        from config import Settings
        base = Settings.from_env()
        kind = "ollama" if args.ai == "ollama" else "openai_compatible"
        settings = dataclasses.replace(base, ai_provider=kind)
        if args.model:
            settings = dataclasses.replace(settings, ollama_model=args.model, api_model=args.model)
        try:
            enhancer = LLMEnhancer(get_provider(settings), timeout=settings.ai_timeout, redact_emails=settings.redact_emails)
        except AIProviderError as exc:
            print(f"error: {exc}")
            return 2
    pipe = AnalysisPipeline(top_n=50, enhancer=enhancer, ai_top_n=Settings.from_env().ai_top_n if enhancer else 0)
    try:
        run = pipe.run(args.log, args.repo)
    except (IngestError, ScanError) as exc:
        print(f"error: {exc}")
        return 2
    st, d = run.parse_stats, run.dashboard
    print(f"Log: {st.total_lines} lines, {st.events} events, {st.unparsed_lines} unparsed lines")
    print(f"Code: {d['files_analyzed']} files | analysis took {d['analysis_seconds']}s "
          f"({', '.join(f'{k} {v:.3f}s' for k, v in run.timings.items() if k != 'total')})")
    print("Dashboard:", d, "\n")
    for g in run.grouping.groups:
        print(f"{g.id} {g.severity:<8} x{g.count:<4} {g.title[:70]}")
    report = run.reports.get(args.group)
    if report is None:
        print(f"\nNo group {args.group}")
        return 1
    print(f"\n== {report.group_id}: {report.incident}\nCategory: {report.category} | severity {report.severity} | "
          f"confidence {report.confidence} (heuristic) | code strategy: {report.code_strategy}")
    print("\nOBSERVED EVIDENCE")
    for e in report.observed_evidence:
        print(f" - {e.text}  [{e.source}]")
    print("\nINFERENCE (hypothesis, not confirmed)\n " + report.probable_root_cause)
    if run.ai_log:
        a = run.ai_log[0]
        print(f"\nAI: {run.ai_provider} | refined {sum(x['used'] for x in run.ai_log)}/{len(run.ai_log)} report(s)")
        if report.ai_enhanced:
            print(" AI confidence (model's own estimate):", report.ai_confidence, "| baseline hypothesis:", report.baseline_probable_root_cause)
        for x in run.ai_log:
            if x["fallback_reason"]:
                print(f" fallback for {x['group_id']}: {x['fallback_reason']}")
    print("\nAlternatives:", *[f"\n - {a}" for a in report.alternative_possibilities])
    print("\nSuggested fixes:", *[f"\n - {a}" for a in report.recommended_fix])
    for note in report.notes:
        print("NOTE:", note)
    for c in report.code_context[:2]:
        print(f"\n[{c['status']}{' VERIFIED' if c['verified'] else ''}] {c['file_path']}:{c['target_line']} {c['qualname'] or ''}")
        print(c["snippet"])
    if args.export:
        from reports.exporters import write_exports
        from reports.jira import build_ticket
        ticket = build_ticket(run, args.group)
        for p in write_exports(ticket, args.export):
            print("Wrote", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
