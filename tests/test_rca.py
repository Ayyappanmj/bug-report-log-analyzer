import json
import re
from datetime import datetime, timedelta

from agent.root_cause_agent import MAX_CONFIDENCE, RootCauseAnalyzer, analyze_pattern
from agent.rules import match_rule
from code_analyzer.models import CodeContext, RetrievalResult
from log_analyzer.grouper import group_events
from log_analyzer.models import LogEvent

T0 = datetime(2026, 9, 30, 10, 0, 0)
HEDGES = re.compile(r"\b(probably|likely|might|may|possibly|perhaps|suggests|indicates|appears)\b", re.I)
TRACE = ["Traceback (most recent call last):", '  File "src/db.py", line 5, in connect', "    raise DbTimeout()",
         "DatabaseConnectionTimeout: timed out after 5s"]


def ev(n, level="ERROR", msg="boom", service="Svc", rid=None, trace=None, status=None, minute=0.0):
    return LogEvent(line_no=n, fmt="t", raw=msg, message=msg, level=level, service=service, request_id=rid,
                    http_status=status, continuation=list(trace or []), timestamp=T0 + timedelta(minutes=minute))


def analyze(events, gid="G001", retrieval=None):
    res = group_events(events)
    g = next(x for x in res.groups if x.id == gid)
    return RootCauseAnalyzer().analyze(g, retrieval, res.groups, (T0, T0 + timedelta(minutes=60))), res


def ctx(verified, line=5):
    return CodeContext("verified_exact" if verified else "line_moved", verified,
                       "Verified: line matches." if verified else "NOT verified: moved.",
                       file_path="src/db.py", target_line=line, snippet=[(line, "    raise DbTimeout()")],
                       qualname="connect")


def test_rule_matching_table():
    cases = {
        "DatabaseConnectionTimeout: Timed out": "db_pool_timeout",
        "Database connection timeout while charging": "db_pool_timeout",
        "Connection pool utilization at <N>%": "db_saturation_warning",
        "Slow database call <N>ms": "db_saturation_warning",
        "ConnectionRefusedError: [Errno 111]": "network_connection",
        "Request timed out after 30s": "generic_timeout",
        "Lock wait timeout exceeded": "deadlock",
        "Invalid token for user=u<N>": "auth_failure",
        "KeyError: 'currency'": "missing_field",
        "AttributeError: 'NoneType' object has no attribute x": "null_reference",
        "java.lang.OutOfMemoryError: Java heap space": "out_of_memory",
        "No space left on device": "disk_space",
        "ValueError: bad amount": "validation_error",
        "FileNotFoundError: x.cfg": "file_missing",
        "Readiness probe failed db=down": "health_readiness",
        "upstream returned error": "upstream_error",
        "something entirely different": "generic",
    }
    for text, rule_id in cases.items():
        assert match_rule(text).id == rule_id, text


def test_basic_fields_and_separation_of_evidence_and_inference():
    events = [ev(i, msg="Checkout failed", trace=TRACE, rid=f"r{i}", minute=i) for i in range(1, 13)]
    r, _ = analyze(events)
    assert r.frequency == 12 and r.exception == "DatabaseConnectionTimeout"
    assert r.first_occurrence == "2026-09-30 10:01:00" and r.last_occurrence == "2026-09-30 10:12:00"
    assert r.affected_services == ["Svc"] and r.rule_id == "db_pool_timeout"
    assert r.observed_evidence and all(e.source for e in r.observed_evidence)
    for e in r.observed_evidence:
        assert not HEDGES.search(e.text), e.text  # evidence states measurements, never guesses
    assert r.probable_root_cause and r.probable_root_cause not in [e.text for e in r.observed_evidence]
    assert r.alternative_possibilities and r.recommended_fix and r.recommended_investigation
    assert "12 event(s)" in r.observed_evidence[0].text
    assert "Verify" not in r.disclaimer and "hypothesis" in r.disclaimer


def test_precursor_warning_before_error_is_reported_and_raises_confidence():
    warn = [ev(i, level="WARN", msg="Connection pool utilization at 95%", minute=i) for i in range(1, 4)]
    err = [ev(10 + i, msg="Checkout failed", trace=TRACE, minute=10 + i) for i in range(5)]
    r, res = analyze(warn + err, gid=next(g.id for g in group_events(warn + err).groups if g.severity == "HIGH"))
    assert any("began" in e.text and "before the first event" in e.text for e in r.observed_evidence)
    assert any("earlier warning" in b for b in r.confidence_basis)


def test_warning_after_error_is_not_a_precursor():
    err = [ev(i, msg="Checkout failed", trace=TRACE, minute=i) for i in range(1, 4)]
    warn = [ev(10 + i, level="WARN", msg="Connection pool utilization at 95%", minute=10 + i) for i in range(3)]
    gid = next(g.id for g in group_events(err + warn).groups if g.severity == "HIGH")
    r, _ = analyze(err + warn, gid=gid)
    assert not any("began" in e.text for e in r.observed_evidence)


def test_symptom_group_points_to_related_group():
    events = []
    for i in range(3):
        events.append(ev(10 + i, msg="db failure detail", service="Pay", rid=f"r{i}", minute=i, trace=TRACE))
        events.append(ev(20 + i, msg="upstream returned error", service="gw", rid=f"r{i}", status=500, minute=i))
    res = group_events(events)
    gw = next(g for g in res.groups if g.title == "upstream returned error")
    r = RootCauseAnalyzer().analyze(gw, None, res.groups)
    other = next(g for g in res.groups if g is not gw)
    assert other.id in r.probable_root_cause and r.related_group_ids == [other.id]
    assert any("Shares 3 request ID(s)" in e.text for e in r.observed_evidence)
    assert any("500 x3" in line for line in r.observed_impact)


