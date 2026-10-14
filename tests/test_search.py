from code_analyzer.search import CodeIndex, tokenize
from tests.helpers import write_repo

FILES = {
    "src/db.py": "class Pool:\n    def acquire_connection(self):\n        raise TimeoutError('database connection timeout')\n",
    "src/pay.py": "def charge(order):\n    return order.total * 2\n",
    "web/ui.js": "function renderButton() {\n  return 'button';\n}\n",
}


def test_tokenize_splits_identifiers():
    t = tokenize("DatabaseConnectionTimeout acquire_connection HTTPServer")
    assert {"database", "connection", "timeout", "acquire", "databaseconnectiontimeout", "http", "server"} <= set(t)
    assert "the" not in tokenize("the cat")


def test_bm25_ranks_relevant_chunk_first(tmp_path):
    idx = CodeIndex.build(write_repo(tmp_path, FILES))
    top = idx.search("database connection timeout", k=3)
    assert top[0][0].qualname == "Pool.acquire_connection"
    assert idx.search("charge order")[0][0].qualname == "charge"


def test_camel_case_query_matches_snake_case_code(tmp_path):
    idx = CodeIndex.build(write_repo(tmp_path, FILES))
    assert idx.search("acquireConnection")[0][0].qualname == "Pool.acquire_connection"


def test_language_filter_and_min_terms(tmp_path):
    idx = CodeIndex.build(write_repo(tmp_path, FILES))
    assert all(c.language == "javascript" for c, _ in idx.search("button render", language="javascript"))
    assert idx.search("button charge", min_terms=2) == []


def test_empty_and_unmatched_queries(tmp_path):
    idx = CodeIndex.build(write_repo(tmp_path, FILES))
    assert idx.search("") == [] and idx.search("zzzqqq") == []
    (tmp_path / "empty").mkdir()
    assert CodeIndex.build(tmp_path / "empty").search("anything") == []


def test_symbol_and_file_lookups(tmp_path):
    idx = CodeIndex.build(write_repo(tmp_path, FILES))
    assert [c.file for c in idx.find_symbol("charge")] == ["src/pay.py"]
    assert idx.enclosing("src/db.py", 3).qualname == "Pool.acquire_connection"
    assert idx.enclosing("src/db.py", 1) is None
    assert idx.get_lines("src/pay.py", 0, 99) == [(1, "def charge(order):"), (2, "    return order.total * 2")]
    assert idx.by_basename["db.py"] == ["src/db.py"]
    assert idx.build_seconds >= 0
