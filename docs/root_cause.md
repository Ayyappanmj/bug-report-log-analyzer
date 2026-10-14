# Root-cause analysis (Phase 6, deterministic mode)

`agent/orchestrator.py` runs: parse -> group -> index code -> retrieve code per group -> `RootCauseAnalyzer` report.
No LLM is involved yet (Phase 7 adds an optional one on top of the same evidence).

## Observed evidence vs inference
- **Observed evidence** (`observed_evidence`): only measurements, each with a source (log lines, group ids, file:line):
  counts, first/last seen, timing pattern, services, exception type, call path, shared request IDs, earlier warnings,
  overlapping incidents, and the real source line with its verification status. Tests forbid hedging words here.
- **Inference** (`probable_root_cause`, `alternative_possibilities`, `inferred_impact`, fixes, reproduction steps):
  hypotheses from a hand-written rule library (`agent/rules.py`). They are suggestions to verify, never confirmed facts.

## Pattern rules
13 categories (database pool/timeouts, saturation warnings, network, generic timeout, deadlock, auth, missing key,
null reference, out-of-memory, disk, validation, missing file, health/readiness, upstream error) plus an "unclassified" fallback.
"Symptom" rules (upstream error, readiness) point to a linked group's id when shared request IDs exist.

## Confidence
A heuristic score between 0.1 and 0.85, **not a calibrated probability**. Components are listed in `confidence_basis`:
rule base (0.25-0.60) + 0.10 verified source location + 0.05 stack trace + 0.10 matching earlier warnings
+ 0.05 linked group - 0.10 if no code found; capped at 0.85.

## Timing pattern
From per-minute counts: single occurrence, sustained burst (>=10 events, >=80% of minutes active), sporadic (<50% active), intermittent.

## Limits
- Rules cover common patterns only; unfamiliar failures get the "unclassified" report.
- Impact is limited to what the log records (request IDs, HTTP status). Real user impact is not measured.
- The analysis never executes uploaded code or runs commands.
