"""Map stack frames and log messages to real source code, and say honestly how well each mapping was verified.

Statuses (only `verified_exact` sets verified=True):
  verified_exact   line text (or, without code text, the enclosing function name) matches the trace
  line_moved       the traced code text exists in the file, but at a different line (code changed since the log)
  function_only    file and function found, but the line does not match
  line_mismatch    file found, line exists, but the code text/function differ from the trace
  line_unverified  file and line exist; the trace carried nothing that could confirm them
  file_only        file found but the line is out of range and the function is missing
  ambiguous_file   several files match equally well
  symbol_search    file not found; a function with that name exists elsewhere
  message_match / exception_match / keyword_search   fallbacks when no stack trace can be mapped
  external / not_found
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from log_analyzer.extractor import Frame

from .models import CodeChunk, CodeContext, RetrievalResult, SourceFile
from .search import CodeIndex

_EXTERNAL = ("site-packages", "dist-packages", "node_modules", "/usr/lib/python", "/usr/local/lib/python",
             "<frozen", "<string>", "<stdin>", "<module>", "\\lib\\python", "/lib/python3", "/lib64/python")
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_NOISE_CALLS = {"if", "for", "while", "with", "return", "print", "len", "str", "int", "float", "dict", "list",
                "set", "tuple", "isinstance", "super", "range", "open", "catch", "switch", "function"}
STACK_STATUSES = ("verified_exact", "line_moved", "function_only", "line_mismatch", "line_unverified")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _short_func(function: str | None) -> str | None:
    if not function or function.startswith("<"):
        return None
    name = function.split(".")[-1].split("$")[-1]
    return None if not name or name.startswith("<") else name


def _parts(path: str) -> list[str]:
    p = path.replace("\\", "/")
    p = re.sub(r"^[A-Za-z]:", "", p)
    return [x for x in p.split("/") if x not in ("", ".", "..")]


def _overlap(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(reversed(a), reversed(b)):
        if x.lower() != y.lower():
            break
        n += 1
    return n


def _literal_fragment(normalized: str, min_len: int = 12) -> str | None:
    """Longest stable text fragment of a normalized log message (split at <N>/<HEX>/... placeholders)."""
    best = ""
    frags = re.split(r"<[A-Z]+>", normalized)
    for i, frag in enumerate(frags):
        if i > 0:                      # text right after a placeholder may start mid-word
            frag = re.sub(r"^[\w-]*", "", frag)
        if i < len(frags) - 1:         # text right before a placeholder may end mid-word (e.g. "ORD-")
            frag = re.sub(r"[\w-]*$", "", frag)
        frag = frag.strip()
        if len(frag) > len(best):
            best = frag
    return best if len(best) >= min_len else None


class CodeRetriever:
    def __init__(self, index: CodeIndex, context_lines: int = 10):
        self.index = index
        self.context_lines = context_lines

    # ------------------------------------------------------------ file resolution
    def _frame_parts(self, frame: Frame) -> list[str]:
        if frame.language == "java":
            cls = re.sub(r"\$.*$", "", ".".join(frame.function.split(".")[:-1]))
            if cls and "." in cls:
                return cls.split(".")[:-1] + [PurePosixPath(frame.file).name]
        return _parts(frame.file)

    def resolve_file(self, frame: Frame) -> tuple[str, SourceFile | None, list[str]]:
        """Returns (kind, file, candidates); kind is unique | ambiguous | external | none."""
        low = frame.file.replace("\\", "/").lower()
        if any(m.replace("\\", "/") in low for m in _EXTERNAL):
            return "external", None, []
        parts = self._frame_parts(frame)
        if not parts:
            return "none", None, []
        cands = self.index.by_basename.get(parts[-1].lower(), [])
        if not cands:
            return "none", None, []
        scored = [(_overlap(parts, _parts(c)), c) for c in cands]
        top_score = max(s for s, _ in scored)
        top = sorted(c for s, c in scored if s == top_score)
        if len(top) == 1:
            return "unique", self.index.files[top[0]], top
        fn = _short_func(frame.function)
        with_fn = [c for c in top if fn and self.index.functions_in_file(c, fn)]
        if len(with_fn) == 1:
            return "unique", self.index.files[with_fn[0]], top
        return "ambiguous", None, top

    # ------------------------------------------------------------ building contexts
    def _related(self, chunk: CodeChunk | None) -> list[dict]:
        if chunk is None:
            return []
        seen, out = set(), []
        for line in self.index.chunk_text(chunk):
            for name in _CALL.findall(line):
                if name in _NOISE_CALLS or name == chunk.name or name in seen:
                    continue
                seen.add(name)
                hits = [c for c in self.index.by_name.get(name.lower(), []) if c.kind == "function" and c.name == name]
                if 0 < len(hits) <= 3:
                    h = hits[0]
                    out.append({"name": h.qualname, "file": h.file, "start_line": h.start_line, "end_line": h.end_line})
            if len(out) >= 5:
                break
        return out[:5]

    def _build(self, sf: SourceFile, target: int, status: str, note: str, frame: Frame | None = None,
               verified: bool = False, verification: str | None = None, alternatives=None) -> CodeContext:
        idx, n = self.index, len(sf.lines)
        target = max(1, min(target, n)) if n else 1
        start, end = max(1, target - self.context_lines), min(n, target + self.context_lines)
        fn = idx.enclosing(sf.rel_path, target, "function")
        cls = idx.enclosing(sf.rel_path, target, "class")
        return CodeContext(
            status=status, verified=verified, note=note, file_path=sf.rel_path, language=sf.language,
            target_line=target, start_line=start, end_line=end, snippet=idx.get_lines(sf.rel_path, start, end),
            function=fn.name if fn else None, qualname=fn.qualname if fn else None,
            class_name=(fn.class_name if fn and fn.class_name else cls.name if cls else None),
            module=sf.module, function_range=(fn.start_line, fn.end_line) if fn else None,
            imports=[t for _, t in idx.imports.get(sf.rel_path, [])][:12], related_functions=self._related(fn),
            frame=frame.to_dict() if frame else None, verification=verification, alternatives=alternatives or [],
        )

    # ------------------------------------------------------------ frames
    def retrieve_for_frame(self, frame: Frame) -> CodeContext:
        kind, sf, cands = self.resolve_file(frame)
        if kind == "external":
            return CodeContext("external", False, f"{frame.file} is outside the project (library or runtime code).",
                               frame=frame.to_dict())
        if kind == "ambiguous":
            return CodeContext("ambiguous_file", False,
                               f"{len(cands)} files match '{frame.file}' equally; not choosing one.",
                               frame=frame.to_dict(), alternatives=cands)
        if sf is None:
            return self._symbol_fallback(frame)
        return self._at_line(sf, frame)

    def _at_line(self, sf: SourceFile, frame: Frame) -> CodeContext:
        idx, n, line = self.index, len(sf.lines), frame.line
        fn_name = _short_func(frame.function)
        line_ok = 1 <= line <= n
        enclosing = idx.enclosing(sf.rel_path, line, "function") if line_ok else None
        where = f"{sf.rel_path}:{line}"

        if frame.code:
            want = _norm(frame.code)
            if line_ok and _norm(sf.lines[line - 1]) == want:
                return self._build(sf, line, "verified_exact",
                                   f"Verified: line {line} of {sf.rel_path} matches the code shown in the stack trace.",
                                   frame, True, "code_text")
            for delta in range(1, 101):
                for cand in (line - delta, line + delta):
                    if 1 <= cand <= n and _norm(sf.lines[cand - 1]) == want:
                        return self._build(sf, cand, "line_moved",
                                           f"NOT verified at the logged line: the trace says {where}, but the same code "
                                           f"text is at line {cand}. The file changed since the log was written.", frame)
        elif line_ok and enclosing and fn_name and enclosing.name == fn_name:
            return self._build(sf, line, "verified_exact",
                               f"Verified by function name only: line {line} is inside {enclosing.qualname}(); "
                               "the trace carried no code text to compare.", frame, True, "function_name")

        same_named = idx.functions_in_file(sf.rel_path, fn_name) if fn_name else []
        if same_named:
            best = min(same_named, key=lambda c: abs(c.start_line - line))
            why = "the line text differs from the trace" if frame.code else "the line is not inside that function"
            return self._build(sf, best.start_line, "function_only",
                               f"NOT verified: {where} could not be confirmed ({why}); showing function "
                               f"{best.qualname}() from {sf.rel_path} instead.", frame)
        if line_ok:
            if frame.code:
                return self._build(sf, line, "line_mismatch",
                                   f"NOT verified: {where} exists but its text differs from the trace's code.", frame)
            if fn_name is None or enclosing is None:
                return self._build(sf, line, "line_unverified",
                                   f"NOT verified: {where} exists, but the trace has no code text or usable "
                                   "function name to confirm it.", frame)
            return self._build(sf, line, "line_mismatch",
                               f"NOT verified: {where} is inside {enclosing.qualname}(), not {fn_name}().", frame)
        return CodeContext("file_only", False,
                           f"File {sf.rel_path} was found but has {n} lines (trace says line {line}) and no function "
                           f"'{fn_name}'. No snippet shown.", file_path=sf.rel_path, language=sf.language,
                           module=sf.module, frame=frame.to_dict())

    def _symbol_fallback(self, frame: Frame) -> CodeContext:
        fn = _short_func(frame.function)
        hits = self.index.find_symbol(fn, kinds=("function",)) if fn else []
        if not hits:
            return CodeContext("not_found", False, f"No source file matching '{frame.file}' and no function "
                               f"'{fn}' in the repository." if fn else f"No source file matching '{frame.file}'.",
                               frame=frame.to_dict())
        parts = _parts(frame.file)
        hits.sort(key=lambda c: (-_overlap(parts, _parts(c.file)), c.file, c.start_line))
        best = hits[0]
        sf = self.index.files[best.file]
        alts = [f"{c.file}:{c.start_line} {c.qualname}" for c in hits[1:4]]
        return self._build(sf, best.start_line, "symbol_search",
                           f"NOT verified: '{frame.file}' is not in the repository. A function named {fn}() exists in "
                           f"{best.file}" + (f" (and {len(hits) - 1} more)." if len(hits) > 1 else "."),
                           frame, alternatives=alts)

    # ------------------------------------------------------------ message / exception / keyword fallbacks
    def search_message(self, normalized_message: str, limit: int = 3) -> list[CodeContext]:
        frag = _literal_fragment(normalized_message)
        if not frag:
            return []
        out = []
        for rel, sf in self.index.files.items():
            for i, text in enumerate(sf.lines, 1):
                if frag in text:
                    out.append(self._build(sf, i, "message_match",
                                           f"NOT verified: the log message text is found at {rel}:{i} (a logging "
                                           "statement or similar); it is not tied to a stack trace."))
                    if len(out) >= limit:
                        return out
        return out

    def search_exception(self, exc_type: str, limit: int = 3) -> list[CodeContext]:
        rx = re.compile(rf"\b(?:raise|throw\s+new|except|catch|class)\s*\(?\s*(?:[\w.]*\.)?{re.escape(exc_type)}\b")
        out = []
        for rel, sf in self.index.files.items():
            for i, text in enumerate(sf.lines, 1):
                if rx.search(text):
                    out.append(self._build(sf, i, "exception_match",
                                           f"NOT verified: {exc_type} is raised/caught/defined at {rel}:{i}; nothing "
                                           "links this line to the logged failure."))
                    if len(out) >= limit:
                        return out
        return out

    def search_keywords(self, query: str, limit: int = 3) -> list[CodeContext]:
        out = []
        for ch, score in self.index.search(query, k=limit * 3, min_terms=2):
            if ch.kind == "class" and ch.size > 60:
                continue
            sf = self.index.files[ch.file]
            out.append(self._build(sf, ch.start_line, "keyword_search",
                                   f"Low confidence keyword match (score {score:.1f}) for '{query[:60]}'; "
                                   "not linked to a stack trace."))
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------ groups
    def retrieve_for_group(self, group, max_contexts: int = 4) -> RetrievalResult:
        """Find code for an ErrorGroup: stack frames first, then symbol, message, exception and keyword search."""
        result = RetrievalResult(contexts=[], strategy="none")
        seen: set = set()
        frames = list(group.frames) + [f for f in group.frames_surfaced if f not in group.frames]
        for fr in frames:
            ctx = self.retrieve_for_frame(fr)
            if ctx.status == "external":
                result.external_frames.append(fr.to_dict())
                continue
            if ctx.status in ("not_found", "ambiguous_file", "file_only"):
                result.unresolved_frames.append(fr.to_dict())
                if ctx.status == "ambiguous_file":
                    result.notes.append(ctx.note)
                continue
            key = (ctx.file_path, ctx.qualname, ctx.target_line if ctx.qualname is None else None)
            if key in seen:
                continue
            seen.add(key)
            result.contexts.append(ctx)
            if len(result.contexts) >= max_contexts:
                break

        if frames and result.unresolved_frames and result.unresolved_frames[0] == frames[0].to_dict() and result.contexts:
            f0 = frames[0]
            result.notes.append(f"The innermost stack frame ({f0.file}:{f0.line} in {f0.function}) was not found in the repository; "
                                "showing the nearest caller that could be located.")
        if any(c.status in STACK_STATUSES for c in result.contexts):
            result.strategy = "stack_trace"
        elif result.contexts:
            result.strategy = "symbol"
        if result.strategy != "stack_trace":
            message = group.normalized_message or ""
            fallbacks = [("message", lambda: self.search_message(message)),
                         ("exception", lambda: self.search_exception(group.exception_type) if group.exception_type else []),
                         ("keyword", lambda: self.search_keywords(f"{group.exception_type or ''} {group.title}"))]
            for name, fn in fallbacks:
                if result.strategy == "symbol" and name != "message":
                    break
                hits = fn()
                if hits:
                    result.contexts.extend(hits[:max_contexts])
                    if result.strategy != "symbol":
                        result.strategy = name
                    break
        if not result.contexts:
            result.notes.append("No source code could be located for this group; the exact source location is not verified.")
        elif not result.verified_contexts:
            result.notes.append("The exact source location was not verified against the stack trace.")
        return result
