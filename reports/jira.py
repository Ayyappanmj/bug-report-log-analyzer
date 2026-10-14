"""Jira-ready bug report: ticket model, builder (from a root-cause report), REST payload and optional client.

Nothing is sent anywhere unless the caller passes explicit Jira credentials AND confirm=True to `create_issue`.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request

from ai.http import open_no_redirect
from dataclasses import dataclass, field
from datetime import datetime

from ai.redaction import redact
from config import TOOL_VERSION

REVIEW_CHECKLIST = (
    "Confirm the root-cause hypothesis against runtime evidence (metrics, database logs, a reproduction).",
    "Check items marked NOT verified, especially the source location.",
    "Remove or confirm any confidential data before sharing this report.",
    "Adjust severity and priority to your team's rules.",
)

TESTING = {
    "db_pool_timeout": ("Add a load test with more concurrent requests than the pool size; assert requests fail fast or queue instead of hanging.",
                        "Add a test (with a fake pool) proving connections are released after exceptions.",
                        "Add an alert or dashboard check on pool utilization."),
    "db_saturation_warning": ("Add a load test that watches pool utilization and slow-query counters.",),
    "network_connection": ("Add a test that makes the dependency unavailable and checks retry/backoff behaviour.",),
    "generic_timeout": ("Add a test with a slow dependency and assert the timeout and the user-facing error.",),
    "deadlock": ("Add a concurrency test that runs two transactions in opposite lock order.",),
    "auth_failure": ("Add tests for expired, malformed and missing tokens expecting 401/403.",),
    "missing_field": ("Add a regression test with a payload lacking the field; expect a 4xx validation error, not a 5xx.",),
    "null_reference": ("Add a regression test for the empty/None case on this path.",),
    "out_of_memory": ("Add a test with a large input and check memory use stays bounded.",),
    "disk_space": ("Add a test simulating a full disk on the write path.",),
    "validation_error": ("Add tests for the rejected value shapes.",),
    "file_missing": ("Add a startup check test for required files.",),
    "health_readiness": ("Add a test that fails the probed dependency and checks the probe and traffic handling.",),
    "upstream_error": ("Add a test with a failing upstream and check gateway timeouts and fallbacks.",),
}
GENERIC_TESTING = ("Add a regression test that reproduces the failing call path.",
                   "After the fix, re-run the original scenario and confirm this error group no longer appears in the log.")


@dataclass
class JiraTicket:
    group_id: str
    title: str
    summary: str
    severity: str
    priority: str
    priority_rationale: str
    component: str
    labels: list[str]
    environment: list[tuple[str, str]]
    error_message: str
    steps_to_reproduce: list[str]
    expected_behavior: str
    actual_behavior: list[str]
    observed_evidence: list[dict]
    root_cause_hypothesis: str
    alternatives: list[str]
    confidence: dict
    impact_observed: list[str]
    impact_inferred: str
    code: list[dict]
    suggested_fix: list[str]
    investigation: list[str]
    testing: list[str]
    logs: dict
    ai: dict
    review: dict
    generated_at: str
    tool_version: str
    redactions: dict
    disclaimer: str
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["environment"] = [{"name": k, "value": v} for k, v in self.environment]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "JiraTicket":
        """Rebuild a ticket from `to_dict()` output (used when reopening saved runs)."""
        import dataclasses
        names = {f.name for f in dataclasses.fields(cls)}
        data = {k: v for k, v in d.items() if k in names}
        data["environment"] = [(e["name"], e["value"]) if isinstance(e, dict) else tuple(e) for e in data.get("environment", [])]
        data.setdefault("extra", {})
        return cls(**data)


# ----------------------------------------------------------------------------- builder
def recommend_priority(report) -> tuple[str, str]:
    """Documented heuristic; teams should adjust it."""
    burst = report.pattern.get("label") == "sustained burst"
    has_5xx = any("HTTP responses recorded" in s for s in report.observed_impact)
    many = report.frequency >= 10
    if report.severity == "CRITICAL":
        return "Highest", "Group contains CRITICAL-level events."
    if report.severity == "HIGH":
        if has_5xx or burst or many:
            why = [w for w, f in (("linked HTTP 5xx responses", has_5xx), ("sustained burst", burst), (">=10 occurrences", many)) if f]
            return "High", "ERROR-level group with " + ", ".join(why) + "."
        return "Medium", "ERROR-level group with few occurrences and no recorded 5xx responses."
    if report.severity == "MEDIUM":
        return ("Medium", "WARN-level group in a sustained burst.") if burst else ("Low", "WARN-level group; no sustained burst.")
    return "Low", "Low severity."


def _clean_label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")[:40]


def build_ticket(run, group_id: str, *, redact_secrets: bool = True, redact_emails: bool = True) -> JiraTicket:
    """Build a ticket draft from a finished AnalysisRun. The group must already have a report (see analyze_group)."""
    report = run.reports.get(group_id)
    if report is None:
        raise KeyError(f"No analysis for {group_id}; analyze it first")
    group = next(g for g in run.grouping.groups if g.id == group_id)
    counts: dict = {}

    def clean(text):
        if not redact_secrets or not text:
            return text
        r = redact(text, redact_emails=redact_emails)
        for k, v in r.counts.items():
            counts[k] = counts.get(k, 0) + v
        return r.text

    def clean_list(items):
        return [clean(i) for i in items]

    service = report.affected_services[0] if report.affected_services else "Application"
    what = report.exception or report.category
    n = report.frequency
    title = f"[{report.severity}] {service}: {what} ({n} occurrence{'s' if n != 1 else ''})"[:255]
    window = (f"between {report.first_occurrence} and {report.last_occurrence}" if report.first_occurrence and report.last_occurrence
              and report.first_occurrence != report.last_occurrence else f"at {report.first_occurrence or 'an unknown time'}")
    summary = (f"{what} was logged {n} time(s) {window} ({report.pattern.get('label', 'unknown')} pattern). "
               f"Category: {report.category}. Source location "
               + ("verified against the stack trace." if report.code_location_verified else "NOT verified."))
    priority, why = recommend_priority(report)

    env = [("Log file", run.log_name), ("Services in log", ", ".join(report.affected_services) or "unknown"),
           ("First occurrence", report.first_occurrence or "unknown"), ("Last occurrence", report.last_occurrence or "unknown"),
           ("Log time zone", "as written in the log (timezone-aware stamps converted to UTC)")]
    if run.git:
        env.append(("Repository", f"branch {run.git.get('branch') or 'detached'}, commit {(run.git.get('commit') or 'unknown')[:12]}"))
    env.append(("Analyzed by", f"Bug Report & Log Analyzer Agent v{TOOL_VERSION} ({run.ai_provider if report.ai_enhanced else 'deterministic mode'})"))

    actual = [f"{what} occurred {n} time(s) {window}."]
    if report.observed_impact:
        actual.extend(report.observed_impact)
    expected = f"The affected operation completes without raising {report.exception}." if report.exception \
        else "The affected operation completes without logging this error. (Template; confirm the intended behaviour.)"

    code = []
    for c in report.code_context[:3]:
        if not c.get("file_path"):
            continue
        code.append({"file": c["file_path"], "lines": f"{c.get('start_line')}-{c.get('end_line')}", "target_line": c.get("target_line"),
                     "function": c.get("qualname"), "language": c.get("language") or "text", "status": c.get("status"),
                     "verified": bool(c.get("verified")), "note": c.get("note", ""),
                     "snippet": clean(_numbered(c))})

    ctx_before, ctx_after = list(group.context_before), list(group.context_after)
    labels = sorted({"log-analyzer", _clean_label(service), _clean_label(report.rule_id or "unclassified"),
                     f"severity-{report.severity.lower()}"} - {""})
    ai = {"enhanced": report.ai_enhanced, "provider": report.ai_provider, "baseline_hypothesis": report.baseline_probable_root_cause,
          "caveats": clean_list(report.ai_caveats), "warnings": report.ai_warnings,
          "supporting_evidence": [{"id": e["id"], "text": clean(e["text"])} for e in report.ai_supporting_evidence],
          "fallback_reason": report.ai_fallback_reason}
    return JiraTicket(
        group_id=group_id, title=clean(title), summary=clean(summary), severity=report.severity, priority=priority,
        priority_rationale=why, component=service, labels=labels, environment=env,
        error_message=clean(report.error_message), steps_to_reproduce=clean_list(report.reproduction_steps),
        expected_behavior=expected, actual_behavior=clean_list(actual),
        observed_evidence=[{"text": clean(e.text), "source": e.source} for e in report.observed_evidence],
        root_cause_hypothesis=clean(report.probable_root_cause), alternatives=clean_list(report.alternative_possibilities),
        confidence={"heuristic": report.confidence, "basis": report.confidence_basis, "ai": report.ai_confidence},
        impact_observed=clean_list(report.observed_impact), impact_inferred=report.inferred_impact, code=code,
        suggested_fix=clean_list(report.recommended_fix), investigation=clean_list(report.recommended_investigation),
        testing=list(TESTING.get(report.rule_id or "", ()) + GENERIC_TESTING),
        logs={"stack_trace": clean(report.stack_trace), "context_before": clean_list(ctx_before), "context_after": clean_list(ctx_after),
              "first_line": group.first_line, "last_line": group.last_line},
        ai=ai, review={"status": "DRAFT - not reviewed by a human", "checklist": list(REVIEW_CHECKLIST)},
        generated_at=datetime.now().isoformat(timespec="seconds"), tool_version=TOOL_VERSION, redactions=counts,
        disclaimer=report.disclaimer,
    )


def _numbered(ctx: dict) -> str:
    start = ctx.get("start_line") or 1
    lines = (ctx.get("snippet") or "").split("\n")
    return "\n".join(f"{start + i:>5}  {t}" for i, t in enumerate(lines))


PRIORITIES = ("Highest", "High", "Medium", "Low", "Lowest")


def apply_review(ticket: JiraTicket, *, title: str | None = None, summary: str | None = None, priority: str | None = None,
                 expected_behavior: str | None = None, steps_to_reproduce: list[str] | None = None,
                 suggested_fix: list[str] | None = None, reviewer: str = "", reviewed: bool = False,
                 redact_secrets: bool = True) -> JiraTicket:
    """Human review step: returns an edited copy. Edited text is redacted too; `reviewed=True` marks it as reviewed."""
    import copy
    t = copy.deepcopy(ticket)
    counts = dict(t.redactions)

    def clean(text: str) -> str:
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text).strip()
        if redact_secrets and text:
            r = redact(text)
            for k, v in r.counts.items():
                counts[k] = counts.get(k, 0) + v
            return r.text
        return text

    def lines(items):
        return [clean(x) for x in items if clean(x)]

    edited = []
    if title is not None and clean(title) and clean(title)[:255] != t.title:
        t.title, _ = clean(title)[:255], edited.append("title")
    if summary is not None and clean(summary) != t.summary:
        t.summary, _ = clean(summary), edited.append("summary")
    if priority is not None and priority != t.priority:
        if priority not in PRIORITIES:
            raise ValueError(f"priority must be one of {', '.join(PRIORITIES)}")
        t.priority, t.priority_rationale = priority, f"Set by reviewer (tool recommended {ticket.priority})."
        edited.append("priority")
    if expected_behavior is not None and clean(expected_behavior) != t.expected_behavior:
        t.expected_behavior, _ = clean(expected_behavior), edited.append("expected_behavior")
    if steps_to_reproduce is not None and lines(steps_to_reproduce) != t.steps_to_reproduce:
        t.steps_to_reproduce, _ = lines(steps_to_reproduce), edited.append("steps_to_reproduce")
    if suggested_fix is not None and lines(suggested_fix) != t.suggested_fix:
        t.suggested_fix, _ = lines(suggested_fix), edited.append("suggested_fix")
    t.redactions = counts
    t.extra = {**t.extra, "edited_fields": sorted(set(t.extra.get("edited_fields", [])) | set(edited))}
    if reviewed:
        who = clean(reviewer) or "a human reviewer"
        t.review = {**t.review, "status": f"REVIEWED by {who} on {datetime.now().strftime('%Y-%m-%d')}", "checked": True}
    return t


# ----------------------------------------------------------------------------- Jira REST
class JiraError(Exception):
    """Jira configuration or request problem. Messages never contain credentials."""


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    project_key: str
    api_token: str = field(default="", repr=False)
    email: str = ""
    issue_type: str = "Bug"
    auth: str = "basic"

    @classmethod
    def from_settings(cls, s) -> "JiraConfig":
        return cls(s.jira_base_url, s.jira_project_key, s.jira_api_token, s.jira_email, s.jira_issue_type, s.jira_auth)

    def validate(self) -> None:
        from urllib.parse import urlparse
        p = urlparse(self.base_url)
        if p.scheme not in ("http", "https") or not p.netloc or p.username or p.password:
            raise JiraError("JIRA_BASE_URL must be an http(s) URL without credentials")
        if p.scheme == "http" and (p.hostname or "").lower() not in ("localhost", "127.0.0.1", "::1"):
            raise JiraError("Refusing to send the Jira token over unencrypted HTTP to a non-local host. Use https://")
        if not self.project_key or not self.api_token:
            raise JiraError("Jira is not configured: JIRA_PROJECT_KEY and JIRA_API_TOKEN are required")
        if self.auth == "basic" and not self.email:
            raise JiraError("JIRA_EMAIL is required for basic auth (Jira Cloud)")
        if self.auth not in ("basic", "bearer"):
            raise JiraError("JIRA_AUTH must be 'basic' or 'bearer'")


def to_jira_payload(ticket: JiraTicket, project_key: str, issue_type: str = "Bug", include_priority: bool = True) -> dict:
    """Body for POST /rest/api/2/issue (description in Jira wiki markup). Built locally; sends nothing."""
    from .exporters import render_wiki
    fields = {"project": {"key": project_key}, "issuetype": {"name": issue_type}, "summary": ticket.title[:255],
              "description": render_wiki(ticket), "labels": ticket.labels}
    if include_priority:
        fields["priority"] = {"name": ticket.priority}
    return {"fields": fields}


def create_issue(ticket: JiraTicket, config: JiraConfig, *, confirm: bool = False, timeout: float = 20.0) -> dict:
    """Create a real Jira issue. Requires explicit config AND confirm=True. Returns {'key', 'url'}."""
    if not confirm:
        raise JiraError("Refusing to create a Jira issue without confirm=True")
    config.validate()
    base = config.base_url.rstrip("/")
    if config.auth == "basic":
        token = base64.b64encode(f"{config.email}:{config.api_token}".encode()).decode()
        auth = f"Basic {token}"
    else:
        auth = f"Bearer {config.api_token}"
    body = json.dumps(to_jira_payload(ticket, config.project_key, config.issue_type)).encode()
    req = urllib.request.Request(f"{base}/rest/api/2/issue", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json", "Authorization": auth})
    try:
        with open_no_redirect(req, timeout) as resp:
            data = json.loads(resp.read(200_000) or b"{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            errs = json.loads(exc.read(20_000) or b"{}")
            detail = "; ".join([*errs.get("errorMessages", []), *map(str, errs.get("errors", {}).values())])[:300]
        except ValueError:
            pass
        redirect = " (redirects are not followed)" if 300 <= exc.code < 400 else ""
        raise JiraError(f"Jira returned HTTP {exc.code}{redirect}" + (f": {detail}" if detail else "")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise JiraError(f"Cannot reach Jira: {type(getattr(exc, 'reason', exc)).__name__}") from None
    except ValueError:
        raise JiraError("Jira returned invalid JSON") from None
    key = data.get("key")
    if not key:
        raise JiraError("Jira response did not contain an issue key")
    return {"key": key, "url": f"{base}/browse/{key}"}
