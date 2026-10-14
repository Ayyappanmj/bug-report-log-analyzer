"""Pure functions that turn an analysis result (the dict from AnalysisRun.to_dict()) into display data.
No Streamlit imports here, so this logic is unit-tested without a browser."""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from pathlib import Path

from log_analyzer.ingest import MAX_LINE_CHARS, IngestError, iter_log_lines, validate_log_path, validate_upload
from reports.sanitize import md_escape
from security.policy import PolicyError

ROOT = Path(__file__).resolve().parent.parent
DEMO_LOG = ROOT / "demo" / "logs" / "production_sample.log"
DEMO_PROJECT = ROOT / "demo" / "project"
SEVERITY_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
STATUS_LABEL = {
    "verified_exact": "✅ verified", "line_moved": "⚠️ line moved (not verified)", "function_only": "⚠️ function only (not verified)",
    "line_mismatch": "⚠️ line differs (not verified)", "line_unverified": "⚠️ not verified", "file_only": "⚠️ file only",
    "ambiguous_file": "⚠️ ambiguous file", "symbol_search": "⚠️ symbol match (not verified)",
    "message_match": "⚠️ message match (not verified)", "exception_match": "⚠️ exception match (not verified)",
    "keyword_search": "⚠️ keyword match (low confidence)", "external": "library code", "not_found": "not found",
}


class InputError(ValueError):
    """User input problem with a readable message."""


def severity_label(sev: str) -> str:
    return f"{SEVERITY_ICON.get(sev, '⚪')} {sev}"


def status_label(status: str) -> str:
    return STATUS_LABEL.get(status, status)


def dashboard_cards(run: dict) -> list[dict]:
    d = run["dashboard"]
    return [
        {"label": "Total Events", "value": f"{d['total_events']:,}", "help": f"{d['total_log_lines']:,} log lines parsed into events"},
        {"label": "Unique Errors", "value": f"{d['unique_errors']:,}", "help": "Error groups (ERROR/CRITICAL level) after grouping similar events"},
        {"label": "Critical Errors", "value": f"{d['critical_errors']:,}", "help": "Groups containing CRITICAL/FATAL-level events"},
        {"label": "Recurring Errors", "value": f"{d['recurring_errors']:,}", "help": "Error groups that occurred at least twice"},
        {"label": "Files Analyzed", "value": f"{d['files_analyzed']:,}", "help": "Source files scanned in the project folder"},
        {"label": "Analysis Duration", "value": f"{d['analysis_seconds']:.2f} s", "help": "Measured wall-clock time of this run"},
    ]


def _g(run: dict, gid: str | None) -> dict | None:
    return next((g for g in run["grouping"]["groups"] if g["id"] == gid), None)


group_by_id = _g


def report_for(run: dict, gid: str | None) -> dict | None:
    return run.get("reports", {}).get(gid) if gid else None


def groups_rows(run: dict, severities=None, min_count: int = 1, query: str = "") -> list[dict]:
    q = query.strip().lower()
    rows = []
    for g in run["grouping"]["groups"]:
        if severities and g["severity"] not in severities:
            continue
        if g["count"] < min_count:
            continue
        hay = " ".join([g["title"], g["id"], *g["services"], g.get("exception_type") or ""]).lower()
        if q and q not in hay:
            continue
        rep = report_for(run, g["id"])
        code = "not analyzed yet" if rep is None else "✅ verified" if rep["code_location_verified"] else \
            "no code found" if not rep["code_context"] else "⚠️ unverified"
        rows.append({"ID": g["id"], "Severity": severity_label(g["severity"]), "Count": g["count"], "Incident": g["title"],
                     "First seen": g["first_seen"] or "-", "Last seen": g["last_seen"] or "-",
                     "Services": ", ".join(g["services"]) or "-", "Recurring": "yes" if g["is_recurring"] else "no",
                     "Related": ", ".join(g["related"]) or "-", "Source code": code})
    return rows


def timeline_rows(group: dict) -> list[tuple[str, int]]:
    """Per-minute event counts with empty minutes filled in, ready for a bar chart."""
    tl = group.get("timeline") or {}
    if not tl:
        return []
    fmt = "%Y-%m-%d %H:%M"
    start, end = datetime.strptime(min(tl), fmt), datetime.strptime(max(tl), fmt)
    out, cur = [], start
    while cur <= end and len(out) < 2000:
        key = cur.strftime(fmt)
        out.append((key, tl.get(key, 0)))
        cur += timedelta(minutes=1)
    return out


def timing_rows(run: dict) -> list[dict]:
    names = {"parse": "Parse log", "group": "Group errors", "index": "Scan and index code", "retrieval": "Retrieve code",
             "analysis": "Root-cause analysis", "ai": "LLM refinement", "total": "Total"}
    t = run.get("timings_seconds", {})
    return [{"Stage": names[k], "Seconds": round(t[k], 4)} for k in names if k in t]


