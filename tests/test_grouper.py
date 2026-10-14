from datetime import datetime, timedelta

from log_analyzer.grouper import event_severity, group_events
from log_analyzer.models import LogEvent

T0 = datetime(2026, 9, 30, 10, 0, 0)
TRACE = ["Traceback (most recent call last):", '  File "src/db.py", line 5, in connect',
         "    raise DbTimeout()", "DbTimeout: timed out after {n}s"]


def ev(n, level="ERROR", msg="boom", service="Svc", rid=None, trace=None, status=None, ts=True):
    return LogEvent(line_no=n, fmt="t", raw=msg, message=msg, level=level, service=service,
                    request_id=rid, http_status=status, continuation=list(trace or []),
                    timestamp=T0 + timedelta(seconds=n) if ts else None)


def test_same_exception_different_values_is_one_group():
    events = [ev(1, trace=[l.format(n=5) for l in TRACE]), ev(2, trace=[l.format(n=7) for l in TRACE])]
    r = group_events(events)
    assert len(r.groups) == 1 and r.groups[0].count == 2
    assert r.groups[0].exception_type == "DbTimeout" and r.groups[0].raise_site == "src/db.py:connect"


def test_different_exceptions_are_separate():
    other = ["Traceback (most recent call last):", '  File "src/x.py", line 1, in f', "ValueError: bad"]
    r = group_events([ev(1, trace=[l.format(n=1) for l in TRACE]), ev(2, trace=other)])
    assert len(r.groups) == 2


def test_message_groups_mask_ids_and_split_by_service():
    r = group_events([ev(1, msg="failed order=ORD-1"), ev(2, msg="failed order=ORD-2"),
                      ev(3, msg="failed order=ORD-3", service="Other")])
    assert sorted(g.count for g in r.groups) == [1, 2]


def test_non_problem_events_are_ignored_but_counted():
    r = group_events([ev(1, level="INFO"), ev(2, level="DEBUG"), ev(3, level="ERROR")])
    assert r.summary["total_events"] == 3 and r.summary["issue_events"] == 1


def test_severity_mapping():
    assert event_severity(ev(1, level="CRITICAL"), False) == "CRITICAL"
    assert event_severity(ev(1, level="ERROR"), False) == "HIGH"
    assert event_severity(ev(1, level="WARN"), False) == "MEDIUM"
    assert event_severity(ev(1, level="INFO"), False) is None
    assert event_severity(ev(1, level="INFO", status=502), False) == "MEDIUM"
    assert event_severity(ev(1, level="INFO", status=404), False) is None
    assert event_severity(ev(1, level="INFO"), True) == "MEDIUM"
    assert event_severity(ev(1, level=None), False) is None


def test_group_severity_is_highest_level_seen():
    r = group_events([ev(1, level="WARN", msg="same"), ev(2, level="WARN", msg="same")])
    assert r.groups[0].severity == "MEDIUM"


def test_first_last_seen_lines_and_timeline():
    r = group_events([ev(5, msg="x"), ev(65, msg="x"), ev(30, msg="x")])
    g = r.groups[0]
    assert (g.first_seen, g.last_seen) == (T0 + timedelta(seconds=5), T0 + timedelta(seconds=65))
    assert (g.first_line, g.last_line, g.count) == (5, 65, 3)
    assert g.timeline == {"2026-09-30 10:00": 2, "2026-09-30 10:01": 1}


def test_ranking_severity_and_frequency():
    events = [ev(1, level="CRITICAL", msg="crit")] + [ev(10 + i, msg="frequent") for i in range(100)] \
             + [ev(200, msg="rare")] + [ev(300, level="WARN", msg="warn")]
    r = group_events(events)
    assert [g.title for g in r.groups] == ["frequent", "crit", "rare", "warn"]
    assert [g.id for g in r.groups] == ["G001", "G002", "G003", "G004"]


def test_summary_counts():
    events = [ev(1, level="CRITICAL", msg="c"), ev(2, msg="e"), ev(3, msg="e"), ev(4, msg="once"),
              ev(5, level="WARN", msg="w"), ev(6, level="WARN", msg="w"), ev(7, level="INFO")]
    s = group_events(events).summary
    assert s == {"total_events": 7, "issue_events": 6, "error_events": 4, "warning_events": 2,
                 "group_count": 4, "error_groups": 3, "critical_groups": 1, "warning_groups": 1,
                 "recurring_error_groups": 1, "overflow_events": 0}


def test_related_groups_via_shared_request_ids():
    events = []
    for i in range(3):
        events.append(ev(10 + i, msg="db timeout", service="Pay", rid=f"r{i}"))
        events.append(ev(20 + i, msg="checkout failed", service="Chk", rid=f"r{i}"))
    events.append(ev(99, msg="unrelated", service="Other", rid="zzz"))
    r = group_events(events)
    by_title = {g.title: g for g in r.groups}
    assert by_title["checkout failed"].id in by_title["db timeout"].related
    assert by_title["unrelated"].related == []


def test_single_shared_request_is_not_enough_to_relate():
    r = group_events([ev(1, msg="a", rid="r1"), ev(2, msg="b", rid="r1")])
    assert all(g.related == [] for g in r.groups)


def test_context_before_and_after():
    events = [ev(i, level="INFO", msg=f"ctx {i}") for i in range(1, 6)] + [ev(6, msg="problem")] \
             + [ev(i, level="INFO", msg=f"after {i}") for i in range(7, 12)]
    g = group_events(events).groups[0]
    assert g.context_before[-1].startswith("line 5") and len(g.context_before) == 5
    assert [c.split()[1] for c in g.context_after] == ["7", "8", "9"]


def test_similar_messages_are_merged_but_dissimilar_are_not():
    a = "Connection to upstream host payments-a failed after retries"
    b = "Connection to upstream host payments-b failed after retries"
    c = "Disk quota exceeded for tenant reporting batch"
    r = group_events([ev(1, msg=a), ev(2, msg=b), ev(3, msg=c)])
    assert sorted(g.count for g in r.groups) == [1, 2]


def test_events_without_timestamps():
    g = group_events([ev(1, msg="x", ts=False), ev(2, msg="x", ts=False)]).groups[0]
    assert g.count == 2 and g.first_seen is None and g.timeline == {}


def test_http_500_info_event_becomes_issue():
    r = group_events([ev(1, level="INFO", msg="POST /pay 500 12ms", status=500)])
    assert r.groups[0].severity == "MEDIUM" and dict(r.groups[0].http_statuses) == {500: 1}


def test_empty_input():
    r = group_events([])
    assert r.groups == [] and r.summary["total_events"] == 0 and r.summary["error_groups"] == 0


def test_to_dict_is_json_serialisable():
    import json
    r = group_events([ev(1, trace=[l.format(n=5) for l in TRACE], rid="a")])
    json.dumps(r.to_dict())


def test_numbers_in_exception_messages_never_split_groups():
    """Normalization (not just the fuzzy merge) must make these one group: the raw messages are too different to merge."""
    def trace(msg):
        return ["Traceback (most recent call last):", '  File "src/db.py", line 5, in connect', "    raise DbTimeout()", f"DbTimeout: {msg}"]
    r = group_events([ev(1, trace=trace("timed out after 5s")), ev(2, trace=trace("timed out after 123456789s")),
                      ev(3, trace=trace("timed out after 42s"))])
    assert len(r.groups) == 1 and r.groups[0].count == 3 and r.groups[0].normalized_message == "timed out after <N>s"
