# Supported log formats (Phase 3)

| Parser | Example |
|---|---|
| bracketed | `2026-09-30 10:22:14,123 ERROR [PaymentService] [Thread-7] [req=abc123] message` |
| generic | `2026-09-30T10:22:14Z WARNING: text`, `... [ERROR] Svc: text`, `... ERROR PaymentService` + exception on next line |
| json | one JSON object per line, or a `.json` file holding an array. Keys such as `ts/time/timestamp`, `level/severity`, `msg/message`, `service`, `request_id/correlation_id`, `status`, `stack` |

- Continuation lines (indented lines, `Traceback ...`, `Caused by:`, exception lines) are attached to the previous event as its stack trace.
- Lines that fit nothing are counted as `unparsed_lines` (first 20 kept as samples), never silently dropped.
- Timezone-aware timestamps are converted to UTC; naive ones are kept as written.
- Encodings: UTF-8 (with/without BOM) and UTF-16 with BOM (PowerShell 5 `>` redirection); invalid bytes are replaced.
- Safety: lines over 20,000 characters are truncated and counted; each event keeps at most 500 continuation lines.
- Not supported yet: syslog, Apache/Nginx combined format, multi-line JSON objects, timestamps without a year.
