"""Deterministic knowledge base: failure categories with hypotheses, checks and fixes.

These are hand-written heuristics, NOT model output. Every statement here is phrased as a hypothesis or
suggestion; the analyzer pairs them with measured evidence from the actual log and code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    pattern: re.Pattern
    hypothesis: str
    alternatives: tuple[str, ...]
    investigation: tuple[str, ...]
    fixes: tuple[str, ...]
    reproduction: tuple[str, ...]
    impact_hint: str
    base_confidence: float
    precursors: re.Pattern | None = None   # titles of earlier groups that would support this hypothesis
    symptom: bool = False                  # usually a downstream effect of another failure


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.I)


_RULES: tuple[Rule, ...] = (
    Rule(
        "db_pool_timeout", "Database connectivity / pool exhaustion",
        _rx(r"DatabaseConnectionTimeout|(connection|pool).{0,40}(timed? ?out|exhaust)|timed? ?out.{0,40}connection|"
            r"PoolTimeout|TooManyConnections|SQLTransientConnection|could not (get|acquire) .{0,20}connection"),
        "The service could not obtain a database connection before the timeout expired, most likely because the "
        "connection pool was saturated (demand above pool capacity or connections held too long) or the database was slow/unreachable.",
        ("The database server was slow, overloaded or briefly unavailable.",
         "A network problem between the application and the database.",
         "Connections leaked (not returned to the pool) by another code path.",
         "A burst of traffic or a slow query holding connections longer than usual."),
        ("Compare pool size and acquire timeout in the configuration with the concurrent requests seen in the failure window.",
         "Check database-side metrics (active connections, CPU, slow-query log) for the same time window.",
         "Look for code paths that hold a connection while doing slow work or fail to release it.",
         "Check whether earlier warnings (slow queries, high pool utilization) appear before the first failure."),
        ("Release connections promptly (context managers / finally blocks) and avoid holding one during slow work.",
         "Size the pool for peak concurrency, or add queueing/back-pressure so requests fail fast instead of piling up.",
         "Add a bounded retry with jitter for transient acquire timeouts, plus a circuit breaker.",
         "Add pool-utilization alerting so saturation is visible before requests fail."),
        ("Run the service with a small connection pool (use the pool size shown in the log message).",
         "Send more concurrent requests along the observed call path than the pool can serve.",
         "Wait for the acquire timeout shown in the log message.",
         "Confirm the same exception and HTTP 5xx responses appear."),
        "Requests that need the database fail after waiting for the full timeout, so users experience slow failures.",
        0.60, _rx(r"pool|slow (database|query|db)|utilization|latency|connection"),
    ),
    Rule(
        "db_saturation_warning", "Database saturation warning",
        _rx(r"pool utilization|slow (database|query|db) call|slow query|high (db|database) latency"),
        "The warning suggests the database layer was under pressure (slow calls or a nearly full connection pool); "
        "this class of warning often precedes connection timeouts.",
        ("Normal load variation without user impact.", "A single slow query rather than general saturation."),
        ("Check whether connection-timeout errors follow these warnings in the same window.",
         "Review the slowest queries and pool configuration for the affected service."),
        ("Investigate and optimize the slow queries.", "Raise pool capacity or add alerts on utilization thresholds."),
        ("Generate load against the affected endpoint until pool utilization approaches 100%.",),
        "May be an early signal of upcoming failures; no direct failure is shown by this group alone.",
        0.45,
    ),
    Rule(
        "network_connection", "Network / dependency connectivity",
        _rx(r"ConnectionRefused|connection refused|ECONNREFUSED|ConnectionReset|connection reset|UnknownHost|"
            r"No route to host|getaddrinfo|NameResolution|SocketException|BrokenPipe"),
        "The service could not reach a dependency (refused, reset or unresolved connection), which usually means the "
        "dependency was down, restarting, or blocked by network/DNS configuration.",
        ("The dependency was restarting or deploying.", "Firewall/security-group or DNS change.",
         "The client used a wrong host or port setting."),
        ("Check the dependency's health and restart history at the failure time.",
         "Verify host, port and DNS resolution from the application environment."),
        ("Add retries with backoff and a circuit breaker for the dependency.", "Validate dependency configuration at startup."),
        ("Stop or block the dependency, then call the affected code path.",),
        "Operations that need the dependency fail immediately.", 0.55,
    ),
    Rule(
        "generic_timeout", "Timeout",
        _rx(r"timed? ?out|deadline exceeded"),
        "An operation exceeded its time limit; the slow party may be the callee, the network or local resource contention.",
        ("A slow downstream service.", "Resource starvation (CPU, threads, connections) in the caller.",
         "A timeout value that is too low for normal latency."),
        ("Identify what the timed-out call was waiting for.", "Compare latency before and during the failure window."),
        ("Set explicit, justified timeouts and retry only idempotent operations.",
         "Add latency metrics around the failing call."),
        ("Slow down or block the callee, then call the affected code path.",),
        "Affected requests wait for the timeout and then fail.", 0.40,
    ),
    Rule(
        "auth_failure", "Authentication / authorization",
        _rx(r"Unauthorized|invalid token|token (expired|invalid)|authentication failed|\b401\b|\b403\b|Forbidden|"
            r"AccessDenied|PermissionDenied|permission denied|bad credentials"),
        "Requests were rejected because credentials or permissions were invalid; typical causes are expired or "
        "malformed tokens, clock skew, or clients without the required access.",
        ("A client sending stale or wrong tokens.", "Token-signing key rotation or clock skew.",
         "Probing or abusive traffic rather than a product defect."),
        ("Check whether failures cluster on a few users or IPs.", "Verify token lifetimes, signing keys and server clock sync."),
        ("Return clear 401/403 responses and rate-limit repeated failures.", "Monitor failure rates per client."),
        ("Call the endpoint with an expired or invalid token.",),
        "Rejected requests; usually limited to the affected clients.", 0.45,
    ),
    Rule(
        "missing_field", "Missing key / field in data",
        _rx(r"KeyError|NoSuchElement|missing (field|key|property)|required (field|key)"),
        "Code accessed a key or field that the incoming data did not contain, which usually means unvalidated input or "
        "a producer/consumer contract mismatch.",
        ("A client or upstream service omitted the field.", "A recent schema or API change.",
         "A code path that builds the object without populating the field."),
        ("Inspect the request payloads for the failing request IDs.", "Check recent changes to the producer of this data."),
        ("Validate required fields at the boundary and return a 4xx with a clear message instead of failing with a 5xx.",
         "Use explicit defaults only when the business rules allow them.", "Add a regression test using a payload without the field."),
        ("Call the failing code path with input that lacks the missing key.",),
        "Requests with such payloads fail with a server error.", 0.60,
    ),
    Rule(
        "null_reference", "Null / undefined reference",
        _rx(r"NullPointer|AttributeError|NoneType|TypeError.{0,60}(undefined|null|None)|Cannot read propert|undefined is not"),
        "Code used a value that was null/None/undefined, usually because an earlier step returned nothing or the data was incomplete.",
        ("An unexpected empty response from a dependency.", "A race or ordering problem initializing the object."),
        ("Find where the null value originates (return values, missing data, failed lookups).",),
        ("Add explicit null checks or guarantee non-null results at the source.", "Add a regression test for the empty case."),
        ("Call the failing path with input that makes the lookup return nothing.",),
        "Requests that hit the path fail.", 0.55,
    ),
    Rule(
        "out_of_memory", "Memory exhaustion",
        _rx(r"OutOfMemory|MemoryError|heap space|\bOOM\b|Cannot allocate memory"),
        "The process ran out of memory, commonly from unbounded data loading, a leak, or limits that are too small.",
        ("Traffic spike or a very large request.", "A memory leak that grew over time.", "Container memory limit set too low."),
        ("Check memory graphs and restarts around the failure.", "Look for unbounded collections or full-result loading."),
        ("Stream or paginate large data.", "Fix leaks found via profiling and set realistic limits."),
        ("Load an input larger than the configured memory limit.",),
        "The process may crash or be killed, affecting every request on that instance.", 0.55,
    ),
    Rule(
        "disk_space", "Disk / quota",
        _rx(r"No space left|disk full|ENOSPC|quota exceeded"),
        "A write failed because disk space or quota was exhausted.",
        ("Log or temp-file growth.", "A quota set too low for current usage."),
        ("Check disk usage and what grew recently.",), ("Rotate or clean files and alert on disk usage.",),
        ("Fill the target volume and call the writing code path.",), "Writes fail until space is freed.", 0.55,
    ),
    Rule(
        "deadlock", "Database lock / deadlock",
        _rx(r"deadlock|lock wait timeout"),
        "Concurrent transactions blocked each other, typically from inconsistent lock ordering or long transactions.",
        ("A long-running transaction holding locks.",), ("Review transaction scope and lock order in the failing queries.",),
        ("Keep transactions short and acquire locks in a consistent order; retry on deadlock.",),
        ("Run two transactions that update the same rows in opposite order.",), "Affected transactions are rolled back.", 0.55,
    ),
    Rule(
        "validation_error", "Input validation",
        _rx(r"ValueError|ValidationError|IllegalArgument|invalid (input|payload|argument|value)"),
        "The code rejected a value that did not meet its expectations; this may be bad client input or an upstream data problem.",
        ("A client bug sending malformed data.", "A missing validation layer at the API boundary."),
        ("Inspect the rejected values for the affected request IDs.",),
        ("Validate at the boundary and return 4xx responses; add tests for the rejected shapes.",),
        ("Call the code path with the rejected value.",), "Rejected requests.", 0.45,
    ),
    Rule(
        "file_missing", "Missing file / resource",
        _rx(r"FileNotFound|No such file|ENOENT|not found on disk"),
        "A required file or resource was missing at the expected path.",
        ("A deployment omitted the file.", "A wrong path or working-directory assumption."),
        ("Verify the path and deployment artifacts in the affected environment.",),
        ("Fail at startup if required files are missing and make paths configurable.",),
        ("Remove or rename the file and call the code path.",), "Operations needing the file fail.", 0.55,
    ),
    Rule(
        "health_readiness", "Instance health / readiness",
        _rx(r"readiness|liveness|health ?check failed|probe failed|marked unhealthy|unhealthy"),
        "A health probe failed, which normally reflects a failing dependency (for example the database) rather than a fault in "
        "the probe itself; the instance may have been taken out of rotation.",
        ("The probe itself is misconfigured or too strict.", "A genuine outage of the dependency named in the message."),
        ("Read which dependency the probe reports as down and check it for the same window.",
         "Compare the probe failure time with error groups that were active then."),
        ("Make probes check only what the instance truly needs and alert on repeated failures.",),
        ("Make the probed dependency unavailable and watch the probe.",),
        "The instance may stop receiving traffic, reducing capacity.", 0.45, symptom=True,
    ),
    Rule(
        "upstream_error", "Upstream / gateway error response",
        _rx(r"upstream|bad gateway|service unavailable|gateway time-?out|\b50[234]\b"),
        "The gateway reported a server error from an upstream service; this is normally a symptom of a failure further downstream.",
        ("The upstream was overloaded.", "A deployment or restart of the upstream."),
        ("Follow the shared request IDs into the upstream service's own error groups.",),
        ("Fix the root cause in the upstream; consider timeouts and fallbacks at the gateway.",),
        ("Cause the upstream to fail and call it through the gateway.",),
        "Clients receive 5xx responses.", 0.40, symptom=True,
    ),
)

_ordered = list(_RULES)  # deadlock text often contains "timeout": check it before the generic timeout rule
_dl = next(r for r in _ordered if r.id == "deadlock")
_ordered.remove(_dl)
_ordered.insert(next(i for i, r in enumerate(_ordered) if r.id == "generic_timeout"), _dl)
RULES: tuple[Rule, ...] = tuple(_ordered)

GENERIC = Rule(
    "generic", "Unclassified failure", _rx(r"."),
    "No built-in pattern matched this failure, so no specific cause is proposed. The evidence below is what the logs and code show.",
    ("Insufficient information to rank causes.",),
    ("Read the full stack trace and surrounding events.", "Reproduce the failing request and capture more detail."),
    ("Add targeted logging around the failing call, then re-analyze.",),
    ("Re-run the request path shown in the stack trace.",),
    "Unknown.", 0.25,
)


def match_rule(text: str, rules: tuple[Rule, ...] = RULES) -> Rule:
    for rule in rules:
        if rule.pattern.search(text):
            return rule
    return GENERIC
