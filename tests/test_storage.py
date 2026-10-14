import json
import sqlite3

from storage.database import HistoryDB, redact_obj
from tests.fakes import demo_run


def payload():
    run = demo_run()
    return run.to_dict()


def test_save_list_load_roundtrip(tmp_path):
    db = HistoryDB(tmp_path / "sub" / "h.db")
    d = payload()
    rid = db.save(d, {"G001": {"title": "t"}})
    rows = db.list()
    assert len(rows) == 1 and rows[0]["id"] == rid and rows[0]["log_name"] == "production_sample.log"
    assert rows[0]["total_events"] == d["dashboard"]["total_events"] and rows[0]["error_groups"] == d["dashboard"]["unique_errors"]
    loaded = db.load(rid)
    assert loaded["run"]["dashboard"] == d["dashboard"] and loaded["tickets"] == {"G001": {"title": "t"}}
    assert loaded["run"]["grouping"]["groups"][0]["id"] == "G001" and db.count() == 1


def test_payload_is_compressed(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    d = payload()
    db.save(d)
    raw_size = len(json.dumps(d).encode())
    stored = sqlite3.connect(tmp_path / "h.db").execute("SELECT length(payload) FROM runs").fetchone()[0]
    assert stored < raw_size / 3


def test_secrets_are_redacted_before_storing(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    d = payload()
    d["grouping"]["groups"][0]["samples"][0]["message"] = "login password=hunter2 mail bob@example.com"
    rid = db.save(d)
    text = json.dumps(db.load(rid))
    assert "hunter2" not in text and "bob@example.com" not in text and "<REDACTED:secret>" in text
    rid2 = db.save(d, redact_payload=False)
    assert "hunter2" in json.dumps(db.load(rid2))


def test_prune_delete_clear_and_missing(tmp_path):
    db = HistoryDB(tmp_path / "h.db", max_runs=3)
    ids = [db.save({"log_name": f"l{i}", "dashboard": {}}) for i in range(5)]
    assert db.count() == 3 and [r["id"] for r in db.list()] == ids[::-1][:3]
    assert db.load(ids[0]) is None and db.load(99999) is None
    assert db.delete(ids[-1]) is True and db.delete(ids[-1]) is False and db.count() == 2
    assert db.clear() == 2 and db.list() == []


def test_hostile_values_do_not_break_queries(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    evil = "x'); DROP TABLE runs;--"
    rid = db.save({"log_name": evil, "ai_provider": evil, "dashboard": {}})
    assert db.list()[0]["log_name"] == evil and db.count() == 1
    assert db.load(rid) is not None
    try:
        db.load("1 OR 1=1")
        raise AssertionError("ids must be integers")
    except ValueError:
        pass


def test_corrupt_payload_returns_none(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    rid = db.save({"log_name": "a", "dashboard": {}})
    con = sqlite3.connect(tmp_path / "h.db")
    con.execute("UPDATE runs SET payload = ?", (b"not zlib",))
    con.commit()
    con.close()
    assert db.load(rid) is None


def test_redact_obj_handles_nesting_and_non_strings():
    out = redact_obj({"a": ["token=abc123", {"b": 5, "c": None, "d": True}], "e": 1.5})
    assert out["a"][0] == "token=<REDACTED:secret>" and out["a"][1] == {"b": 5, "c": None, "d": True} and out["e"] == 1.5


def test_unicode_log_names(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    db.save({"log_name": "journal-\u00e9\u2713.log", "dashboard": {}})
    assert db.list()[0]["log_name"] == "journal-\u00e9\u2713.log"
