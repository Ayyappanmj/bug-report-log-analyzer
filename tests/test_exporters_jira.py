import json

from pytest import raises

from config import Settings
from reports.exporters import export_bytes, safe_basename, write_exports
from reports.jira import JiraConfig, JiraError, build_ticket, create_issue, to_jira_payload
from tests.fakes import FakeJiraServer, demo_run


def ticket(gid="G001"):
    return build_ticket(demo_run(), gid)


def test_export_bytes_for_each_download_button():
    t = ticket()
    for fmt, (name, mime) in {"markdown": ("bug-report-G001.md", "text/markdown"), "text": ("bug-report-G001.txt", "text/plain"),
                              "json": ("bug-report-G001.json", "application/json"), "jira": ("bug-report-G001.jira.txt", "text/plain")}.items():
        n, m, data = export_bytes(t, fmt)
        assert (n, m) == (name, mime) and isinstance(data, bytes) and len(data) > 500
    with raises(ValueError):
        export_bytes(t, "pdf")


def test_json_export_round_trips_and_keeps_evidence_separate():
    d = json.loads(export_bytes(ticket(), "json")[2].decode("utf-8"))
    assert d["group_id"] == "G001" and d["review"]["status"].startswith("DRAFT")
    assert d["observed_evidence"][0].keys() == {"text", "source"} and d["root_cause_hypothesis"]
    assert d["environment"][0] == {"name": "Log file", "value": "production_sample.log"}
    assert d["confidence"]["heuristic"] > 0 and d["code"][0]["verified"] is True


def test_write_exports_creates_all_files_and_sanitizes_names(tmp_path):
    paths = write_exports(ticket(), tmp_path / "out" / "nested")
    assert sorted(p.name for p in paths) == ["bug-report-G001.jira.txt", "bug-report-G001.json", "bug-report-G001.md", "bug-report-G001.txt"]
    assert all(p.read_text(encoding="utf-8") for p in paths)
    t = ticket()
    t.group_id = "../../evil name"
    inside = write_exports(t, tmp_path / "safe", formats=("markdown",))[0]
    assert inside.parent == tmp_path / "safe" and inside.name == "bug-report-evil-name.md"
    assert safe_basename("..\\..\\x.py") == "x.py" and safe_basename("") == "bug-report"


def test_unicode_survives_export(tmp_path):
    t = ticket()
    t.summary = "Caf\u00e9 checkout \u2713 failed"
    p = write_exports(t, tmp_path, formats=("markdown",))[0]
    assert "Caf\u00e9 checkout \u2713" in p.read_text(encoding="utf-8")


def test_payload_fields_and_limits():
    t = ticket()
    t.title = "x" * 400
    payload = to_jira_payload(t, "PAY", "Bug")
    f = payload["fields"]
    assert f["project"] == {"key": "PAY"} and f["issuetype"] == {"name": "Bug"} and len(f["summary"]) == 255
    assert f["priority"] == {"name": "High"} and "log-analyzer" in f["labels"] and f["description"].startswith("h1.")
    assert "priority" not in to_jira_payload(t, "PAY", include_priority=False)["fields"]
    json.dumps(payload)


def test_create_issue_requires_confirmation_and_complete_config():
    with FakeJiraServer() as srv:
        with raises(JiraError) as no_confirm:
            create_issue(ticket(), JiraConfig(srv.url, "PAY", "tok", "me@x.com"))   # complete config, but no confirm=True
        assert "confirm" in str(no_confirm.value) and srv.requests == []            # and nothing was sent
    cfg = JiraConfig("https://jira.example", "PAY", "tok", "me@x.com")
    with raises(JiraError):
        create_issue(ticket(), JiraConfig("https://jira.example", "", ""), confirm=True)
    with raises(JiraError):
        create_issue(ticket(), JiraConfig("https://jira.example", "PAY", "tok", ""), confirm=True)
    with raises(JiraError):
        create_issue(ticket(), JiraConfig("ftp://jira.example", "PAY", "tok", "a@b.c"), confirm=True)
    with raises(JiraError):
        create_issue(ticket(), JiraConfig("https://u:p@jira.example", "PAY", "tok", "a@b.c"), confirm=True)
    with raises(JiraError):
        create_issue(ticket(), JiraConfig("https://jira.example", "PAY", "tok", "a@b.c", auth="magic"), confirm=True)


def test_create_issue_against_fake_jira_basic_and_bearer():
    import base64
    with FakeJiraServer() as srv:
        res = create_issue(ticket(), JiraConfig(srv.url + "/", "PAY", "TOKEN123", "me@x.com"), confirm=True, timeout=5)
        assert res == {"key": "PAY-12", "url": srv.url + "/browse/PAY-12"}
        req = srv.requests[0]
        assert req["path"] == "/rest/api/2/issue"
        assert req["headers"]["Authorization"] == "Basic " + base64.b64encode(b"me@x.com:TOKEN123").decode()
        assert req["body"]["fields"]["project"]["key"] == "PAY" and req["body"]["fields"]["description"].startswith("h1.")
        create_issue(ticket(), JiraConfig(srv.url, "PAY", "PATTOKEN", auth="bearer"), confirm=True, timeout=5)
        assert srv.requests[1]["headers"]["Authorization"] == "Bearer PATTOKEN"


def test_jira_errors_never_leak_the_token():
    with FakeJiraServer() as srv:
        srv.status, srv.reply = 400, {"errorMessages": ["Project is invalid"], "errors": {"priority": "Priority name 'High' is not valid"}}
        cfg = JiraConfig(srv.url, "PAY", "TOKEN123", "me@x.com")
        with raises(JiraError) as ei:
            create_issue(ticket(), cfg, confirm=True, timeout=5)
        msg = str(ei.value)
        assert "HTTP 400" in msg and "Project is invalid" in msg and "TOKEN123" not in msg and "TOKEN123" not in repr(cfg)
        srv.status, srv.reply = 201, {"id": "1"}
        with raises(JiraError):
            create_issue(ticket(), cfg, confirm=True, timeout=5)          # no key in response
    with raises(JiraError) as ei2:
        create_issue(ticket(), JiraConfig("http://127.0.0.1:9", "PAY", "TOKEN123", "me@x.com"), confirm=True, timeout=2)
    assert "Cannot reach Jira" in str(ei2.value) and "TOKEN123" not in str(ei2.value)


def test_jira_settings_from_env_and_config():
    s = Settings.from_env(env={"JIRA_BASE_URL": "https://j.example", "JIRA_EMAIL": "a@b.c", "JIRA_API_TOKEN": "t0k",
                               "JIRA_PROJECT_KEY": "PAY", "JIRA_AUTH": "BEARER"})
    assert "t0k" not in repr(s)
    c = JiraConfig.from_settings(s)
    assert (c.base_url, c.project_key, c.auth, c.issue_type) == ("https://j.example", "PAY", "bearer", "Bug")
    assert Settings.from_env(env={}).jira_base_url == ""
