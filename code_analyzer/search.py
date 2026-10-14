"""Code index: chunks, symbol lookup and BM25 keyword search (pure Python, no external services)."""
from __future__ import annotations

import math
import re
import time
from collections import Counter, defaultdict
from pathlib import PurePosixPath

from .chunker import chunk_file
from .models import CodeChunk, RepoScan, SourceFile
from .scanner import scan_repository

_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_STOP = {"the", "and", "for", "with", "while", "after", "from", "that", "this", "was", "are", "not", "has",
         "have", "had", "been", "into", "when", "which", "its", "our", "out", "all", "but", "can", "did",
         "does", "self", "none", "true", "false", "null", "def", "var", "let", "new", "return"}


def tokenize(text: str) -> list[str]:
    """Lower-case identifier tokens; camelCase and snake_case identifiers also yield their parts."""
    tokens: list[str] = []
    for ident in _ID.findall(text):
        parts = [p.lower() for p in _CAMEL.findall(ident.replace("_", " "))]
        if len(parts) > 1:
            tokens.extend(parts)
        tokens.append(ident.lower())
    return [t for t in tokens if len(t) >= 2 and t not in _STOP]


class CodeIndex:
    def __init__(self, scan: RepoScan, k1: float = 1.5, b: float = 0.75):
        t0 = time.perf_counter()
        self.scan, self.files = scan, scan.files
        self.k1, self.b = k1, b
        self.chunks: list[CodeChunk] = []
        self.imports: dict[str, list[tuple[int, str]]] = {}
        self.by_file: dict[str, list[CodeChunk]] = {}
        self.by_name: dict[str, list[CodeChunk]] = defaultdict(list)
        self.by_basename: dict[str, list[str]] = defaultdict(list)
        self._postings: dict[str, dict[int, int]] = defaultdict(dict)
        self._doc_len: list[int] = []
        for rel, sf in self.files.items():
            self.by_basename[PurePosixPath(rel).name.lower()].append(rel)
            chunks, imports = chunk_file(sf)
            self.imports[rel] = imports
            self.by_file[rel] = chunks
            for ch in chunks:
                ch.id = len(self.chunks)
                self.chunks.append(ch)
                if ch.kind in ("function", "class"):
                    self.by_name[ch.name.lower()].append(ch)
                self._index_chunk(ch, sf)
        self._avgdl = (sum(self._doc_len) / len(self._doc_len)) if self._doc_len else 0.0
        self.build_seconds = time.perf_counter() - t0

    @classmethod
    def build(cls, root, **scan_kwargs) -> "CodeIndex":
        return cls(scan_repository(root, **scan_kwargs))

    def _index_chunk(self, ch: CodeChunk, sf: SourceFile) -> None:
        body = "\n".join(sf.lines[ch.start_line - 1:ch.end_line])
        counts = Counter(tokenize(body))
        for tok in tokenize(f"{ch.qualname} {ch.file}") * 3:  # names and paths weigh more
            counts[tok] += 1
        for tok, tf in counts.items():
            self._postings[tok][ch.id] = tf
        self._doc_len.append(sum(counts.values()))

    # ---- lookups ----
    def chunk_text(self, ch: CodeChunk) -> list[str]:
        return self.files[ch.file].lines[ch.start_line - 1:ch.end_line]

    def get_lines(self, path: str, start: int, end: int) -> list[tuple[int, str]]:
        lines = self.files[path].lines
        start, end = max(1, start), min(len(lines), end)
        return [(i, lines[i - 1]) for i in range(start, end + 1)]

    def enclosing(self, path: str, line: int, kind: str = "function") -> CodeChunk | None:
        """Innermost chunk of `kind` containing `line`."""
        best = None
        for ch in self.by_file.get(path, []):
            if ch.kind == kind and ch.start_line <= line <= ch.end_line:
                if best is None or ch.size < best.size:
                    best = ch
        return best

    def functions_in_file(self, path: str, name: str) -> list[CodeChunk]:
        return [c for c in self.by_file.get(path, []) if c.kind == "function" and c.name == name]

    def find_symbol(self, name: str, kinds=("function", "class")) -> list[CodeChunk]:
        return [c for c in self.by_name.get(name.lower(), []) if c.kind in kinds and c.name == name] or \
               [c for c in self.by_name.get(name.lower(), []) if c.kind in kinds]

    # ---- BM25 ----
    def search(self, query: str, k: int = 5, language: str | None = None,
               min_terms: int = 1) -> list[tuple[CodeChunk, float]]:
        """BM25 search. `min_terms`: a chunk must contain at least this many distinct query terms."""
        terms = list(dict.fromkeys(tokenize(query)))
        n_docs = len(self.chunks)
        if not terms or not n_docs:
            return []
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, int] = defaultdict(int)
        min_terms = min(min_terms, len(terms))
        for t in terms:
            posting = self._postings.get(t)
            if not posting:
                continue
            idf = math.log(1 + (n_docs - len(posting) + 0.5) / (len(posting) + 0.5))
            for cid, tf in posting.items():
                matched[cid] += 1
                dl = self._doc_len[cid]
                scores[cid] += idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * dl / self._avgdl))
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        out = []
        for cid, sc in ranked:
            if matched[cid] < min_terms:
                continue
            ch = self.chunks[cid]
            if language and ch.language != language:
                continue
            out.append((ch, sc))
            if len(out) >= k:
                break
        return out