def test_temporal_overlap_evidence():
    big = [ev(i, msg="big failure", minute=i) for i in range(1, 11)]
    probe = [ev(50, level="CRITICAL", msg="Readiness probe failed db=down", service="Health", minute=5)]
    gid = next(g.id for g in group_events(big + probe).groups if g.severity == "CRITICAL")
    r, _ = analyze(big + probe, gid=gid)
    assert any("during the active window" in e.text for e in r.observed_evidence)
    assert r.rule_id == "health_readiness"


def test_confidence_components_and_cap():
    events = [ev(i, msg="Checkout failed", trace=TRACE, rid=f"r{i}", minute=10 + i) for i in range(5)]
    base, _ = analyze(events)                           # no retrieval at all
    assert any("no source code located" in b for b in base.confidence_basis)
    unverified, _ = analyze(events, retrieval=RetrievalResult([ctx(False)], "stack_trace"))
    verified, _ = analyze(events, retrieval=RetrievalResult([ctx(True)], "stack_trace"))
    assert base.confidence < unverified.confidence < verified.confidence <= MAX_CONFIDENCE
    assert verified.code_location_verified and not unverified.code_location_verified
    assert abs((verified.confidence - unverified.confidence) - 0.10) < 1e-9
    warn = [ev(100 + i, level="WARN", msg="Connection pool utilization at 95%", minute=i) for i in range(3)]
    gid = next(g.id for g in group_events(warn + events).groups if g.severity == "HIGH")
    top, _ = analyze(warn + events, gid=gid, retrieval=RetrievalResult([ctx(True)], "stack_trace"))
    assert top.confidence <= MAX_CONFIDENCE and 0.1 <= top.confidence


def test_code_evidence_states_verification_status():
    events = [ev(1, trace=TRACE)]
    r, _ = analyze(events, retrieval=RetrievalResult([ctx(True), ctx(False, 9)], "stack_trace"))
    code_items = [e for e in r.observed_evidence if e.source.startswith("src/db.py")]
    assert "Verified: line matches" in code_items[0].text and "NOT verified" in code_items[1].text
    assert r.affected_files == ["src/db.py"] and r.code_context[0]["file_path"] == "src/db.py"
    assert not any(HEDGES.search(e.text) for e in r.observed_evidence)


def test_no_code_found_is_stated():
    r, _ = analyze([ev(1, msg="odd failure")], retrieval=RetrievalResult([], "none", notes=["x"]))
    assert any("No source code could be located" in e.text for e in r.observed_evidence)
    assert r.rule_id is None and r.category == "Unclassified failure" and r.notes == ["x"]


def test_pattern_labels():
    def pat(minutes):
        res = group_events([ev(i, msg="m", minute=m) for i, m in enumerate(minutes)])
        return analyze_pattern(res.groups[0], (T0, T0 + timedelta(minutes=60)))
    assert pat([3])["label"] == "single occurrence"
    assert pat(list(range(15)))["label"] == "sustained burst"
    assert pat([0, 30, 59])["label"] == "sporadic"
    assert pat([0, 1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 15, 16])["label"] == "intermittent"
    p = pat([0, 30])
    assert p["span_minutes"] == 31 and p["share_of_log_span"] == round(31 / 61, 3)
    assert analyze_pattern(group_events([LogEvent(1, "t", "x", message="m", level="ERROR")]).groups[0])["label"] == "no timestamps"


def test_impact_without_request_ids_or_status():
    r, _ = analyze([ev(1, msg="odd")])
    assert "cannot be measured" in r.observed_impact[0]


def test_reproduction_steps_include_call_path_and_sample():
    r, _ = analyze([ev(1, msg="Checkout failed", trace=TRACE)])
    assert r.reproduction_steps[0].startswith("Use the sample failure")
    assert any(s.startswith("Call path to exercise: connect") for s in r.reproduction_steps)


def test_report_is_json_serialisable():
    r, _ = analyze([ev(1, msg="x", trace=TRACE, rid="a")], retrieval=RetrievalResult([ctx(True)], "stack_trace"))
    d = json.loads(json.dumps(r.to_dict()))
    assert d["observed_evidence"][0].keys() == {"text", "source"} and d["generated_by"] == "deterministic-rules"


def test_only_warning_groups_count_as_precursors():
    """An earlier ERROR group that happens to mention 'connection' is not a precursor warning."""
    early_error = [ev(i, msg="Connection refused to cache host", service="Cache", minute=1 + i) for i in range(3)]
    target = [ev(20 + i, msg="Checkout failed", trace=TRACE, minute=10 + i) for i in range(4)]
    res = group_events(early_error + target)
    g = next(x for x in res.groups if x.exception_type == "DatabaseConnectionTimeout")
    assert g.first_seen > next(x for x in res.groups if x.exception_type is None).first_seen
    r = RootCauseAnalyzer().analyze(g, None, res.groups, (T0, T0 + timedelta(minutes=60)))
    assert not any("began" in e.text for e in r.observed_evidence)
    assert not any("earlier warning" in b for b in r.confidence_basis)
