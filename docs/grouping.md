# Error extraction and grouping (Phase 4)

**Problem events**: level WARN/ERROR/CRITICAL, or any event with an exception trace or HTTP 5xx status.

**Grouping keys**
- Events with an exception trace: `root exception type + normalized root message + raise site (file:function)`.
  For Python chained tracebacks the root is the first exception raised; for Java/JS "Caused by:" traces it is the last cause.
  Line numbers are not part of the key (they shift between deployments).
- Other events: `level + service + HTTP status + normalized message`.
- Normalization masks numbers, hex ids, UUIDs, IPs, emails and timestamps.
- A second pass merges near-identical messages (difflib ratio >= 0.9) within the same exception/site or service; skipped above 2000 groups.

**Severity** comes only from log levels: CRITICAL -> CRITICAL, ERROR -> HIGH, WARN -> MEDIUM. A group takes its highest level.

**Ranking** is a heuristic, not a measurement: `weight * (1 + log10(count))^2 (+5 if a stack trace was seen)`, weights 40/10/3/1.

**Related groups**: two groups are linked when they share at least 2 request ids and at least half of the smaller group's ids.
A link is evidence of co-occurrence, not proof of causation.

**Recurring** means the group occurred at least twice.

Each group also keeps first/last seen, per-minute counts, services, HTTP statuses, sample request ids, up to 3 sample events,
context lines before its first occurrence and after it.
