# Security

This tool reads **untrusted text** (logs and source code), can call an optional LLM, and can optionally create Jira issues.
This page lists what it defends against, how that is tested, and what is **not** covered. Nothing here is a guarantee: it is a
single-developer project that has not had an independent security review.

## Reporting a problem
Open a private security advisory on the GitHub repository (Security tab), or contact the maintainer directly. Please do not post exploit details in a public issue.
(Replace this paragraph with your real contact before publishing.)

## Deployment modes
| Mode | Use | Local paths | History | Jira | LLM | Upload limit |
|---|---|---|---|---|---|---|
| Local (default) | One user on their own machine | allowed, except roots and credential folders | on | optional | optional | 50 MB |
| `ALLOWED_ROOTS=...` | Local, restricted to chosen folders | only inside those folders | on | optional | optional | 50 MB |
| `PUBLIC_DEMO=true` | A shared/hosted demo | **none** (uploads and the bundled demo only) | **off** | **off** | **off** | set `MAX_LOG_SIZE_MB=10` |

The app has **no login and no rate limiting**. Streamlit gives each browser session its own state, but anything shared (the history file, the server's disk) is shared by every visitor, which is why public mode switches those off.
Do not host the local mode on a network. Put a real authenticating proxy in front of any shared deployment.

## Threat model
| Threat | Defense | Test |
|---|---|---|
| Huge or hostile upload (size, giant line, endless stack trace, deeply nested JSON, regex-slow text) | size limits, 20,000-char line cap, 500-line trace cap, bounded regexes, nested JSON rejected | `test_robustness.py`, `test_large_files.py` |
| Memory exhaustion by millions of distinct messages | group cap (20,000, extra problems folded into one counted group); events are streamed, not stored | `test_group_count_is_capped_so_unique_messages_cannot_exhaust_memory`, `test_pipeline_streams_events_instead_of_holding_them` |
| Terminal escape sequences, control characters, bidirectional-override text in a log | stripped while reading | `test_ansi_escape_sequences_cannot_reach_reports_or_terminals`, `test_control_characters_and_bidi_overrides_are_stripped` |
| Log text rendered as live Markdown/HTML/Jira markup (remote images, phishing links, macros) | untrusted text is escaped in the UI and in Markdown/wiki exports; raw log text goes through `st.text` or code blocks | `test_exports_do_not_contain_live_links_images_or_html`, `test_ui_text_is_escaped_before_rendering` |
| Path traversal / reading files named by a log | stack-frame paths are only matched against the scanned index and never opened | `test_retriever_never_opens_paths_taken_from_a_log` |
| Reading arbitrary server files through the path boxes | path policy (no filesystem roots, no `.ssh/.aws/...`, optional allowed roots, none in public mode) | `test_path_policy_blocks_roots_sensitive_dirs_and_escapes`, `test_public_mode_blocks_every_local_path_but_not_the_bundled_demo` |
| Symlinks or junctions leading out of the project | symlinks are skipped; every file's real path must stay inside the project | `test_symlinks_are_not_followed`, `test_scanner_refuses_files_whose_real_path_leaves_the_project` |
| Executing uploaded code or log-supplied commands | none of it is imported, executed or passed to a shell; a test forbids `eval/exec/subprocess/pickle` in application code | `test_application_code_has_no_dynamic_execution_or_unsafe_deserialization` |
| Secrets in logs reaching an LLM, a ticket, an export or the history file | best-effort redaction (cloud keys, tokens, JWTs, private keys, URL credentials, passwords, Luhn-valid card numbers, emails) applied to prompts, tickets and stored history | `test_every_secret_family_is_redacted`, `test_card_numbers_need_to_pass_the_luhn_check_and_look_like_cards` |
| Prompt injection through log or code text | content is fenced as untrusted data, the model may only rewrite the hypothesis, must cite real evidence ids, output is validated, nothing it returns is executed | `test_enhancer.py`, `test_prompts.py` |
| Credentials leaking to another host or over plain HTTP | redirects are never followed; API keys and Jira tokens refuse unencrypted HTTP to non-local hosts; keys are not in `repr`, errors or logs | `test_api_key_is_never_forwarded_to_a_redirect_target`, `test_jira_token_is_never_forwarded_to_a_redirect_target`, `test_credentials_refuse_plain_http_to_remote_hosts` |
| SSRF through the settings page | hosts, keys and modes cannot be overridden from the UI (whitelist of 5 harmless keys) | `test_session_overrides_cannot_change_hosts_keys_or_modes` |
| SQL injection / history disclosure | parameterized queries, compressed redacted payloads, owner-only file permissions (POSIX), history disabled in public mode | `test_storage.py`, `test_history_database_is_owner_only` |
| Accidentally filing a ticket | needs Jira credentials, a confirm checkbox and "reviewed"; API requires `confirm=True` | `test_create_issue_requires_confirmation_and_complete_config` |
| Committing secrets | `.env` is ignored; the project is scanned with the project's own redaction engine in a test; gitleaks, bandit and pip-audit are configured | `test_repository_contains_no_secrets`, `.github/workflows/tests.yml` |

## Secrets handling
Configuration comes from environment variables or `.env` (never committed). Settings objects hide keys in their representation, the UI shows only "set / not set", and error messages never include tokens.

## Residual risks (read these)
- **Redaction is best-effort.** Unusual secret formats, secrets split across lines, and personal data other than emails and card numbers are not caught. Review reports before sharing them. Do not use an online LLM with confidential logs.
- **LLM output is untrusted.** Validation checks format and evidence ids, not truth. A model can still write a wrong hypothesis (it is labeled as one).
- **Raw URLs in text may be auto-linked** by some Markdown viewers (they need a click; images and HTML are neutralized).
- **No authentication, quotas or audit log.** See deployment modes.
- **Windows-specific code** (peak-memory and RAM readers, junction handling) was written without a Windows test machine.
- **Dependencies** are pinned only by range. CI runs `pip-audit`, but that workflow has not been run in the build environment.
- Scanning a very large folder is bounded (20,000 files, 512 KB each) but still reads those files into memory.

## Before publishing a hosted demo
Set `PUBLIC_DEMO=true`, `MAX_LOG_SIZE_MB=10`, run the container as the provided non-root user, publish only through an HTTPS proxy with authentication or rate limiting, and use the synthetic demo data only.
