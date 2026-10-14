"""Split source files into function/class chunks and extract imports.

Python uses `ast`. JavaScript/TypeScript/Java use declaration regexes plus brace matching (approximate).
Files that cannot be parsed fall back to overlapping line windows.
"""
from __future__ import annotations

import ast
import re

from .models import CodeChunk, SourceFile

_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "new", "else", "throw", "function", "do",
             "try", "finally", "synchronized", "super", "this", "await", "typeof", "delete"}
_STR = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`')

_JS_CLASS = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)")
_JS_FUNC = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*\(")
_JS_ARROW = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s*)?"
    r"(?:function\b|\([^)]*\)\s*(?::\s*[^=]+)?=>|\w+\s*=>)")
_JS_METHOD = re.compile(
    r"^\s+(?:(?:public|private|protected|static|async|get|set|readonly)\s+)*(\w+)\s*(?:<[^>]*>)?\s*\([^)]*\)"
    r"\s*(?::\s*[\w<>\[\]|,.\s]+)?\s*\{")
_JAVA_CLASS = re.compile(
    r"^\s*(?:(?:public|private|protected|abstract|final|static)\s+)*(?:class|interface|enum|record)\s+(\w+)")
_JAVA_METHOD = re.compile(
    r"^\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:(?:public|private|protected|static|final|abstract|synchronized|native|default)\s+)*"
    r"(?:<[^>]+>\s*)?([\w<>\[\],.?]+)\s+(\w+)\s*\([^;]*\)\s*(?:throws\s+[\w.,\s]+)?\s*\{?[^;]*$")


def _clean(lines: list[str]) -> list[str]:
    """Blank out comments and string literals so braces inside them are not counted."""
    out, in_block = [], False
    for line in lines:
        s, res = line, ""
        while s:
            if in_block:
                k = s.find("*/")
                if k < 0:
                    s = ""
                    break
                s, in_block = s[k + 2:], False
                continue
            k, k2 = s.find("/*"), s.find("//")
            if k >= 0 and (k2 < 0 or k < k2):
                res += s[:k]
                s, in_block = s[k + 2:], True
                continue
            res, s = res + s, ""
        out.append(_STR.sub('""', res).split("//")[0])
    return out


def _block_end(cleaned: list[str], start: int, max_span: int = 3000) -> int:
    """1-based end line of the brace block that starts at 0-based index `start`."""
    depth, started = 0, False
    for j in range(start, min(len(cleaned), start + max_span)):
        line = cleaned[j]
        if "{" in line or "}" in line:
            if "}" not in line:
                depth += line.count("{")
                started = True
            else:
                for ch in line:
                    if ch == "{":
                        depth, started = depth + 1, True
                    elif ch == "}":
                        depth -= 1
            if started and depth <= 0:
                return j + 1
        if not started and j - start >= 4:
            return start + 1
    return min(len(cleaned), start + max_span)


def _uncovered_chunks(sf: SourceFile, chunks: list[CodeChunk], window: int = 80) -> list[CodeChunk]:
    n = len(sf.lines)
    covered = [False] * (n + 2)
    for c in chunks:
        for i in range(c.start_line, min(c.end_line, n) + 1):
            covered[i] = True
    out, i = [], 1
    while i <= n:
        if covered[i]:
            i += 1
            continue
        j = i
        while j + 1 <= n and not covered[j + 1]:
            j += 1
        nonblank = sum(1 for k in range(i, j + 1) if sf.lines[k - 1].strip())
        if nonblank >= 3:
            for s in range(i, j + 1, window):
                out.append(CodeChunk(sf.rel_path, "module", "<module>", "<module>", s, min(s + window - 1, j),
                                     sf.language))
        i = j + 1
    return out


def _windows(sf: SourceFile, size: int = 50, overlap: int = 10) -> list[CodeChunk]:
    n, out, s = len(sf.lines), [], 1
    while s <= n:
        e = min(s + size - 1, n)
        out.append(CodeChunk(sf.rel_path, "block", f"lines {s}-{e}", f"lines {s}-{e}", s, e, sf.language))
        if e == n:
            break
        s = e - overlap + 1
    return out


# ---------------- Python ----------------
def _py_imports(tree: ast.Module, lines: list[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    def walk(body):
        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                found.append((node.lineno, " ".join(l.strip() for l in lines[node.lineno - 1:node.end_lineno])))
            elif isinstance(node, (ast.If, ast.Try)):
                walk(node.body)
                walk(getattr(node, "orelse", []))
                for h in getattr(node, "handlers", []):
                    walk(h.body)
    walk(tree.body)
    return found


def _chunk_python(sf: SourceFile) -> tuple[list[CodeChunk], list[tuple[int, str]]] | None:
    try:
        tree = ast.parse("\n".join(sf.lines))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    chunks: list[CodeChunk] = []

    def visit(node, stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                is_class = isinstance(child, ast.ClassDef)
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                qual = ".".join([s[1] for s in stack] + [child.name])
                cls = next((s[1] for s in reversed(stack) if s[0] == "class"), None)
                chunks.append(CodeChunk(sf.rel_path, "class" if is_class else "function", child.name, qual,
                                        start, child.end_lineno or child.lineno, sf.language,
                                        None if is_class else cls))
                visit(child, stack + [("class" if is_class else "function", child.name)])
            elif isinstance(child, (ast.stmt, ast.ExceptHandler)):
                visit(child, stack)
    visit(tree, [])
    return chunks, _py_imports(tree, sf.lines)


# ---------------- JS / TS / Java ----------------
def _chunk_braced(sf: SourceFile) -> list[CodeChunk]:
    cleaned = _clean(sf.lines)
    java = sf.language == "java"
    class_re = _JAVA_CLASS if java else _JS_CLASS
    raw: list[tuple[str, str, int, int]] = []  # kind, name, start, end
    for i, line in enumerate(cleaned):
        if not line.strip():
            continue
        m = class_re.match(line)
        if m:
            raw.append(("class", m.group(1), i + 1, _block_end(cleaned, i)))
            continue
        if java:
            m = _JAVA_METHOD.match(line)
            if m and m.group(1) not in _KEYWORDS and m.group(2) not in _KEYWORDS and not line.rstrip().endswith(";"):
                raw.append(("function", m.group(2), i + 1, _block_end(cleaned, i)))
            continue
        m = _JS_FUNC.match(line) or _JS_ARROW.match(line)
        if m:
            raw.append(("function", m.group(1), i + 1, _block_end(cleaned, i)))
            continue
        m = _JS_METHOD.match(line)
        if m and m.group(1) not in _KEYWORDS:
            raw.append(("method?", m.group(1), i + 1, _block_end(cleaned, i)))
    classes = [(s, e) for k, _, s, e in raw if k == "class"]
    items = []
    for k, name, s, e in raw:
        if k == "method?":  # JS method-like lines only count inside a class body
            if not any(cs < s <= ce for cs, ce in classes):
                continue
            k = "function"
        items.append((k, name, s, e))
    items.sort(key=lambda t: (t[2], -t[3]))
    chunks: list[CodeChunk] = []
    stack: list[CodeChunk] = []
    for k, name, s, e in items:
        while stack and not (stack[-1].start_line <= s <= stack[-1].end_line):
            stack.pop()
        qual = ".".join([c.name for c in stack] + [name])
        cls = next((c.name for c in reversed(stack) if c.kind == "class"), None)
        ch = CodeChunk(sf.rel_path, k, name, qual, s, e, sf.language, None if k == "class" else cls)
        chunks.append(ch)
        if e > s:
            stack.append(ch)
    return chunks


def _braced_imports(sf: SourceFile) -> list[tuple[int, str]]:
    out = []
    for i, line in enumerate(sf.lines[:400], 1):
        s = line.strip()
        if s.startswith("import ") or "require(" in s and s.startswith(("const ", "let ", "var ")):
            out.append((i, s))
    return out


def chunk_file(sf: SourceFile) -> tuple[list[CodeChunk], list[tuple[int, str]]]:
    """Return (chunks, imports) for a source file."""
    if sf.language == "python":
        res = _chunk_python(sf)
        if res is None:
            return _windows(sf), []
        chunks, imports = res
    else:
        chunks, imports = _chunk_braced(sf), _braced_imports(sf)
        if not chunks and len(sf.lines) > 80:
            return _windows(sf), imports
    chunks = chunks + _uncovered_chunks(sf, chunks)
    return chunks, imports
