import shutil

from code_analyzer.retriever import CodeRetriever
from code_analyzer.search import CodeIndex
from log_analyzer.extractor import parse_exception_chain
from log_analyzer.grouper import group_events
from log_analyzer.ingest import parse_log_file
from scripts.generate_demo_log import OUT, SRC

PROJECT = SRC.parent


def _setup(project=PROJECT):
    parsed = parse_log_file(OUT)
    return parsed, group_events(parsed.events), CodeRetriever(CodeIndex.build(project))


def _line_of(rel, marker):
    lines = (PROJECT / rel).read_text(encoding="utf-8").splitlines()
    return next(i for i, l in enumerate(lines, 1) if marker in l)


def test_every_frame_in_the_demo_log_is_verified_against_real_source():
    parsed, _, rt = _setup()
    frames = {(f.file, f.line, f.function, f.code)
              for e in parsed.events if e.continuation
              for f in parse_exception_chain(e.continuation).all_frames}
    assert len(frames) >= 6
    for file, line, func, code in frames:
        from log_analyzer.extractor import Frame
        ctx = rt.retrieve_for_frame(Frame(file, line, func, code, "python"))
        assert ctx.status == "verified_exact" and ctx.verified, (file, line, ctx.status, ctx.note)
        assert ctx.snippet_text(numbered=False).count(code.strip()) >= 1


def test_root_cause_group_retrieves_the_real_raise_site():
    _, res, rt = _setup()
    g = next(g for g in res.groups if g.exception_type == "DatabaseConnectionTimeout")
    r = rt.retrieve_for_group(g)
    assert r.strategy == "stack_trace" and len(r.verified_contexts) == len(r.contexts) == 4
    first = r.contexts[0]
    assert first.file_path == "src/database.py" and first.qualname == "Database._acquire_connection"
    assert first.target_line == _line_of("src/database.py", "raise DatabaseConnectionTimeout(")
    assert "raise DatabaseConnectionTimeout(" in first.snippet_text()
    charge = next(c for c in r.contexts if c.qualname == "PaymentService.charge")
    assert "self.db.execute(query" in charge.snippet_text()
    assert [x["name"] for x in charge.related_functions] == ["Database.execute"]
    assert first.imports == ["import time"]


def test_message_only_group_is_located_but_marked_unverified():
    _, res, rt = _setup()
    g = next(g for g in res.groups if g.title.startswith("Database connection timeout while charging"))
    r = rt.retrieve_for_group(g)
    assert r.strategy == "message" and not r.verified_contexts
    assert r.contexts[0].target_line == _line_of("src/payment_service.py", "logger.error(")
    assert r.contexts[0].qualname == "PaymentService.charge"


def test_keyerror_group_maps_to_checkout():
    _, res, rt = _setup()
    g = next(g for g in res.groups if g.exception_type == "KeyError")
    ctx = rt.retrieve_for_group(g).contexts[0]
    assert ctx.verified and ctx.file_path == "src/checkout.py"
    assert ctx.target_line == _line_of("src/checkout.py", 'order["currency"]')


def test_edited_source_is_reported_as_moved_not_verified(tmp_path):
    proj = tmp_path / "project"
    shutil.copytree(PROJECT, proj)
    db = proj / "src" / "database.py"
    db.write_text("# added\n# lines\n# here\n" + db.read_text(encoding="utf-8"), encoding="utf-8")
    _, res, rt = _setup(proj)
    g = next(g for g in res.groups if g.exception_type == "DatabaseConnectionTimeout")
    r = rt.retrieve_for_group(g)
    db_ctx = [c for c in r.contexts if c.file_path == "src/database.py"]
    assert db_ctx and all(c.status == "line_moved" and not c.verified for c in db_ctx)
    assert db_ctx[0].target_line == _line_of("src/database.py", "raise DatabaseConnectionTimeout(") + 3
    assert any(c.verified for c in r.contexts)  # unchanged files still verify


def test_cli_runs_on_demo_data(capsys=None):
    import contextlib
    import io
    from scripts.analyze_cli import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main([])
    out = buf.getvalue()
    assert code == 0 and "code strategy: stack_trace" in out and "VERIFIED" in out
    assert "OBSERVED EVIDENCE" in out and "INFERENCE (hypothesis, not confirmed)" in out
    assert "raise DatabaseConnectionTimeout(" in out
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(["--log", "does_not_exist.log"]) == 2
        assert main(["--group", "G999"]) == 1


def test_cli_with_ollama_over_real_http_and_fallback_when_server_down():
    import contextlib
    import io
    import os
    import socket

    from scripts.analyze_cli import main
    from tests.fakes import FakeLLMServer, good_reply

    def run_cli(host):
        old = {k: os.environ.get(k) for k in ("OLLAMA_HOST", "AI_TOP_N", "AI_PROVIDER")}
        os.environ.update({"OLLAMA_HOST": host, "AI_TOP_N": "1"})
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = main(["--ai", "ollama", "--group", "G001"])
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        return code, buf.getvalue()

    with FakeLLMServer(replies=[good_reply()]) as srv:
        code, out = run_cli(srv.url)
    assert code == 0 and "AI: ollama:qwen2.5-coder:7b | refined 1/1" in out and "AI confidence" in out
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    code, out = run_cli(f"http://127.0.0.1:{port}")
    assert code == 0 and "fallback for G001: LLM unavailable" in out and "OBSERVED EVIDENCE" in out


def test_cli_export_writes_jira_ready_report(tmp_path=None):
    import contextlib
    import io
    import tempfile
    from pathlib import Path

    from scripts.analyze_cli import main
    with tempfile.TemporaryDirectory() as d:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert main(["--group", "G005", "--export", d]) == 0
        files = sorted(p.name for p in Path(d).iterdir())
        assert files == ["bug-report-G005.jira.txt", "bug-report-G005.json", "bug-report-G005.md", "bug-report-G005.txt"]
        md = (Path(d) / "bug-report-G005.md").read_text(encoding="utf-8")
        assert "KeyError" in md and 'order["currency"]' in md and "Wrote" in buf.getvalue()
