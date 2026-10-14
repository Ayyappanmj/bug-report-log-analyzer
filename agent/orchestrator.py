"""Agent controller: log -> parse -> group -> index code -> retrieve -> root-cause reports, with measured timings."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from code_analyzer.models import RepoScan, ScanStats
from code_analyzer.retriever import CodeRetriever
from code_analyzer.search import CodeIndex
from code_analyzer.scanner import scan_repository
from log_analyzer.grouper import ErrorGrouper, GroupingResult
from log_analyzer.ingest import iter_log_lines, validate_log_path
from log_analyzer.models import ParseStats
from log_analyzer.parser import LogParser

from .root_cause_agent import RootCauseAnalyzer, RootCauseReport

if TYPE_CHECKING:  # avoid a runtime import cycle (ai.enhancer imports agent.root_cause_agent)
    from ai.enhancer import LLMEnhancer

Progress = Callable[[str, float], None]


@dataclass
class AnalysisRun:
    log_name: str
    started_at: str
    parse_stats: ParseStats
    grouping: GroupingResult
    scan_stats: ScanStats
    git: dict | None
    reports: dict[str, RootCauseReport]
    timings: dict[str, float]
    log_span: tuple[datetime, datetime] | None = None
    ai_provider: str = "none (deterministic mode)"
    ai_log: list = field(default_factory=list)
    errors: list = field(default_factory=list)   # per-group failures that were contained
    retriever: CodeRetriever | None = field(default=None, repr=False)

    @property
    def dashboard(self) -> dict:
        s = self.grouping.summary
        return {
            "total_events": s["total_events"], "unique_errors": s["error_groups"],
            "critical_errors": s["critical_groups"], "recurring_errors": s["recurring_error_groups"],
            "warning_groups": s["warning_groups"], "files_analyzed": self.scan_stats.files_scanned,
            "analysis_seconds": round(self.timings.get("total", 0.0), 3), "total_log_lines": self.parse_stats.total_lines,
        }

    def to_dict(self) -> dict:
        return {
            "log_name": self.log_name, "started_at": self.started_at, "ai_provider": self.ai_provider, "ai_log": self.ai_log, "errors": self.errors,
            "dashboard": self.dashboard, "parse_stats": self.parse_stats.to_dict(), "scan_stats": self.scan_stats.to_dict(),
            "git": self.git, "timings_seconds": {k: round(v, 4) for k, v in self.timings.items()},
            "grouping": self.grouping.to_dict(), "reports": {k: r.to_dict() for k, r in self.reports.items()},
        }


class AnalysisPipeline:
    def __init__(self, analyzer: RootCauseAnalyzer | None = None, top_n: int = 5, max_contexts: int = 4,
                 max_log_mb: int = 50, enhancer: "LLMEnhancer | None" = None, ai_top_n: int = 3):
        self.analyzer = analyzer or RootCauseAnalyzer()
        self.top_n, self.max_contexts, self.max_log_mb = top_n, max_contexts, max_log_mb
        self.enhancer, self.ai_top_n = enhancer, ai_top_n

    def _maybe_enhance(self, run: "AnalysisRun", report: RootCauseReport) -> RootCauseReport:
        if self.enhancer is None:
            return report
        outcome = self.enhancer.enhance(report)
        run.ai_log.append(outcome.to_dict())
        run.timings["ai"] = run.timings.get("ai", 0.0) + outcome.seconds
        return outcome.report

    def run(self, log_source, repo_path=None, *, log_name: str | None = None,
            progress: Progress | None = None) -> AnalysisRun:
        """`log_source`: file path or seekable binary stream. `repo_path`: source folder or None (no code retrieval)."""
        tick = progress or (lambda stage, frac: None)
        t_all = time.perf_counter()
        timings: dict[str, float] = {}
        started = datetime.now().isoformat(timespec="seconds")

        tick("Reading and parsing log", 0.05)
        t = time.perf_counter()
        if isinstance(log_source, (str, Path)):
            path = validate_log_path(log_source, max_size_mb=self.max_log_mb)
            name = log_name or path.name
            source = path
        else:
            name, source = log_name or "upload.log", log_source
        parser = LogParser()
        grouper = ErrorGrouper()
        lo = hi = None
        add_t = 0.0
        loop_start = time.perf_counter()
        for ev in parser.parse_lines(iter_log_lines(source)):      # streamed: events are grouped and discarded, never all held
            ts = ev.timestamp
            if ts is not None:
                if lo is None or ts < lo:
                    lo = ts
                if hi is None or ts > hi:
                    hi = ts
            t_add = time.perf_counter()
            grouper.add(ev)
            add_t += time.perf_counter() - t_add
        loop_total = time.perf_counter() - loop_start
        tick("Ranking error groups", 0.35)
        t_fin = time.perf_counter()
        grouping = grouper.finalize()
        fin_t = time.perf_counter() - t_fin
        timings["parse"] = max(loop_total - add_t, 0.0) + (loop_start - t)       # parsing + validation, grouping excluded
        timings["group"] = add_t + fin_t
        span = (lo, hi) if lo is not None else None

        tick("Scanning source code", 0.5)
        t = time.perf_counter()
        scan = scan_repository(repo_path) if repo_path else RepoScan(Path("."), {}, ScanStats())
        index = CodeIndex(scan)
        timings["index"] = time.perf_counter() - t
        retriever = CodeRetriever(index)

        run = AnalysisRun(name, started, parser.stats, grouping, scan.stats, scan.git, {}, timings, span, retriever=retriever)
        if self.enhancer is not None:
            run.ai_provider = self.enhancer.provider.describe()
        targets = grouping.groups[: self.top_n]
        retrieve_t = analyze_t = 0.0
        for i, g in enumerate(targets):
            tick(f"Analyzing {g.id}", 0.6 + 0.35 * (i / max(len(targets), 1)))
            try:
                t = time.perf_counter()
                ret = retriever.retrieve_for_group(g, self.max_contexts)
                retrieve_t += time.perf_counter() - t
                t = time.perf_counter()
                report = self.analyzer.analyze(g, ret, grouping.groups, span)
                analyze_t += time.perf_counter() - t
            except Exception as exc:  # noqa: BLE001 - contain the failure, keep the other groups
                run.errors.append({"group_id": g.id, "stage": "analysis", "error": f"{type(exc).__name__}: {exc}"[:300]})
                continue
            if i < self.ai_top_n:
                tick(f"AI refinement of {g.id}", 0.6 + 0.35 * (i / max(len(targets), 1)))
                report = self._maybe_enhance(run, report)
            run.reports[g.id] = report
        timings["retrieval"], timings["analysis"] = retrieve_t, analyze_t
        timings["total"] = time.perf_counter() - t_all
        tick("Done", 1.0)
        return run

    def analyze_group(self, run: AnalysisRun, group_id: str, use_ai: bool = True) -> RootCauseReport:
        """Analyze one more group on demand (e.g. a warning group outside the top N)."""
        if group_id in run.reports:
            return run.reports[group_id]
        group = next((g for g in run.grouping.groups if g.id == group_id), None)
        if group is None:
            raise KeyError(f"Unknown group id {group_id}")
        ret = run.retriever.retrieve_for_group(group, self.max_contexts) if run.retriever else None
        report = self.analyzer.analyze(group, ret, run.grouping.groups, run.log_span)
        run.reports[group_id] = self._maybe_enhance(run, report) if use_ai else report
        return run.reports[group_id]
