import json

from agent.orchestrator import AnalysisPipeline
from ai.enhancer import LLMEnhancer
from scripts.generate_demo_log import OUT, SRC
from tests.fakes import FakeProvider, good_reply

REPO = SRC.parent


def pipe(replies, ai_top_n=2, top_n=4, available=True):
    prov = FakeProvider(replies, available=available)
    return AnalysisPipeline(top_n=top_n, enhancer=LLMEnhancer(prov, backoff=0), ai_top_n=ai_top_n), prov


def test_only_top_groups_are_sent_to_the_model():
    p, prov = pipe([good_reply()], ai_top_n=2)
    run = p.run(OUT, REPO)
    assert len(prov.calls) == 2 and len(run.ai_log) == 2
    assert [run.reports[g].ai_enhanced for g in ("G001", "G002", "G003", "G004")] == [True, True, False, False]
    assert run.ai_provider == "fake:test" and run.timings["ai"] >= 0
    assert "timings_seconds" in run.to_dict() and "ai" in run.to_dict()["timings_seconds"]


def test_unusable_model_leaves_a_complete_deterministic_run():
    p, _ = pipe(["garbage"], ai_top_n=2)
    run = p.run(OUT, REPO)
    base = AnalysisPipeline(top_n=4).run(OUT, REPO)
    assert not any(r.ai_enhanced for r in run.reports.values())
    assert run.reports["G001"].probable_root_cause == base.reports["G001"].probable_root_cause
    assert all(x["fallback_reason"] for x in run.ai_log) and run.dashboard["unique_errors"] == base.dashboard["unique_errors"]


def test_unavailable_model_is_a_noop_with_reason():
    p, prov = pipe(["x"], available=False)
    run = p.run(OUT, REPO)
    assert prov.calls == [] and "unavailable" in run.ai_log[0]["fallback_reason"]


def test_no_enhancer_means_no_ai_activity():
    run = AnalysisPipeline(top_n=3).run(OUT, REPO)
    assert run.ai_log == [] and "ai" not in run.timings and run.ai_provider.startswith("none")


def test_analyze_group_on_demand_respects_use_ai():
    p, prov = pipe([good_reply()], ai_top_n=0)
    run = p.run(OUT, REPO)
    assert prov.calls == []
    assert not p.analyze_group(run, "G005", use_ai=False).ai_enhanced and prov.calls == []
    assert p.analyze_group(run, "G006").ai_enhanced and len(prov.calls) == 1


def test_run_with_ai_is_json_serialisable():
    p, _ = pipe([good_reply()])
    d = json.loads(json.dumps(p.run(OUT, REPO).to_dict()))
    assert d["reports"]["G001"]["ai_enhanced"] is True and d["ai_log"][0]["used"] is True
