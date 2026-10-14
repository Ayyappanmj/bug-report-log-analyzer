import copy
import io

from pytest import raises

from reports.exporters import render_markdown
from reports.jira import JiraTicket, apply_review, build_ticket
from tests.fakes import demo_run
from ui import viewmodels as vm


def run_dict():
    return demo_run().to_dict()


def test_dashboard_cards_are_the_six_required_metrics_from_the_run():
    d = run_dict()
    cards = vm.dashboard_cards(d)
    assert [c["label"] for c in cards] == ["Total Events", "Unique Errors", "Critical Errors", "Recurring Errors",
                                           "Files Analyzed", "Analysis Duration"]
    assert cards[0]["value"] == f"{d['dashboard']['total_events']:,}" and cards[4]["value"] == "3"
    assert cards[5]["value"].endswith(" s") and all(c["help"] for c in cards)


def test_groups_rows_filtering_and_columns():
    d = run_dict()
    rows = vm.groups_rows(d)
    assert len(rows) == len(d["grouping"]["groups"]) and rows[0]["ID"] == "G001" and rows[0]["Severity"] == "🟠 HIGH"
    assert rows[0]["Source code"] == "✅ verified" and "G002" in rows[0]["Related"]
    assert [r["ID"] for r in vm.groups_rows(d, severities=["CRITICAL"])] == ["G004"]
    assert all(r["Count"] >= 100 for r in vm.groups_rows(d, min_count=100))
    assert [r["ID"] for r in vm.groups_rows(d, query="keyerror")] == ["G005"]
    assert [r["ID"] for r in vm.groups_rows(d, query="HealthCheck")] == ["G004"]
    assert vm.groups_rows(d, query="zzzz") == []
    unanalyzed = copy.deepcopy(d)
    unanalyzed["reports"] = {}
    assert vm.groups_rows(unanalyzed)[0]["Source code"] == "not analyzed yet"


def test_timeline_rows_fill_gaps():
    g = {"timeline": {"2026-09-30 10:00": 3, "2026-09-30 10:03": 1}}
    assert vm.timeline_rows(g) == [("2026-09-30 10:00", 3), ("2026-09-30 10:01", 0), ("2026-09-30 10:02", 0), ("2026-09-30 10:03", 1)]
    assert vm.timeline_rows({"timeline": {}}) == []
    d = run_dict()
    rows = vm.timeline_rows(vm.group_by_id(d, "G001"))
    assert sum(c for _, c in rows) == vm.group_by_id(d, "G001")["count"]


def test_timings_severity_parse_quality_and_ai_summary():
    d = run_dict()
    assert [r["Stage"] for r in vm.timing_rows(d)][-1] == "Total" and all(r["Seconds"] >= 0 for r in vm.timing_rows(d))
    sc = vm.severity_counts(d)
    assert sc["CRITICAL"] == 1 and sum(sc.values()) == len(d["grouping"]["groups"])
    q = vm.parse_quality(d)
    assert q["unparsed"] == 2 and q["events"] == d["dashboard"]["total_events"]
    assert "2 line(s)" in vm.unparsed_warning(d)
    assert vm.ai_summary(d)["attempted"] == 0 and vm.ai_summary(d)["provider"].startswith("none")
    empty = copy.deepcopy(d)
    empty["parse_stats"].update(events=0, unparsed_lines=0, total_lines=5)
    assert "No log events were recognized" in vm.unparsed_warning(empty)
    empty["parse_stats"].update(total_lines=0)
    assert vm.unparsed_warning(empty) is None


def test_confidence_and_evidence_text():
    r = vm.report_for(run_dict(), "G001")
    assert "heuristic score, not a probability" in vm.confidence_text(r) and "fairly high" in vm.confidence_text(r)
    assert vm.confidence_text({"confidence": 0.2}).startswith("0.20 (low")
    assert all("*source:" in l for l in vm.evidence_lines(r)) and vm.report_for(run_dict(), "G999") is None


