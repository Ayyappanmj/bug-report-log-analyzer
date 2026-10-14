# Architecture

## Components
```mermaid
flowchart TD
    UI["Streamlit UI<br/>app.py and ui/"] --> AC["Agent controller<br/>agent/orchestrator.py"]
    CLI["Command-line scripts<br/>scripts/"] --> AC
    AC --> LA["Log analyzer<br/>parse, normalize, extract"]
    AC --> CS["Code scanner<br/>scan, chunk, index"]
    LA --> EG["Error groups<br/>rank and link"]
    CS --> CR["Code retrieval<br/>verify against the stack trace"]
    EG --> RC["Root-cause analyzer<br/>evidence plus hypothesis"]
    CR --> RC
    RC -. optional .-> LLM["LLM provider<br/>Ollama or API"]
    RC --> BR["Bug report builder"]
    BR --> HR["Human review"]
    HR --> EX["Export<br/>MD, TXT, JSON, Jira wiki"]
    HR -. explicit confirm .-> JI["Jira REST API"]
    AC --> DB[("SQLite history<br/>redacted")]
```

## Data flow of one analysis
```mermaid
sequenceDiagram
    participant U as User
    participant P as AnalysisPipeline
    participant G as ErrorGrouper
    participant R as CodeRetriever
    participant A as RootCauseAnalyzer
    participant M as LLMEnhancer (optional)
    U->>P: log file or upload, project folder
    loop each log line, streamed
        P->>G: parsed event
    end
    G-->>P: ranked groups and summary
    P->>P: scan and index the project
    loop top groups
        P->>R: retrieve code for the group
        R-->>P: snippets with verified or not
        P->>A: group, snippets, all groups
        A-->>P: report (evidence, hypothesis)
        P->>M: report (redacted evidence only)
        M-->>P: refined hypothesis or fallback
    end
    P-->>U: dashboard numbers, reports, ticket drafts
```

## Trust boundaries
```mermaid
flowchart LR
    subgraph Untrusted["Untrusted input"]
        LOG["Log text"]
        SRC["Source code"]
        MODEL["Model output"]
    end
    subgraph Local["This program, on your machine"]
        SAN["Sanitize and bound<br/>strip escapes, cap sizes"]
        CORE["Parse, group, retrieve, analyze<br/>no execution"]
        RED["Redact secrets"]
        ESC["Escape for Markdown and wiki"]
    end
    LOG --> SAN --> CORE
    SRC --> CORE
    CORE --> RED --> MODEL
    MODEL --> ESC
    CORE --> ESC
    ESC --> OUT["UI, exports, Jira draft"]
```

## Principles
- Never send the whole log to a model: parse, group, rank, then send only redacted evidence.
- Observed evidence and inference are separate fields everywhere (report, ticket, UI).
- Works with no LLM; model output is validated and falls back to the deterministic report.
- Uploaded code and logs are only read, never executed; paths named in a log are never opened.
- Display logic is in plain functions (`ui/viewmodels.py`), so it is unit-tested without a browser.

## Main modules
| Module | Responsibility |
|---|---|
| `agent/orchestrator.py` | runs the pipeline, times each stage, contains per-group failures |
| `agent/root_cause_agent.py`, `agent/rules.py` | evidence builders, hypothesis rules, confidence score |
| `log_analyzer/` | `ingest` (safe reading), `parser`, `normalizer`, `extractor` (exception chains and frames), `grouper` |
| `code_analyzer/` | `scanner`, `chunker`, `search` (BM25), `retriever` (verification statuses) |
| `ai/` | providers, `prompts`, `validation`, `redaction`, `enhancer` |
| `reports/` | `jira` (ticket, review, optional REST), `exporters`, `sanitize` |
| `storage/database.py` | redacted run history |
| `ui/` | Streamlit pages over a plain-dict view of a run |