def severity_counts(run: dict) -> dict[str, int]:
    out = {s: 0 for s in SEVERITY_ORDER}
    for g in run["grouping"]["groups"]:
        out[g["severity"]] = out.get(g["severity"], 0) + 1
    return out


def parse_quality(run: dict) -> dict:
    p = run["parse_stats"]
    return {"lines": p["total_lines"], "events": p["events"], "continuation": p["continuation_lines"], "unparsed": p["unparsed_lines"],
            "truncated": p["truncated_lines"], "formats": p["events_by_format"], "levels": p["events_by_level"],
            "samples": p["unparsed_samples"]}


def unparsed_warning(run: dict) -> str | None:
    p = run["parse_stats"]
    if p["total_lines"] and p["events"] == 0:
        return "No log events were recognized. The file may not be a supported log format (see docs/log_formats.md)."
    if p["unparsed_lines"]:
        return f"{p['unparsed_lines']} line(s) did not match any known format and were skipped (not hidden: see the samples below)."
    return None


def ai_summary(run: dict) -> dict:
    log = run.get("ai_log", [])
    return {"provider": run.get("ai_provider", "none"), "attempted": len(log), "refined": sum(1 for x in log if x["used"]),
            "failures": [f"{x['group_id']}: {x['fallback_reason']}" for x in log if x["fallback_reason"]],
            "redactions": sum(sum(x["redactions"].values()) for x in log)}


def confidence_text(report: dict) -> str:
    c = report["confidence"]
    band = "low" if c < 0.4 else "moderate" if c < 0.65 else "fairly high"
    return f"{c:.2f} ({band}; heuristic score, not a probability)"


def md_safe(text) -> str:
    """Escape untrusted text for st.markdown/st.write so log content cannot become links, images, HTML or math."""
    return md_escape(str(text), ui=True)


def evidence_lines(report: dict) -> list[str]:
    return [f"{md_safe(e['text'])}  \n*source: {md_safe(e['source'])}*" for e in report["observed_evidence"]]


def ai_privacy_notice(provider: str, use_ai: bool) -> str | None:
    if not use_ai:
        return None
    if provider in ("openai_compatible", "api"):
        return ("Online AI provider selected: redacted evidence and code snippets will be sent to the server configured in API_BASE_URL. "
                "Redaction is best-effort; do not use this with confidential logs.")
    return "Local LLM: evidence stays on this computer (it is sent only to the Ollama server you configured)."


# ---------------------------------------------------------------------------- inputs
def resolve_repo_path(text: str, policy=None) -> Path | None:
    """Empty -> None (no code retrieval). Accepts quoted paths pasted from Windows Explorer."""
    t = (text or "").strip().strip('"').strip("'").strip()
    if not t:
        return None
    p = Path(t).expanduser()
    if policy is not None:
        try:
            p = policy.check(p)
        except PolicyError as exc:
            raise InputError(str(exc)) from None
    if not p.exists():
        raise InputError(f"Project folder not found: {p}")
    if not p.is_dir():
        raise InputError(f"Not a folder: {p}")
    return p


def check_log_source(upload_name: str | None, upload_size: int | None, path_text: str, max_mb: int, policy=None) -> tuple[str, str]:
    """Returns (kind, label): kind is 'upload' or 'path'. Raises InputError with a readable message."""
    try:
        if upload_name:
            return "upload", validate_upload(upload_name, upload_size or 0, max_size_mb=max_mb)
        t = (path_text or "").strip().strip('"').strip("'").strip()
        if not t:
            raise InputError("Choose a log file: upload one, enter a path, or click Load demo.")
        p = Path(t).expanduser()
        if policy is not None:
            p = policy.check(p)
        return "path", str(validate_log_path(p, max_size_mb=max_mb))
    except (IngestError, PolicyError) as exc:
        raise InputError(str(exc)) from None


def preview_lines(source, n: int = 40) -> list[str]:
    """First `n` lines of a path or of upload bytes (bounded line length)."""
    stream = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    out = []
    for line in iter_log_lines(stream, max_line_chars=min(MAX_LINE_CHARS, 400)):
        out.append(line)
        if len(out) >= n:
            break
    return out


def language_for_streamlit(lang: str | None) -> str | None:
    return {"python": "python", "javascript": "javascript", "typescript": "typescript", "java": "java"}.get(lang or "")


def numbered_snippet(ctx: dict) -> str:
    start = ctx.get("start_line") or 1
    target = ctx.get("target_line")
    lines = (ctx.get("snippet") or "").split("\n")
    return "\n".join(f"{'>' if start + i == target else ' '} {start + i:>5}  {t}" for i, t in enumerate(lines))


def safe_slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "run"
