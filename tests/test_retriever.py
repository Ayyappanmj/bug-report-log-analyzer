from types import SimpleNamespace

from code_analyzer.retriever import CodeRetriever, _literal_fragment
from code_analyzer.search import CodeIndex
from log_analyzer.extractor import Frame
from tests.helpers import write_repo

PAY = '''import logging
from db import Db

logger = logging.getLogger("pay")


def charge(order):
    total = order.total
    try:
        result = Db().execute(total)
    except TimeoutError:
        logger.error("Charge failed for order=%s after retries", order.id)
        raise PaymentError("charge failed")
    return result
'''
DB = '''class Db:
    def execute(self, q):
        return q
'''


def make(tmp_path, files=None):
    write_repo(tmp_path, files or {"src/pay.py": PAY, "src/db.py": DB})
    return CodeRetriever(CodeIndex.build(tmp_path))


def pyframe(line=10, code="result = Db().execute(total)", func="charge", file="src/pay.py"):
    return Frame(file, line, func, code, "python")


def test_verified_exact_by_code_text(tmp_path):
    c = make(tmp_path).retrieve_for_frame(pyframe())
    assert (c.status, c.verified, c.verification) == ("verified_exact", True, "code_text")
    assert c.file_path == "src/pay.py" and c.target_line == 10 and c.qualname == "charge"
    assert (c.start_line, c.end_line) == (1, 14) or c.start_line == 1
    assert any(n == 10 and "execute" in t for n, t in c.snippet)
    assert c.imports == ["import logging", "from db import Db"] and c.module == "src.pay"
    assert c.function_range == (7, 14)
    assert c.related_functions and c.related_functions[0]["name"] == "Db.execute"


def test_line_moved_is_not_verified(tmp_path):
    c = make(tmp_path).retrieve_for_frame(pyframe(line=6))
    assert (c.status, c.verified, c.target_line) == ("line_moved", False, 10)
    assert "NOT verified" in c.note and "line 10" in c.note


def test_code_changed_shows_function_but_not_verified(tmp_path):
    c = make(tmp_path).retrieve_for_frame(pyframe(code="total = other()"))
    assert (c.status, c.verified, c.qualname) == ("function_only", False, "charge")
    assert c.target_line == 7


def test_line_mismatch_and_file_only(tmp_path):
    rt = make(tmp_path)
    c = rt.retrieve_for_frame(pyframe(code="nothing like this", func="gone"))
    assert (c.status, c.verified) == ("line_mismatch", False)
    c = rt.retrieve_for_frame(pyframe(line=999, code="nothing", func="gone"))
    assert c.status == "file_only" and c.snippet == [] and not c.verified


def test_path_styles_resolve_to_same_file(tmp_path):
    rt = make(tmp_path)
    for p in ("/app/src/pay.py", "C:\\app\\src\\pay.py", "pay.py", "./src/pay.py"):
        assert rt.retrieve_for_frame(pyframe(file=p)).file_path == "src/pay.py", p


def test_external_frames_are_skipped(tmp_path):
    c = make(tmp_path).retrieve_for_frame(pyframe(file="/usr/lib/python3.11/site-packages/requests/api.py"))
    assert c.status == "external" and c.file_path is None


def test_ambiguous_basename_and_disambiguation(tmp_path):
    files = {"a/util.py": "def one():\n    return 1\n", "b/util.py": "def one():\n    return 2\n\ndef two():\n    pass\n"}
    rt = make(tmp_path, files)
    amb = rt.retrieve_for_frame(Frame("util.py", 2, "one", "return 1", "python"))
    assert amb.status == "ambiguous_file" and sorted(amb.alternatives) == ["a/util.py", "b/util.py"]
    assert not amb.verified and amb.snippet == []
    assert rt.retrieve_for_frame(Frame("util.py", 5, "two", "pass", "python")).file_path == "b/util.py"
    assert rt.retrieve_for_frame(Frame("/x/a/util.py", 2, "one", "return 1", "python")).file_path == "a/util.py"


def test_java_frame_uses_package_path_and_function_name(tmp_path):
    java = "package com.acme;\n\npublic class Db {\n    public void acquire() {\n        int x = 1;\n    }\n}\n"
    rt = make(tmp_path, {"src/main/java/com/acme/Db.java": java, "other/Db.java": java.replace("acme", "z")})
    c = rt.retrieve_for_frame(Frame("Db.java", 5, "com.acme.Db.acquire", None, "java"))
    assert c.file_path == "src/main/java/com/acme/Db.java"
    assert (c.status, c.verified, c.verification) == ("verified_exact", True, "function_name")
    assert c.class_name == "Db"


