from pytest import raises

from ai.validation import (LLMValidationError, extract_json, pydantic_available, repair_payload, validate_builtin,
                           validate_inference)

OK = {"probable_root_cause": "A pool was saturated under load.", "supporting_evidence": ["E1"], "confidence": 0.6}


def test_extract_json_variants():
    assert extract_json('{"a": 1}')[0] == {"a": 1}
    d, rep = extract_json('Sure! Here you go:\n```json\n{"a": 1, "b": [1, 2,],}\n```\nHope it helps')
    assert d == {"a": 1, "b": [1, 2]} and any("fences" in r for r in rep) and any("syntax" in r for r in rep)
    assert extract_json("{'a': 1}" .replace("'", '"'))[0] == {"a": 1}
    assert extract_json('{"a": "x {not} a brace", "b": {"c": 2}} trailing')[0]["b"] == {"c": 2}
    assert extract_json('{"a": True, "b": None}')[0] == {"a": True, "b": None}
    assert extract_json('{\u201ca\u201d: 1}')[0] == {"a": 1}
    assert extract_json('{"a": "line1\nline2"}')[0] == {"a": "line1\nline2"}      # raw newline inside a string


def test_extract_json_rejects_non_objects():
    for bad in ("", "   ", "no json here", "[1, 2, 3]", '{"a": ', "{not json at all}"):
        with raises(LLMValidationError):
            extract_json(bad)


def test_repair_renames_aliases_and_wraps_scalars():
    d, rep = repair_payload({"Root_Cause": "x" * 20, "evidence": "E1, e2 and E3", "fixes": "Do X", "impact": 5,
                             "confidence": "85%"})
    assert d["probable_root_cause"] == "x" * 20 and d["supporting_evidence"] == ["E1", "E2", "E3"]
    assert d["recommended_fix"] == ["Do X"] and d["confidence"] == 0.85
    assert rep


def test_repair_truncates_and_caps_but_does_not_invent():
    d, rep = repair_payload({**OK, "recommended_fix": [f"fix {i}" for i in range(12)],
                             "alternative_possibilities": ["y" * 900], "probable_root_cause": "z" * 2000, "confidence": 70})
    assert len(d["recommended_fix"]) == 8 and len(d["alternative_possibilities"][0]) == 500
    assert len(d["probable_root_cause"]) == 1200 and d["confidence"] == 0.7
    assert "reproduction_steps" not in d and "inferred_impact" not in d


def test_repair_drops_empty_items_and_none():
    d, _ = repair_payload({**OK, "caveats": ["  ", None, "real", 3, {"k": "v"}], "reproduction_steps": None})
    assert d["caveats"] == ["real", "3", '{"k": "v"}'] and d["reproduction_steps"] == []


def test_valid_payload_passes():
    v = validate_builtin(dict(OK))
    assert v.confidence == 0.6 and v.supporting_evidence == ["E1"] and v.recommended_fix == []


def test_invalid_payloads_are_rejected():
    cases = [
        {k: v for k, v in OK.items() if k != "probable_root_cause"},
        {k: v for k, v in OK.items() if k != "confidence"},
        {**OK, "probable_root_cause": "short"},
        {**OK, "supporting_evidence": []},
        {**OK, "supporting_evidence": ["F1"]},
        {**OK, "supporting_evidence": "E1"},
        {**OK, "confidence": 1.5}, {**OK, "confidence": -0.1}, {**OK, "confidence": True}, {**OK, "confidence": "high"},
        {**OK, "recommended_fix": "not a list"}, {**OK, "recommended_fix": [""]}, {**OK, "recommended_fix": [1]},
        {**OK, "recommended_fix": ["a"] * 9}, {**OK, "inferred_impact": 5}, {**OK, "probable_root_cause": 12345678901},
    ]
    for c in cases:
        with raises(LLMValidationError):
            validate_builtin(c)


def test_validate_inference_uses_available_backend_consistently():
    assert validate_inference(dict(OK)).probable_root_cause == OK["probable_root_cause"]
    with raises(LLMValidationError):
        validate_inference({**OK, "confidence": 2})
    assert isinstance(pydantic_available(), bool)


def test_pydantic_and_builtin_validators_agree():
    import pytest
    pytest.importorskip("pydantic")
    from ai.validation import validate_pydantic
    good = [dict(OK), {**OK, "recommended_fix": ["a", "b"], "inferred_impact": "x" * 600, "caveats": ["c"]}]
    bad = [{**OK, "confidence": 1.5}, {**OK, "supporting_evidence": ["F1"]}, {**OK, "probable_root_cause": "short"},
           {**OK, "recommended_fix": ["a"] * 9}, {**OK, "supporting_evidence": []}, {**OK, "recommended_fix": [""]},
           {k: v for k, v in OK.items() if k != "confidence"}, {**OK, "confidence": True}]
    for g in good:
        assert validate_pydantic(g) == validate_builtin(g)
    for b in bad:
        with raises(LLMValidationError):
            validate_pydantic(b)
        with raises(LLMValidationError):
            validate_builtin(b)
