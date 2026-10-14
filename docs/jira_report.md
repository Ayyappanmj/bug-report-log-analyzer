# Jira-ready bug reports (Phase 8)

`reports/jira.py` builds a **draft ticket** from a finished analysis; `reports/exporters.py` renders it as Markdown, plain text,
JSON or Jira wiki markup (paste-ready for Jira's text editor). Nothing is filed automatically.

## Sections
Title, summary, severity, priority recommendation (with its reason), component, labels, environment, error message, steps to
reproduce (suggested, from the logged call path), expected and actual behaviour, root-cause analysis (**observed evidence** and a separate
**hypothesis** with alternatives and confidence), impact (observed vs inferred), relevant source code (marked VERIFIED / NOT verified),
suggested fix, investigation, testing recommendation, logs excerpt, AI details (only if a model was used), review checklist, disclaimer.

## Human review
Every ticket starts as `DRAFT - not reviewed by a human` with a checklist. Expected behaviour is a template; reproduction steps and fixes
are hypotheses. Priority follows a documented heuristic (CRITICAL -> Highest; ERROR with linked 5xx, a sustained burst or >=10 events -> High;
otherwise Medium/Low) that you should adapt to your team.

## Redaction
Secrets (keys, tokens, passwords, JWTs, URL credentials, private keys) and emails are masked in every field by default; counts are listed in the report.
Best-effort only: read the report before sharing it.

## Optional: create the issue in Jira
Only if you set `JIRA_*` values in `.env` **and** call `create_issue(ticket, config, confirm=True)` explicitly. Uses Jira REST API v2
(`POST /rest/api/2/issue`, description in wiki markup). `basic` auth = account email + API token (Jira Cloud); `bearer` = personal access token
(Server/Data Center). Priority names must exist in your Jira (Highest/High/Medium/Low are defaults). Tokens are never printed or included in errors.
This was tested only against a local fake server, not a real Jira instance.

```powershell
python scripts\analyze_cli.py --group G001 --export out
```
