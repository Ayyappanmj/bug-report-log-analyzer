# Source-code scanning and retrieval (Phase 5)

**Scanner** (`code_analyzer/scanner.py`): walks a local folder and only *reads* text. Skips excluded directories
(configurable), symlinks, binary files, files over 512 KB, minified/generated files and anything beyond 20,000 files.
A `.git` folder is never scanned, but branch/commit are read from its plain files (no `git` command, no credentials).

**Chunker**: Python is parsed with `ast` (functions, methods, classes, imports, decorators). JavaScript, TypeScript and Java use
declaration regexes plus brace matching, which is approximate. Unparseable files fall back to overlapping 50-line windows.

**Index/search**: symbol lookup and BM25 keyword search over chunks (camelCase and snake_case are split, names and paths weigh more).
No embeddings yet (planned as optional).

**Retrieval** (`code_analyzer/retriever.py`) maps each stack frame to a file, tolerating different path styles
(`/app/src/x.py`, `C:\app\src\x.py`, `com.acme.Db` -> `com/acme/Db.java`). Result statuses:

| status | meaning | verified |
|---|---|---|
| verified_exact | line text matches the trace (or, with no code text, the enclosing function name matches) | yes |
| line_moved | trace's code text exists at another line: the file changed since the log | no |
| function_only / line_mismatch / line_unverified / file_only | file found, but the line could not be confirmed | no |
| ambiguous_file | several files match equally; none is chosen | no |
| symbol_search | file missing, a function with that name exists elsewhere | no |
| message_match / exception_match / keyword_search | no usable trace; located by message text, exception name, or keywords | no |

Group retrieval order: stack frames (raise site first) -> symbol -> message text -> exception name -> keywords.
Snippets are real file lines; nothing is generated. Anything not marked verified must be presented as unverified.
