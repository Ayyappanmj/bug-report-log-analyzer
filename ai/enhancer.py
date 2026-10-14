"""Optional LLM refinement of a deterministic report.

The model may only rewrite the *inference* sections. Observed evidence is never touched. Output is parsed, repaired
(format only), validated, grounded against the evidence ids it cites, and retried once if invalid. On any failure the
unchanged deterministic report is returned, with the reason recorded.
"""
from __future__ import annotations

import copy
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from agent.root_cause_agent import DISCLAIMER_AI, RootCauseReport

from .base import AIProvider, AIProviderError
from .prompts import PromptBundle, build_prompt
from .validation import LLMValidationError, extract_json, repair_payload, validate_inference

_FILE_MENTION = re.compile(r"[\w./\\-]+\.(?:py|jsx?|tsx?|java)\b")
_COMMAND_LIKE = re.compile(r"(?m)```|^\s*\$\s|\bsudo\s|\brm\s+-rf\b|\bcurl\b[^\n]*\|\s*(?:ba)?sh\b|\bchmod\s+[0-7]{3}|\bkill\s+-9\b")


@dataclass
class EnhancementOutcome:
    report: RootCauseReport
    used: bool
    attempts: int = 0
    repairs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fallback_reason: str | None = None
    redactions: dict = field(default_factory=dict)
    prompt_truncated: bool = False
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {"group_id": self.report.group_id, "used": self.used, "attempts": self.attempts,
                "repairs": self.repairs, "warnings": self.warnings, "fallback_reason": self.fallback_reason,
                "redactions": self.redactions, "prompt_truncated": self.prompt_truncated,
                "seconds": round(self.seconds, 3)}


class LLMEnhancer:
    def __init__(self, provider: AIProvider, *, max_retries: int = 1, timeout: float = 120.0,
                 backoff: float = 0.5, redact_emails: bool = True, max_prompt_chars: int = 12000):
        self.provider = provider
        self.max_retries, self.timeout, self.backoff = max_retries, timeout, backoff
        self.redact_emails, self.max_prompt_chars = redact_emails, max_prompt_chars

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _warnings_for(inf, bundle: PromptBundle) -> list[str]:
        warnings: list[str] = []
        text = " ".join([inf.probable_root_cause, inf.inferred_impact, *inf.alternative_possibilities,
                         *inf.recommended_investigation, *inf.recommended_fix, *inf.reproduction_steps])
        known = {PurePosixPath(f.replace("\\", "/")).name.lower() for f in bundle.known_files}
        unknown = sorted({m for m in _FILE_MENTION.findall(text)
                          if PurePosixPath(m.replace("\\", "/")).name.lower() not in known})
        if unknown:
            warnings.append("Model text mentions file(s) that are not in the evidence: " + ", ".join(unknown[:5]))
        if _COMMAND_LIKE.search(text):
            warnings.append("Model text contains command-like content. Commands are never executed by this tool; review before use.")
        return warnings

    def _apply(self, report: RootCauseReport, inf, bundle: PromptBundle, valid_ids: list[str], warnings: list[str],
               attempts: int) -> RootCauseReport:
        out = copy.deepcopy(report)
        out.baseline_probable_root_cause = report.probable_root_cause
        out.probable_root_cause = inf.probable_root_cause
        out.alternative_possibilities = inf.alternative_possibilities or out.alternative_possibilities
        out.recommended_investigation = inf.recommended_investigation or out.recommended_investigation
        out.recommended_fix = inf.recommended_fix or out.recommended_fix
        out.reproduction_steps = inf.reproduction_steps or out.reproduction_steps
        out.inferred_impact = inf.inferred_impact or out.inferred_impact
        out.ai_enhanced, out.ai_provider, out.ai_attempts = True, self.provider.describe(), attempts
        out.ai_confidence = round(inf.confidence, 2)
        out.ai_supporting_evidence = [{"id": i, "text": bundle.evidence[i]} for i in valid_ids]
        out.ai_caveats, out.ai_warnings = list(inf.caveats), warnings
        out.generated_by = self.provider.describe()
        out.disclaimer = DISCLAIMER_AI
        return out

    # ------------------------------------------------------------------ main entry
    def enhance(self, report: RootCauseReport) -> EnhancementOutcome:
        """Never raises: any unexpected problem returns the unchanged deterministic report with the reason."""
        t0 = time.perf_counter()
        try:
            return self._enhance(report, t0)
        except Exception as exc:  # noqa: BLE001
            kept = copy.deepcopy(report)
            kept.ai_fallback_reason = f"unexpected error: {type(exc).__name__}"
            return EnhancementOutcome(kept, False, 0, fallback_reason=kept.ai_fallback_reason, seconds=time.perf_counter() - t0)

    def _enhance(self, report: RootCauseReport, t0: float) -> EnhancementOutcome:

        def fallback(reason: str, attempts: int = 0, **kw) -> EnhancementOutcome:
            kept = copy.deepcopy(report)
            kept.ai_fallback_reason, kept.ai_attempts = reason, attempts
            return EnhancementOutcome(kept, False, attempts, fallback_reason=reason,
                                      seconds=time.perf_counter() - t0, **kw)

        if not self.provider.is_available():
            return fallback(f"LLM unavailable: {self.provider.unavailable_reason()}")
        bundle = build_prompt(report, max_chars=self.max_prompt_chars, redact_emails=self.redact_emails)
        red, trunc = dict(bundle.redactions), bundle.truncated
        prompt, last_error, attempts, repairs_all = bundle.user, "", 0, []
        for attempt in range(1, self.max_retries + 2):
            attempts = attempt
            try:
                raw = self.provider.generate(prompt, bundle.system, self.timeout)
            except AIProviderError as exc:
                last_error = f"provider error: {exc}"
                if exc.retriable and attempt <= self.max_retries:
                    time.sleep(self.backoff)
                    continue
                break
            try:
                data, r1 = extract_json(raw)
                data, r2 = repair_payload(data)
                inf = validate_inference(data)
                valid = [i for i in inf.supporting_evidence if i in bundle.evidence]
                if not valid:
                    raise LLMValidationError("'supporting_evidence' cites no evidence id that exists (valid ids: "
                                             f"E1-E{len(bundle.evidence)})")
            except LLMValidationError as exc:
                last_error = f"invalid model output: {exc}"
                prompt = (bundle.user + f"\n\nYour previous reply was rejected: {exc}. "
                          "Reply again with ONLY a valid JSON object in the required shape.")
                continue
            warnings = self._warnings_for(inf, bundle)
            dropped = [i for i in inf.supporting_evidence if i not in bundle.evidence]
            if dropped:
                warnings.append("Model cited evidence ids that do not exist and were dropped: " + ", ".join(dropped))
            out = self._apply(report, inf, bundle, valid, warnings, attempts)
            return EnhancementOutcome(out, True, attempts, r1 + r2, warnings, None, red, trunc,
                                      time.perf_counter() - t0)
        return fallback(f"{last_error} (after {attempts} attempt(s))", attempts, redactions=red, prompt_truncated=trunc)
