from log_analyzer.grouper import group_events
from log_analyzer.ingest import parse_log_file
from scripts.generate_demo_log import OUT


def _run():
    parsed = parse_log_file(OUT)
    return parsed, group_events(parsed.events), OUT.read_text(encoding="utf-8")


def test_totals_come_from_the_file():
    parsed, res, _ = _run()
    assert res.summary["total_events"] == parsed.stats.events
    assert res.summary["error_events"] + res.summary["warning_events"] == res.summary["issue_events"]
    assert sum(g.count for g in res.groups) == res.summary["issue_events"]
    assert res.summary["issue_events"] == sum(
        parsed.stats.events_by_level[l] for l in ("WARN", "ERROR", "CRITICAL"))


def test_timeout_root_cause_group_matches_raw_counts():
    _, res, raw = _run()
    g = next(g for g in res.groups if g.exception_type == "DatabaseConnectionTimeout")
    assert g.count == raw.count("DatabaseConnectionTimeout: Timed out after")
    assert g.raise_site == "src/database.py:_acquire_connection"
    assert g.surfaced_type == "CheckoutError"
    assert g.severity == "HIGH" and g.is_recurring and g.has_stack_trace
    assert [f.function for f in g.frames] == ["_acquire_connection", "execute", "charge", "process_checkout"]
    assert [f.function for f in g.frames_surfaced] == ["process_checkout"]


def test_keyerror_incident_is_separate_group():
    _, res, raw = _run()
    g = next(g for g in res.groups if g.exception_type == "KeyError")
    assert g.count == raw.count("KeyError: 'currency'") == 3
    assert g.raise_site == "src/checkout.py:process_checkout"


def test_critical_group_and_warning_groups():
    _, res, raw = _run()
    crit = [g for g in res.groups if g.severity == "CRITICAL"]
    assert len(crit) == 1 and crit[0].count == raw.count(" CRITICAL ") and crit[0].services == {"HealthCheck": 1}
    assert res.summary["critical_groups"] == 1
    warn_titles = " ".join(g.title for g in res.groups if g.severity == "MEDIUM")
    assert "Slow database call" in warn_titles and "Connection pool utilization" in warn_titles


def test_payment_and_checkout_groups_are_linked():
    _, res, _ = _run()
    chain = next(g for g in res.groups if g.exception_type == "DatabaseConnectionTimeout" and g.kind == "exception")
    msg = next(g for g in res.groups if g.title.startswith("Database connection timeout while charging"))
    assert msg.id in chain.related and chain.id in msg.related
    assert chain.count == msg.count


def test_root_cause_group_ranks_in_top_two():
    _, res, _ = _run()
    assert "DatabaseConnectionTimeout" in [g.exception_type for g in res.groups[:2]]


def test_incident_window_from_timeline():
    _, res, _ = _run()
    g = next(g for g in res.groups if g.exception_type == "DatabaseConnectionTimeout")
    assert g.first_seen.strftime("%H:%M") >= "10:20" and g.last_seen.strftime("%H:%M") <= "10:35"
