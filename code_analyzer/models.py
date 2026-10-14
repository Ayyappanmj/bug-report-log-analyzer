"""Data models for the code scanner, index and retriever (stdlib only)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SourceFile:
    rel_path: str            # posix-style path relative to the scanned root
    abs_path: Path
    language: str
    lines: list[str]

    @property
    def module(self) -> str:
        return self.rel_path.rsplit(".", 1)[0].replace("/", ".")


@dataclass
class CodeChunk:
    file: str
    kind: str                # function | class | module | block
    name: str
    qualname: str
    start_line: int          # 1-based, inclusive
    end_line: int
    language: str
    class_name: str | None = None
    id: int = -1

    @property
    def size(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class ScanStats:
    files_scanned: int = 0
    total_lines: int = 0
    directories_excluded: int = 0
    duration_seconds: float = 0.0
    by_language: Counter = field(default_factory=Counter)
    skipped: Counter = field(default_factory=Counter)

    def to_dict(self) -> dict:
        return {"files_scanned": self.files_scanned, "total_lines": self.total_lines,
                "directories_excluded": self.directories_excluded,
                "duration_seconds": round(self.duration_seconds, 4),
                "by_language": dict(self.by_language), "skipped": dict(self.skipped)}


@dataclass
class RepoScan:
    root: Path
    files: dict[str, SourceFile]
    stats: ScanStats
    git: dict | None = None


@dataclass
class CodeContext:
    """One piece of retrieved source code. `verified` is True only when the stack-trace frame was
    confirmed against the real file (see `status` and `note` for exactly what was and wasn't checked)."""

    status: str
    verified: bool
    note: str
    file_path: str | None = None
    language: str | None = None
    target_line: int | None = None
    start_line: int | None = None
    end_line: int | None = None
    snippet: list[tuple[int, str]] = field(default_factory=list)
    function: str | None = None
    qualname: str | None = None
    class_name: str | None = None
    module: str | None = None
    function_range: tuple[int, int] | None = None
    imports: list[str] = field(default_factory=list)
    related_functions: list[dict] = field(default_factory=list)
    frame: dict | None = None
    verification: str | None = None   # "code_text" | "function_name" | None
    alternatives: list[str] = field(default_factory=list)

    def snippet_text(self, numbered: bool = True) -> str:
        if numbered:
            return "\n".join(f"{n:>5}  {t}" for n, t in self.snippet)
        return "\n".join(t for _, t in self.snippet)

    def to_dict(self) -> dict:
        return {
            "status": self.status, "verified": self.verified, "verification": self.verification,
            "note": self.note, "file_path": self.file_path, "language": self.language,
            "target_line": self.target_line, "start_line": self.start_line, "end_line": self.end_line,
            "snippet": self.snippet_text(numbered=False), "function": self.function,
            "qualname": self.qualname, "class_name": self.class_name, "module": self.module,
            "function_range": list(self.function_range) if self.function_range else None,
            "imports": self.imports, "related_functions": self.related_functions,
            "frame": self.frame, "alternatives": self.alternatives,
        }


@dataclass
class RetrievalResult:
    contexts: list[CodeContext]
    strategy: str                       # stack_trace | symbol | message | exception | keyword | none
    notes: list[str] = field(default_factory=list)
    external_frames: list[dict] = field(default_factory=list)
    unresolved_frames: list[dict] = field(default_factory=list)

    @property
    def verified_contexts(self) -> list[CodeContext]:
        return [c for c in self.contexts if c.verified]

    def to_dict(self) -> dict:
        return {"strategy": self.strategy, "notes": self.notes,
                "contexts": [c.to_dict() for c in self.contexts],
                "external_frames": self.external_frames, "unresolved_frames": self.unresolved_frames}
