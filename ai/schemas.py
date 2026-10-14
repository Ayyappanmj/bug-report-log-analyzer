"""Pydantic schemas for structured analysis output (validation of reports and, in Phase 7, LLM JSON).

Field names mirror `agent.root_cause_agent.RootCauseReport.to_dict()`, so a deterministic report can be validated with
`RootCauseAnalysis.model_validate(report.to_dict())`. Observed evidence is kept separate from inference.
"""
from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvidenceItem(BaseModel):
    text: str
    source: str = ""


class CodeContext(BaseModel):
    status: str = "unknown"
    verified: bool = False  # True only if the exact stack-trace location was confirmed
    note: str = ""
    file_path: str | None = None
    target_line: int | None = Field(default=None, ge=1)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    snippet: str = ""
    qualname: str | None = None
    class_name: str | None = None
    module: str | None = None


class RootCauseAnalysis(BaseModel):
    group_id: str = ""
    incident: str
    severity: Severity
    category: str = ""
    first_occurrence: str | None = None
    last_occurrence: str | None = None
    frequency: int = Field(default=0, ge=0)
    affected_services: list[str] = Field(default_factory=list)
    exception: str | None = None
    error_message: str = ""
    stack_trace: str = ""
    observed_evidence: list[EvidenceItem] = Field(default_factory=list)  # measured from log/code
    probable_root_cause: str = ""  # hypothesis, NOT confirmed fact
    alternative_possibilities: list[str] = Field(default_factory=list)
    observed_impact: list[str] = Field(default_factory=list)
    inferred_impact: str = ""
    affected_files: list[str] = Field(default_factory=list)
    code_context: list[CodeContext] = Field(default_factory=list)
    code_location_verified: bool = False
    recommended_investigation: list[str] = Field(default_factory=list)
    recommended_fix: list[str] = Field(default_factory=list)
    reproduction_steps: list[str] = Field(default_factory=list)
    related_group_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_basis: list[str] = Field(default_factory=list)
    generated_by: str = "deterministic-rules"

    # filled only when an optional LLM refined the inference sections
    baseline_probable_root_cause: str | None = None
    ai_enhanced: bool = False
    ai_provider: str | None = None
    ai_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ai_supporting_evidence: list[dict] = Field(default_factory=list)
    ai_caveats: list[str] = Field(default_factory=list)
    ai_warnings: list[str] = Field(default_factory=list)
    ai_attempts: int = Field(default=0, ge=0)
    ai_fallback_reason: str | None = None


class LLMInferenceModel(BaseModel):
    """What a model is allowed to return. It can only add inference; observed evidence is never model-written."""

    probable_root_cause: str = Field(min_length=10, max_length=1200)
    supporting_evidence: list[str] = Field(min_length=1, max_length=12)
    confidence: float = Field(ge=0.0, le=1.0)
    alternative_possibilities: list[str] = Field(default_factory=list, max_length=8)
    recommended_investigation: list[str] = Field(default_factory=list, max_length=8)
    recommended_fix: list[str] = Field(default_factory=list, max_length=8)
    reproduction_steps: list[str] = Field(default_factory=list, max_length=8)
    caveats: list[str] = Field(default_factory=list, max_length=8)
    inferred_impact: str = Field(default="", max_length=600)

    @field_validator("supporting_evidence")
    @classmethod
    def _evidence_ids(cls, v: list[str]) -> list[str]:
        for x in v:
            if not re.fullmatch(r"E\d{1,3}", x):
                raise ValueError("items must look like E1, E2...")
        return v

    @field_validator("alternative_possibilities", "recommended_investigation", "recommended_fix",
                     "reproduction_steps", "caveats")
    @classmethod
    def _items(cls, v: list[str]) -> list[str]:
        for x in v:
            if not x.strip() or len(x) > 500:
                raise ValueError("items must be non-empty strings up to 500 characters")
        return v
