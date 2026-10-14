# Case study: Bug Report & Log Analyzer Agent

Fill the bracketed items from your own benchmark and timing results. Delete any sentence you cannot back with evidence.

## Problem
Triaging a production error means reading logs, finding the code, and writing a ticket by hand. The slow part is not typing; it is separating what the logs *show* from what you *guess*.

## Goal and constraints
Build a genuinely working tool that is free to run, works without a paid API, never invents code or metrics, and could be shown to a recruiter honestly.

## Design decisions
- **Deterministic first, LLM optional.** Parsing, grouping, code retrieval and the evidence list are ordinary code. A model can only rewrite the hypothesis, must cite evidence ids, and any bad output falls back to the rule-based report.
- **Evidence and inference are different fields everywhere.** A test forbids hedging words in the evidence section.
- **Verification is explicit.** A snippet is "verified" only if the stack-trace line text matches the file; otherwise the report says why it is not (line moved, function only, symbol match, keyword match).
- **Stream, group, discard.** Events are grouped as they are parsed instead of being stored, and the number of groups is capped.
- **Human review before filing.** Reports start as drafts; creating a Jira issue needs configuration, a confirmation and a reviewed flag.

## What testing and review found
These are real defects found by the project's own tests and security pass, and fixed:
- A secret-redaction regex was quadratic: a single 20,000-character line took about 19 seconds. Patterns are now bounded.
- Deeply nested JSON crashed the parser with `RecursionError`.
- One failing incident analysis aborted the entire run. Failures are now contained.
- `urllib` forwards an Authorization header to a redirect target on another host; redirects are no longer followed.
- Log text such as `![x](https://…)` would render as a remote image in the UI and in exported Markdown; untrusted text is now escaped.
- Holding every parsed event in memory made large logs expensive; events are now streamed.
A mutation check (deliberately breaking behaviours) initially let 3 of 15 mutants survive, which exposed weak tests that were then strengthened.

## Results (fill from your runs)
| Item | Value | Where it comes from |
|---|---|---|
| Largest log analyzed | [X MB] | `benchmarks\results\latest.md` |
| Time for that log | [Z s] on [your CPU/RAM] | same file |
| Peak memory | [M MB] | same file |
| Scenarios passing every ground-truth check | [n of 4] | same file |
| Manual vs agent-assisted time | [median manual] vs [median assisted] on [n trials, k scenarios] | `python scripts\compare_workflows.py` |

State the caveats next to the numbers: synthetic logs, scenarios written by the author, a single participant.

## What I would do next
Embedding-based retrieval, more log formats, correlating incidents with recent commits, and running it against logs from a real project (with permission).

## What I learned
[Write 3–4 honest sentences in your own words: for example, how fuzzing and a mutation check changed how you test, and why separating evidence from inference changed the design.]