def test_javascript_frame_without_function_is_unverified(tmp_path):
    js = "function handler(req) {\n  return req.id;\n}\n"
    rt = make(tmp_path, {"src/app.js": js})
    ok = rt.retrieve_for_frame(Frame("/srv/src/app.js", 2, "handler", None, "javascript"))
    assert ok.status == "verified_exact" and ok.verification == "function_name"
    weak = rt.retrieve_for_frame(Frame("/srv/src/app.js", 2, "<anonymous>", None, "javascript"))
    assert (weak.status, weak.verified) == ("line_unverified", False)


def test_symbol_fallback_when_file_missing(tmp_path):
    rt = make(tmp_path)
    c = rt.retrieve_for_frame(Frame("elsewhere/moved.py", 3, "charge", "x", "python"))
    assert (c.status, c.file_path, c.verified) == ("symbol_search", "src/pay.py", False)
    assert rt.retrieve_for_frame(Frame("elsewhere/moved.py", 3, "unknown_fn", "x", "python")).status == "not_found"
    assert rt.retrieve_for_frame(Frame("elsewhere/moved.py", 3, "<module>", "x", "python")).status == "not_found"


def test_literal_fragment_extraction():
    assert _literal_fragment("Charge failed for order=ORD-<N> after retries") == "Charge failed for order="
    assert _literal_fragment("Timed out after <N>s waiting for a connection (pool_size=<N>)") == "waiting for a connection (pool_size="
    assert _literal_fragment("<N>") is None and _literal_fragment("short <N>") is None


def test_message_exception_and_keyword_search(tmp_path):
    rt = make(tmp_path)
    m = rt.search_message("Charge failed for order=ORD-<N> after retries")
    assert m and m[0].status == "message_match" and m[0].target_line == 12 and not m[0].verified
    e = rt.search_exception("PaymentError")
    assert e and e[0].status == "exception_match" and e[0].target_line == 13
    k = rt.search_keywords("execute total charge")
    assert k and all(c.status == "keyword_search" and not c.verified for c in k)
    assert rt.search_keywords("zzz qqq") == [] and rt.search_message("nothing matches here <N>") == []


def group(frames=(), surfaced=(), msg="", exc=None, title="t"):
    return SimpleNamespace(frames=list(frames), frames_surfaced=list(surfaced), normalized_message=msg,
                           exception_type=exc, title=title)


def test_group_prefers_stack_trace_and_dedupes(tmp_path):
    rt = make(tmp_path)
    r = rt.retrieve_for_group(group([pyframe(), pyframe(line=10)], msg="Charge failed for order=<N>"))
    assert r.strategy == "stack_trace" and len(r.contexts) == 1 and r.verified_contexts
    assert r.notes == []


def test_group_skips_external_and_falls_back_to_message(tmp_path):
    rt = make(tmp_path)
    ext = pyframe(file="/usr/lib/python3.11/site-packages/x/y.py")
    r = rt.retrieve_for_group(group([ext], msg="Charge failed for order=ORD-<N> after retries"))
    assert r.strategy == "message" and r.external_frames and not r.verified_contexts
    assert any("not verified" in n for n in r.notes)


def test_group_falls_back_to_exception_then_keyword(tmp_path):
    rt = make(tmp_path)
    assert rt.retrieve_for_group(group(msg="zzz <N>", exc="PaymentError")).strategy == "exception"
    assert rt.retrieve_for_group(group(msg="zzz", title="execute total")).strategy == "keyword"


def test_group_with_nothing_found(tmp_path):
    r = make(tmp_path).retrieve_for_group(group(msg="qqq", title="qqq www"))
    assert r.strategy == "none" and r.contexts == [] and r.notes


def test_group_symbol_only_keeps_unverified_note(tmp_path):
    rt = make(tmp_path)
    r = rt.retrieve_for_group(group([Frame("gone/x.py", 1, "charge", "c", "python")]))
    assert r.strategy == "symbol" and r.contexts[0].status == "symbol_search"
    assert r.verified_contexts == [] and r.notes


def test_to_dict_is_json_serialisable(tmp_path):
    import json
    rt = make(tmp_path)
    json.dumps(rt.retrieve_for_group(group([pyframe()])).to_dict())
