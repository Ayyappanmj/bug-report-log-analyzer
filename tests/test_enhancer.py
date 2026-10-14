import copy

from agent.root_cause_agent import EvidenceItem
from ai.base import AIProviderError, NoLLMProvider
from ai.enhancer import LLMEnhancer
from tests.fakes import FakeProvider, demo_report, good_reply


def enh(replies, **kw):
    prov = FakeProvider(replies, available=kw.pop("available", True))
    return LLMEnhancer(prov, backoff=0, **kw), prov


def evidence(report):
    return [(e.text, e.source) for e in report.observed_evidence]


def test_happy_path_replaces_only_inference_sections():
    base = demo_report()
    snapshot = copy.deepcopy(base)
    e, prov = enh([good_reply()])
    out = e.enhance(base)
    r = out.report
    assert out.used and out.attempts == 1 and len(prov.calls) == 1 and out.fallback_reason is None
    assert r.ai_enhanced and r.generated_by == "fake:test" and r.ai_provider == "fake:test"
    assert r.probable_root_cause.startswith("The database connection pool") and r.recommended_fix == ["Release connections promptly."]
    assert r.baseline_probable_root_cause == base.probable_root_cause
    assert evidence(r) == evidence(base)                         # observed evidence untouched
    assert r.confidence == base.confidence and r.ai_confidence == 0.7
    assert [x["id"] for x in r.ai_supporting_evidence] == ["E1", "E2"]
    assert r.ai_supporting_evidence[0]["text"] == base.observed_evidence[0].text[:400]
    assert "language model" in r.disclaimer and r.ai_caveats == ["No database-side metrics were provided."]
    assert base.to_dict() == snapshot.to_dict() and not base.ai_enhanced   # input report not mutated


def test_model_cannot_overwrite_observed_evidence_via_extra_keys():
    base = demo_report()
    e, _ = enh([good_reply(observed_evidence=[{"text": "FAKE", "source": "x"}], frequency=1)])
    r = e.enhance(base).report
    assert evidence(r) == evidence(base) and r.frequency == base.frequency


def test_format_problems_are_repaired_without_retry():
    payload = good_reply().replace('"confidence": 0.7', '"confidence": "85%"')
    raw = "Sure!\n```json\n" + payload[:-1] + ",}" + "\n```"
    e, prov = enh([raw])
    out = e.enhance(demo_report())
    assert out.used and out.attempts == 1 and len(prov.calls) == 1 and out.repairs
    assert out.report.ai_confidence == 0.85


def test_aliases_and_scalars_are_coerced():
    raw = '{"root_cause": "Pool exhaustion under load is the main hypothesis.", "evidence": "E1, E3", "fixes": "Use a context manager.", "confidence": 0.5}'
    out = enh([raw])[0].enhance(demo_report())
    assert out.used and out.report.recommended_fix == ["Use a context manager."]
    assert [x["id"] for x in out.report.ai_supporting_evidence] == ["E1", "E3"]


def test_invalid_then_valid_retries_with_feedback():
    e, prov = enh(["I cannot help with that", good_reply()])
    out = e.enhance(demo_report())
    assert out.used and out.attempts == 2 and len(prov.calls) == 2
    assert "rejected" in prov.calls[1]["prompt"] and "no JSON object" in prov.calls[1]["prompt"]


def test_two_invalid_replies_fall_back_to_deterministic_report():
    base = demo_report()
    e, prov = enh(["nope", good_reply(confidence=150)])
    out = e.enhance(base)
    assert not out.used and len(prov.calls) == 2 and "invalid model output" in out.fallback_reason
    assert out.report.probable_root_cause == base.probable_root_cause and not out.report.ai_enhanced
    assert out.report.ai_fallback_reason == out.fallback_reason and out.report.generated_by == "deterministic-rules"


def test_transient_provider_error_is_retried_once():
    e, prov = enh([AIProviderError("timeout", retriable=True), good_reply()])
    out = e.enhance(demo_report())
    assert out.used and out.attempts == 2


def test_persistent_and_non_retriable_provider_errors_fall_back():
    e, prov = enh([AIProviderError("bad key", retriable=False)])
    out = e.enhance(demo_report())
    assert not out.used and len(prov.calls) == 1 and "provider error: bad key" in out.fallback_reason
    e2, prov2 = enh([AIProviderError("down", retriable=True)])
    out2 = e2.enhance(demo_report())
    assert not out2.used and len(prov2.calls) == 2


def test_unavailable_provider_makes_no_calls():
    e, prov = enh(["x"], available=False)
    out = e.enhance(demo_report())
    assert not out.used and prov.calls == [] and "unavailable" in out.fallback_reason
    out2 = LLMEnhancer(NoLLMProvider()).enhance(demo_report())
    assert not out2.used and "deterministic" in out2.fallback_reason


def test_unknown_evidence_ids_are_dropped_with_a_warning():
    out = enh([good_reply(supporting_evidence=["E1", "E99"])])[0].enhance(demo_report())
    assert out.used and [x["id"] for x in out.report.ai_supporting_evidence] == ["E1"]
    assert any("E99" in w for w in out.warnings)


def test_citing_only_nonexistent_evidence_is_rejected():
    e, prov = enh([good_reply(supporting_evidence=["E98"])])
    out = e.enhance(demo_report())
    assert not out.used and len(prov.calls) == 2 and "cites no evidence id that exists" in out.fallback_reason


def test_mentions_of_unknown_files_and_commands_become_warnings():
    out = enh([good_reply(recommended_fix=["Edit billing/ledger.py and database.py", "Run `sudo rm -rf /tmp/cache`"])])[0] \
        .enhance(demo_report())
    assert out.used
    joined = " ".join(out.warnings)
    assert "ledger.py" in joined and "database.py" not in joined.split("evidence:")[1]
    assert "command-like" in joined and out.report.ai_warnings == out.warnings


def test_secrets_in_evidence_never_reach_the_provider():
    base = copy.deepcopy(demo_report())
    base.observed_evidence.append(EvidenceItem("Sample message: password=hunter2 AKIAABCDEFGHIJKLMNOP", "log line 9"))
    e, prov = enh([good_reply()])
    out = e.enhance(base)
    sent = prov.calls[0]["prompt"] + (prov.calls[0]["system"] or "")
    assert "hunter2" not in sent and "AKIAABCDEFGHIJKLMNOP" not in sent
    assert out.redactions["aws_key"] == 1 and out.used


def test_outcome_to_dict_is_serialisable():
    import json
    out = enh([good_reply()])[0].enhance(demo_report())
    d = json.loads(json.dumps(out.to_dict()))
    assert d["used"] is True and d["group_id"] == "G001" and d["seconds"] >= 0


def test_enhanced_report_round_trips_to_json():
    import json
    r = enh([good_reply()])[0].enhance(demo_report()).report
    d = json.loads(json.dumps(r.to_dict()))
    assert d["ai_enhanced"] is True and d["baseline_probable_root_cause"]