def test_status_labels_and_snippets():
    assert vm.status_label("verified_exact") == "✅ verified" and "not verified" in vm.status_label("line_moved")
    assert vm.status_label("something_new") == "something_new"
    ctx = vm.report_for(run_dict(), "G001")["code_context"][0]
    text = vm.numbered_snippet(ctx)
    marked = [l for l in text.split("\n") if l.startswith(">")]
    assert len(marked) == 1 and "raise DatabaseConnectionTimeout(" in marked[0] and f"{ctx['target_line']:>5}" in marked[0]
    assert vm.language_for_streamlit("python") == "python" and vm.language_for_streamlit("cobol") is None


def test_repo_path_resolution(tmp_path):
    assert vm.resolve_repo_path("") is None and vm.resolve_repo_path("   ") is None
    assert vm.resolve_repo_path(f'"{tmp_path}"') == tmp_path
    with raises(vm.InputError):
        vm.resolve_repo_path(str(tmp_path / "missing"))
    f = tmp_path / "a.py"
    f.write_text("x")
    with raises(vm.InputError):
        vm.resolve_repo_path(str(f))


def test_log_source_checks(tmp_path):
    assert vm.check_log_source("app.log", 100, "", 50) == ("upload", "app.log")
    for args in (("app.exe", 100, "", 50), ("big.log", 60 * 1024 * 1024, "", 50), (None, None, "", 50),
                 (None, None, str(tmp_path / "nope.log"), 50)):
        with raises(vm.InputError):
            vm.check_log_source(*args)
    p = tmp_path / "x.log"
    p.write_text("hi\n")
    assert vm.check_log_source(None, None, f'"{p}"', 50) == ("path", str(p))
    assert vm.check_log_source("a.log", 1, str(p), 50)[0] == "upload"        # upload wins over a typed path


def test_preview_lines_from_bytes_and_path(tmp_path):
    data = ("line %d\n" * 100 % tuple(range(100))).encode()
    assert vm.preview_lines(data, 3) == ["line 0", "line 1", "line 2"]
    assert len(vm.preview_lines(vm.DEMO_LOG, 40)) == 40 and vm.preview_lines(b"", 5) == []
    assert vm.DEMO_LOG.exists() and (vm.DEMO_PROJECT / "src").is_dir()
    long = ("x" * 5000 + "\n").encode()
    assert len(vm.preview_lines(long, 1)[0]) < 500


def test_ticket_round_trip_through_dict_for_history():
    t = build_ticket(demo_run(), "G001")
    t2 = JiraTicket.from_dict(__import__("json").loads(__import__("json").dumps(t.to_dict())))
    assert render_markdown(t2) == render_markdown(t) and t2.environment == t.environment


def test_apply_review_edits_and_marks_reviewed():
    t = build_ticket(demo_run(), "G001")
    r = apply_review(t, title="Checkout fails when DB pool is exhausted", priority="Highest", suggested_fix=["Fix A", "", "Fix B"],
                     steps_to_reproduce=["one", "two"], reviewer="Sam", reviewed=True)
    assert r.title.startswith("Checkout fails") and r.priority == "Highest" and "Set by reviewer" in r.priority_rationale
    assert r.suggested_fix == ["Fix A", "Fix B"] and r.steps_to_reproduce == ["one", "two"]
    assert r.review["status"].startswith("REVIEWED by Sam on ") and r.review["checked"]
    md = render_markdown(r)
    assert "Reviewed by a human (edited: priority, steps_to_reproduce, suggested_fix, title)." in md and "- [x] Confirm" in md
    assert t.title != r.title and t.review["status"].startswith("DRAFT")           # original untouched
    assert "[ ] Confirm" in render_markdown(t) and "A human must review it" in render_markdown(t)


def test_apply_review_redacts_edits_and_validates():
    t = build_ticket(demo_run(), "G001")
    r = apply_review(t, summary="Seen with password=hunter2", title="x" * 400)
    assert "hunter2" not in r.summary and len(r.title) == 255 and r.redactions["secret_assignment"] >= 1
    with raises(ValueError):
        apply_review(t, priority="Urgent!!")
    same = apply_review(t)
    assert same.title == t.title and same.extra.get("edited_fields") == [] and same.review["status"].startswith("DRAFT")
