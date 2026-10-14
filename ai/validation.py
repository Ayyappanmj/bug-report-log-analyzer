"""Parse, repair and validate model output.

Validation uses the Pydantic model (ai.schemas.LLMInferenceModel) when pydantic is installed, otherwise an equivalent
built-in validator, so behaviour is the same either way (tests check parity when pydantic is present).
Repair only fixes *format* problems; it never invents content.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

MAX_ITEMS, MAX_EVIDENCE_IDS = 8, 12
MAX_ITEM_LEN, MAX_ROOT_LEN, MAX_IMPACT_LEN, MIN_ROOT_LEN = 500, 1200, 600, 10
LIST_FIELDS = ("alternative_possibilities", "recommended_investigation", "recommended_fix", "reproduction_steps", "caveats")
_EVID = re.compile(r"E\d{1,3}")
_ALIASES = {
    "root_cause": "probable_root_cause", "probable_cause": "probable_root_cause", "hypothesis": "probable_root_cause",
    "evidence": "supporting_evidence", "evidence_ids": "supporting_evidence", "supporting_evidence_ids": "supporting_evidence",
    "alternatives": "alternative_possibilities", "alternative_causes": "alternative_possibilities",
    "investigation": "recommended_investigation", "investigation_steps": "recommended_investigation",
    "fix": "recommended_fix", "fixes": "recommended_fix", "recommended_fixes": "recommended_fix", "suggested_fix": "recommended_fix",
    "steps_to_reproduce": "reproduction_steps", "reproduction": "reproduction_steps", "repro_steps": "reproduction_steps",
    "impact": "inferred_impact", "limitations": "caveats",
}


class LLMValidationError(ValueError):
    """The model output could not be turned into a valid inference payload."""


@dataclass
class LLMInference:
    probable_root_cause: str
    supporting_evidence: list[str]
    confidence: float
    alternative_possibilities: list[str] = field(default_factory=list)
    recommended_investigation: list[str] = field(default_factory=list)
    recommended_fix: list[str] = field(default_factory=list)
    reproduction_steps: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    inferred_impact: str = ""


# --------------------------------------------------------------------------- JSON extraction
def _balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _fix_json_text(s: str) -> str:
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    s = re.sub(r"(?m)^\s*//.*$", "", s)
    s = re.sub(r",\s*([}\]])", r"\1", s)
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    return re.sub(r"\bNone\b", "null", s)


def extract_json(text: str) -> tuple[dict, list[str]]:
    """Find and parse the JSON object in `text`. Returns (data, repairs applied)."""
    if not isinstance(text, str) or not text.strip():
        raise LLMValidationError("empty response")
    repairs: list[str] = []
    cleaned = text.strip()
    if "```" in cleaned:
        cleaned = re.sub(r"```(?:json|JSON)?", "", cleaned)
        repairs.append("removed markdown code fences")
    block = _balanced_object(cleaned)
    if block is None:
        raise LLMValidationError("no JSON object found in the response")
    if block.strip() != cleaned.strip():
        repairs.append("ignored text around the JSON object")
    try:
        data = json.loads(block, strict=False)
    except RecursionError:
        raise LLMValidationError("JSON is nested too deeply") from None
    except ValueError:
        try:
            data = json.loads(_fix_json_text(block), strict=False)
            repairs.append("fixed JSON syntax (trailing commas, quotes or literals)")
        except RecursionError:
            raise LLMValidationError("JSON is nested too deeply") from None
        except ValueError as exc:
            raise LLMValidationError(f"invalid JSON ({exc.msg})") from None
    if not isinstance(data, dict):
        raise LLMValidationError("JSON root is not an object")
    return data, repairs


# --------------------------------------------------------------------------- payload repair
def _truncate(s: str, limit: int, repairs: list[str], name: str) -> str:
    if len(s) > limit:
        repairs.append(f"truncated {name} to {limit} characters")
        return s[: limit - 3].rstrip() + "..."
    return s


def _to_str_list(value, name: str, repairs: list[str]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        repairs.append(f"wrapped {name} string in a list")
        value = [value]
    if not isinstance(value, list):
        return value  # left as is: validation will reject it
    out = []
    for item in value:
        if item is None:
            continue
        if isinstance(item, dict):
            item = json.dumps(item)
        elif not isinstance(item, str):
            item = str(item)
        item = item.strip()
        if item:
            out.append(_truncate(item, MAX_ITEM_LEN, repairs, f"an item of {name}"))
    if len(out) > MAX_ITEMS:
        repairs.append(f"kept the first {MAX_ITEMS} items of {name}")
        out = out[:MAX_ITEMS]
    return out


def repair_payload(data: dict) -> tuple[dict, list[str]]:
    repairs: list[str] = []
    out: dict = {}
    for key, value in data.items():
        k = str(key).strip().lower()
        k2 = _ALIASES.get(k, k)
        if k2 != k:
            repairs.append(f"renamed key '{k}' to '{k2}'")
        out.setdefault(k2, value)
    if "probable_root_cause" in out and not isinstance(out["probable_root_cause"], str) and out["probable_root_cause"] is not None:
        out["probable_root_cause"] = str(out["probable_root_cause"])
    for name, limit in (("probable_root_cause", MAX_ROOT_LEN), ("inferred_impact", MAX_IMPACT_LEN)):
        if isinstance(out.get(name), str):
            out[name] = _truncate(out[name].strip(), limit, repairs, name)
    for name in LIST_FIELDS:
        if name in out:
            out[name] = _to_str_list(out[name], name, repairs)
    if "supporting_evidence" in out:
        raw = out["supporting_evidence"]
        items = raw if isinstance(raw, list) else [raw]
        ids: list[str] = []
        for item in items:
            for m in re.findall(r"[Ee]\d{1,3}", str(item)):
                eid = m.upper()
                if eid not in ids:
                    ids.append(eid)
        if ids != raw:
            repairs.append("normalized supporting_evidence ids")
        out["supporting_evidence"] = ids[:MAX_EVIDENCE_IDS]
    conf = out.get("confidence")
    if isinstance(conf, str):
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(%?)\s*", conf)
        if m:
            conf = float(m.group(1)) / (100 if m.group(2) else 1)
            repairs.append("converted confidence from text")
    if isinstance(conf, (int, float)) and not isinstance(conf, bool) and 1 < conf <= 100:
        conf = conf / 100
        repairs.append("converted confidence percentage to a fraction")
    if conf is not None:
        out["confidence"] = conf
    return out, repairs


# --------------------------------------------------------------------------- validation
def validate_builtin(data: dict) -> LLMInference:
    def need(name):
        if name not in data:
            raise LLMValidationError(f"missing required field '{name}'")
        return data[name]

    def string(name, value, lo, hi):
        if not isinstance(value, str):
            raise LLMValidationError(f"'{name}' must be a string")
        if not (lo <= len(value) <= hi):
            raise LLMValidationError(f"'{name}' must be {lo}-{hi} characters long (got {len(value)})")
        return value

    def str_list(name, value, hi_items):
        if not isinstance(value, list):
            raise LLMValidationError(f"'{name}' must be a list of strings")
        if len(value) > hi_items:
            raise LLMValidationError(f"'{name}' has more than {hi_items} items")
        for item in value:
            if not isinstance(item, str) or not item.strip() or len(item) > MAX_ITEM_LEN:
                raise LLMValidationError(f"'{name}' items must be non-empty strings up to {MAX_ITEM_LEN} characters")
        return value

    root = string("probable_root_cause", need("probable_root_cause"), MIN_ROOT_LEN, MAX_ROOT_LEN)
    ev = str_list("supporting_evidence", need("supporting_evidence"), MAX_EVIDENCE_IDS)
    if not ev:
        raise LLMValidationError("'supporting_evidence' must cite at least one evidence id (E1, E2...)")
    if not all(_EVID.fullmatch(x) for x in ev):
        raise LLMValidationError("'supporting_evidence' items must look like E1, E2...")
    conf = need("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
        raise LLMValidationError("'confidence' must be a number between 0 and 1")
    extra = {name: str_list(name, data.get(name, []), MAX_ITEMS) for name in LIST_FIELDS}
    impact = string("inferred_impact", data.get("inferred_impact", ""), 0, MAX_IMPACT_LEN)
    return LLMInference(root, ev, float(conf), inferred_impact=impact, **extra)


def validate_pydantic(data: dict) -> LLMInference:
    from pydantic import ValidationError

    from .schemas import LLMInferenceModel
    conf = data.get("confidence")
    if isinstance(conf, bool):
        raise LLMValidationError("'confidence' must be a number between 0 and 1")
    try:
        m = LLMInferenceModel.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "payload"
        raise LLMValidationError(f"'{loc}': {first['msg']}") from None
    return LLMInference(**m.model_dump())


def pydantic_available() -> bool:
    try:
        import pydantic  # noqa: F401
        return True
    except ImportError:
        return False


def validate_inference(data: dict) -> LLMInference:
    """Validate a (repaired) payload with Pydantic when available, else the built-in validator."""
    return validate_pydantic(data) if pydantic_available() else validate_builtin(data)
