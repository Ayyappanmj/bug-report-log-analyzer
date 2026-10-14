import re

from agent.orchestrator import AnalysisPipeline
from scripts.generate_demo_log import OUT, SRC

HEDGES = re.compile(r"\b(probably|likely|might|may|possibly|perhaps|suggests|indicates|appears)\b", re.I)


def _run():
    return AnalysisPipeline(top_n=8).run(OUT, SRC.parent)


def test_all_demo_evidence_is_free_of_hedging_and_sourced():
    run = _run()
    for r in run.reports.values():
        assert r.observed_evidence
        for e in r.observed_evidence:
            assert e.source and not HEDGES.search(e.text), (r.group_id, e.text)


def test_root_incident_report_is_grounded_in_real_log_and_code():
    run = _run()
    r = run.reports["G001"]
    g = next(g for g in run.grouping.groups if g.id == "G001")
    assert r.rule_id == "db_pool_timeout" and r.exception == "DatabaseConnectionTimeout"
    assert r.frequency == g.count and r.code_location_verified and r.code_strategy == "stack_trace"
    assert r.affected_files[0] == "src/database.py"
    text = " ".join(e.text for e in r.observed_evidence)
    assert "Connection pool utilization" in text and "Slow database call" in text   # precursors
    assert "process_checkout -> charge -> execute -> _acquire_connection" in text
    assert "500 x" in " ".join(r.observed_impact)
    assert "G002" in r.related_group_ids and "G003" in r.related_group_ids
    assert 0.1 <= r.confidence <= 0.85
    assert r.pattern["label"] == "sustained burst"


def test_precursor_counts_match_group_counts():
    run = _run()
    warn = next(g for g in run.grouping.groups if g.title.startswith("Connection pool utilization"))
    text = " ".join(e.text for e in run.reports["G001"].observed_evidence)
    assert f"{warn.count} 'Connection pool utilization" in text


def test_unverified_group_is_flagged_not_hidden():
    run = _run()
    r = run.reports["G003"]   # message-only group
    assert r.code_strategy == "message" and not r.code_location_verified
    assert any("NOT verified" in e.text for e in r.observed_evidence)
    assert r.confidence < run.reports["G001"].confidence


def test_keyerror_report_points_at_currency_line():
    r = _run().reports["G005"]
    assert r.rule_id == "missing_field" and r.pattern["label"] == "sporadic" and r.code_location_verified
    assert any('order["currency"]' in e.text for e in r.observed_evidence)


def test_symptom_reports_do_not_claim_a_cause_outside_the_evidence():
    run = _run()
    assert run.reports["G002"].rule_id == "upstream_error" and "G001" in run.reports["G002"].probable_root_cause \
        or "G003" in run.reports["G002"].probable_root_cause
    assert run.reports["G004"].rule_id == "health_readiness"
    assert run.reports["G008"].rule_id == "auth_failure"
