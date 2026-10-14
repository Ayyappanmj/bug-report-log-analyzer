"""Security regression tests. Each test names the attack it guards against."""
import ast
import json
import os
import re
import tempfile
import tracemalloc
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest import raises

from agent.orchestrator import AnalysisPipeline
from agent.root_cause_agent import EvidenceItem
from ai.api_provider import OptionalAPIProvider
from ai.base import AIProviderError
from ai.redaction import redact
from code_analyzer.scanner import scan_repository
from config import SAFE_OVERRIDES, Settings, apply_overrides
from log_analyzer.grouper import ErrorGrouper
from log_analyzer.ingest import iter_log_lines, parse_log_file, sanitize_line
from log_analyzer.models import LogEvent
from reports.exporters import render_markdown, render_wiki
from reports.jira import JiraConfig, JiraError, build_ticket, create_issue
from reports.sanitize import md_escape, wiki_escape
from scripts.generate_demo_log import OUT, SRC
from security.policy import DEMO_ROOT, PathPolicy, PolicyError
from tests.fakes import FakeLLMServer, FakeRedirectServer, demo_run
from tests.helpers import write_repo
from ui import viewmodels as vm

ROOT = Path(__file__).resolve().parent.parent
HOSTILE = "![x](https://evil.example/leak?d=1) [click](https://evil.example) <img src=x onerror=alert(1)> $\\href{x}{y}$ {panel} !https://evil.example/a.png!"


# ------------------------------------------------------------------ hostile log content: terminal tricks, look-alikes
def test_ansi_escape_sequences_cannot_reach_reports_or_terminals(tmp_path):
    p = tmp_path / "color.log"
    p.write_text("\x1b[31m2026-09-30 10:00:00 ERROR\x1b[0m [Svc] [T-1] [req=a1b2c3] \x1b]0;pwned title\x07boom \x1b[2J\x1b[1;1Hspoof\n", encoding="utf-8")
    r = parse_log_file(p)
    e = r.events[0]
    assert e.level == "ERROR" and e.service == "Svc" and e.message == "boom spoof"        # colored levels now parse, too
    assert "\x1b" not in e.raw and "pwned" not in e.raw


def test_control_characters_and_bidi_overrides_are_stripped():
    dirty = "ok\x00\x01\x07\x7f\u202eEVIL\u202c\u2066x\u2069\u200b\u0085\u009b end\ttab"
    assert sanitize_line(dirty) == "okEVILx end\ttab"                                  # tab survives: continuation lines need it
    assert sanitize_line("plain \u00e9\u2713 text") == "plain \u00e9\u2713 text"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "a.log"
        f.write_bytes("2026-09-30 10:00:00 INFO [S] [T] [req=1] \u202egnirts\n".encode("utf-8"))
        assert "\u202e" not in list(iter_log_lines(f))[0]


# ------------------------------------------------------------------ memory exhaustion
def test_group_count_is_capped_so_unique_messages_cannot_exhaust_memory():
    import random
    rng = random.Random(8)
    g = ErrorGrouper(max_groups=5)
    for i in range(20):
        word = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(25, 45)))
        g.add(LogEvent(i + 1, "t", "x", message=word, level="ERROR"))
    res = g.finalize()
    assert len(res.groups) == 6 and res.summary["overflow_events"] == 15 and sum(x.count for x in res.groups) == 20
    assert any("beyond the group limit" in x.title for x in res.groups)


@pytest.mark.slow
def test_default_group_cap_holds_for_a_flood_of_distinct_errors():
    g = ErrorGrouper()
    for i in range(22_000):
        g.add(LogEvent(i + 1, "t", "x", message="problem " + "".join(chr(97 + (i // 26 ** k) % 26) for k in range(5)) + " end", level="ERROR", service="S"))
    res = g.finalize()
    assert len(res.groups) <= 20_001 and res.summary["overflow_events"] == 22_000 - 20_000


@pytest.mark.slow
def test_pipeline_streams_events_instead_of_holding_them(tmp_path):
    from tests.test_large_files import write_big_log
    p = tmp_path / "s.log"
    write_big_log(p, 4 * 1024 * 1024)
    tracemalloc.start()
    parse_log_file(p)                                   # materializes every event
    list_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    tracemalloc.start()
    run = AnalysisPipeline(top_n=2).run(p, None)
    stream_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert run.parse_stats.events > 20_000 and stream_peak < list_peak * 0.5, (stream_peak, list_peak)
    t = run.timings
    assert t["parse"] >= 0 and t["group"] >= 0 and t["parse"] + t["group"] <= t["total"] + 1e-6


# ------------------------------------------------------------------ untrusted text must not become live links, images, HTML
def test_markup_escapers():
    escaped = md_escape(HOSTILE)
    assert escaped.count("\\[") == 2 and "![" not in escaped and not re.search(r"(?<!\\)[<>]", escaped)
    assert md_escape("a\x00b\x1bc") == "abc" and md_escape("$x$") == "$x$" and md_escape("$x$", ui=True) == "\\$x\\$"
    w = wiki_escape(HOSTILE)
    assert "\\!https" in w and "\\{panel\\}" in w and "\\[click\\]" in w and "!\\[" not in w.replace("\\!\\[", "")


def hostile_run():
    import copy
    run = copy.deepcopy(demo_run())
    rep = run.reports["G001"]
    rep.observed_evidence.append(EvidenceItem("Sample message: " + HOSTILE, "log line 1"))
    rep.probable_root_cause = "Cause " + HOSTILE
    rep.error_message = HOSTILE
    rep.alternative_possibilities = [HOSTILE]
    rep.recommended_fix = [HOSTILE]
    rep.stack_trace = "line with " + HOSTILE
    return run


LIVE_MD = re.compile(r"(?<!\\)!\[|(?<!\\)\]\(https?:|(?<!\\)<img\b")           # Markdown images, links, raw HTML
LIVE_WIKI = re.compile(r"(?<!\\)!https?://|(?<!\\)\[[^\]]*\|https?:|(?<!\\)\{panel")   # Jira wiki images, links, macros


def test_exports_do_not_contain_live_links_images_or_html():
    t = build_ticket(hostile_run(), "G001")
    md, wiki = render_markdown(t), render_wiki(t)
    prose_md = re.sub(r"```.*?```", "", md, flags=re.S)                   # fenced blocks are literal and cannot render markup
    prose_wiki = re.sub(r"\{code[^}]*\}.*?\{code\}", "", wiki, flags=re.S)
    assert not LIVE_MD.search(prose_md), LIVE_MD.search(prose_md)
    assert not LIVE_WIKI.search(prose_wiki), LIVE_WIKI.search(prose_wiki)
    assert "evil.example" in md and "evil.example" in wiki                                      # the text is kept, just inert
    assert "evil.example" in json.dumps(t.to_dict())                                          # JSON keeps the raw data


def test_ui_text_is_escaped_before_rendering():
    from tests.fake_streamlit import installed, page
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        os.environ["DB_PATH"] = str(Path(tmp) / "h.db")
        from ui import state as S
        S.init()
        S.load_demo()
        st.click("analyze")
        page("analyzer").render()
        d = st.session_state["run_dict"]
        g = d["grouping"]["groups"][0]
        g["title"], g["samples"][0]["message"] = HOSTILE, HOSTILE
        g["services"] = {HOSTILE: 1}
        d["log_name"] = HOSTILE
        rep = d["reports"]["G001"]
        rep["incident"], rep["probable_root_cause"], rep["inferred_impact"] = HOSTILE, HOSTILE, HOSTILE
        rep["observed_evidence"][0]["text"] = HOSTILE
        rep["observed_impact"], rep["alternative_possibilities"], rep["recommended_fix"] = [HOSTILE], [HOSTILE], [HOSTILE]
        rep["ai_enhanced"], rep["ai_provider"], rep["ai_caveats"], rep["ai_warnings"] = True, HOSTILE, [HOSTILE], [HOSTILE]
        rep["ai_supporting_evidence"] = [{"id": "E1", "text": HOSTILE}]
        rep["baseline_probable_root_cause"] = HOSTILE
        rep["code_context"][0]["note"] = HOSTILE
        st.calls.clear()
        for name in ("dashboard", "error_groups", "root_cause", "code_viewer"):
            page(name).render()
        offenders = []
        for kind, args, kw in st.calls:
            if kind in ("markdown", "write", "caption", "subheader", "info", "warning", "success", "error", "expander") and args:
                text = str(args[0])
                if LIVE_MD.search(text) or re.search(r"(?<!\\)\[click\]", text):
                    offenders.append((kind, text[:80]))
        assert not offenders, offenders
        assert any(k == "text" and HOSTILE in str(a[0]) for k, a, _ in st.calls)         # raw sample message goes through st.text
    os.environ.pop("DB_PATH", None)


# ------------------------------------------------------------------ secrets
def fake_secrets():
    """Built at runtime from pieces so this file never contains a complete secret-looking string."""
    return {
        "aws_key": "AK" + "IA" + "ABCDEFGHIJKLMNOP", "google_api_key": "AI" + "za" + "A" * 35, "stripe_key": "sk_" + "live_" + "a1B2c3D4e5F6g7H8i9",
        "npm_token": "npm_" + "a" * 36, "sendgrid_key": "SG." + "a" * 22 + "." + "b" * 43, "github_token": "gh" + "p_" + "c" * 36,
        "slack_token": "xo" + "xb-" + "1234567890-abcdefghij", "jwt": "ey" + "J" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12,
        "url_credentials": "postgres://admin:" + "s3cr3t" + "@db.internal:5432/app", "basic_auth": "Authorization: Ba" + "sic " + "dXNlcjpwYXNzd29yZDEyMzQ1Njc4OQ==",
        "azure_key": "AccountKey=" + "q" * 40, "bearer": "Bearer " + "x" * 30, "secret_assignment": "pass" + "word=hunter2",
        "card": "4111 1111 1111 1111", "email": "alice@example.com",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
    }


def test_every_secret_family_is_redacted():
    for name, secret in fake_secrets().items():
        r = redact(f"before {secret} after")
        assert r.counts[name] >= 1, name
        core = re.sub(r"^(Authorization: |AccountKey=|Bearer |postgres://admin:|pass" + "word=)", "", secret).split("@")[0]
        assert core not in r.text or name in ("email",) and "alice" not in r.text, name


def test_card_numbers_need_to_pass_the_luhn_check_and_look_like_cards():
    assert redact("card 4111 1111 1111 1111").counts["card"] == 1 and redact("4111-1111-1111-1111 x").counts["card"] == 1
    for harmless in ("4111 1111 1111 1112", "order 1234567890123456", "2026-09-30 10:22:14,123", "id 1000000000000", "tracking 99999999999999999"):
        assert redact(harmless).counts["card"] == 0, harmless


def test_no_false_positives_on_the_demo_log_and_demo_code():
    assert redact(OUT.read_text(encoding="utf-8")).total == 0
    for f in (SRC / "database.py", SRC / "payment_service.py", SRC / "checkout.py"):
        assert redact(f.read_text(encoding="utf-8")).total == 0, f.name


def test_repository_contains_no_secrets():
    """Dogfooding: run the redaction engine over every text file of the project (tests and docs hold deliberate fakes)."""
    hits = []
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if (not p.is_file() or rel.parts[0] in ("tests", "docs", ".git", "benchmarks") or p.suffix in (".zip", ".db", ".pyc")
                or "__pycache__" in rel.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found = redact(text, redact_emails=False)
        for noisy in ("secret_assignment", "card"):         # variable names such as api_key: str match the generic rule; not secrets
            found.counts.pop(noisy, None)
        if found.total:
            hits.append((str(rel), dict(found.counts)))
    assert not hits, hits
    assert not (ROOT / ".env").exists()


# ------------------------------------------------------------------ credentials and redirects
def test_api_key_is_never_forwarded_to_a_redirect_target():
    with FakeLLMServer() as victim, FakeRedirectServer(victim.url + "/v1/chat/completions") as hop:
        p = OptionalAPIProvider(hop.url + "/v1", "sk-test-SECRET-KEY-000000000000", "m")
        with raises(AIProviderError) as ei:
            p.generate("hi", timeout=5)
    assert "redirects are not followed" in str(ei.value) and "SECRET" not in str(ei.value)
    assert victim.requests == [] and "Authorization" in hop.requests[0]["headers"]          # the first hop saw it; the target never did


def test_jira_token_is_never_forwarded_to_a_redirect_target():
    from tests.fakes import FakeJiraServer
    with FakeJiraServer() as victim, FakeRedirectServer(victim.url + "/rest/api/2/issue") as hop:
        with raises(JiraError) as ei:
            create_issue(build_ticket(demo_run(), "G001"), JiraConfig(hop.url, "PAY", "TOKEN123", "a@b.c"), confirm=True, timeout=5)
    assert "redirects are not followed" in str(ei.value) and "TOKEN123" not in str(ei.value) and victim.requests == []


def test_credentials_refuse_plain_http_to_remote_hosts():
    for url in ("http://api.example.com/v1", "http://10.0.0.5:8000/v1"):
        with raises(AIProviderError):
            OptionalAPIProvider(url, "key", "m")
    OptionalAPIProvider("https://api.example.com/v1", "key", "m")
    OptionalAPIProvider("http://localhost:1234/v1", "key", "m")
    OptionalAPIProvider("http://api.example.com/v1", "", "m")                                  # no credential, nothing to protect
    with raises(JiraError):
        JiraConfig("http://jira.example.com", "PAY", "tok", "a@b.c").validate()
    JiraConfig("http://127.0.0.1:8080", "PAY", "tok", "a@b.c").validate()


# ------------------------------------------------------------------ filesystem access
def test_path_policy_blocks_roots_sensitive_dirs_and_escapes(tmp_path):
    ok = tmp_path / "proj"
    ok.mkdir()
    assert PathPolicy().check(ok) == ok.resolve()
    with raises(PolicyError):
        PathPolicy().check(Path(ok.anchor))
    (tmp_path / ".ssh").mkdir()
    with raises(PolicyError):
        PathPolicy().check(tmp_path / ".ssh" / "id.log")
    with raises(PolicyError):
        PathPolicy().check(tmp_path / ".AWS" / "x")
    pol = PathPolicy(allowed_roots=(str(ok),))
    assert pol.check(ok / "sub") == (ok / "sub").resolve()
    (tmp_path / "other").mkdir()
    for outside in (tmp_path / "other", ok / ".." / "other", ok / ".." / ".." / "etc"):
        with raises(PolicyError):
            pol.check(outside)


def test_symlink_cannot_smuggle_a_path_outside_the_allowed_root(tmp_path):
    inside, outside = tmp_path / "in", tmp_path / "out"
    inside.mkdir()
    outside.mkdir()
    try:
        os.symlink(outside, inside / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    with raises(PolicyError):
        PathPolicy(allowed_roots=(str(inside),)).check(inside / "link")


def test_public_mode_blocks_every_local_path_but_not_the_bundled_demo(tmp_path):
    pol = PathPolicy(allow_local_paths=False)
    with raises(PolicyError):
        pol.check(tmp_path)
    assert pol.check(DEMO_ROOT / "logs" / "production_sample.log").exists()
    assert pol.check(DEMO_ROOT / "project").is_dir()
    with raises(PolicyError):
        pol.check(DEMO_ROOT / ".." / "app.py")
    with raises(vm.InputError):
        vm.check_log_source(None, None, str(tmp_path / "x.log"), 50, pol)
    with raises(vm.InputError):
        vm.resolve_repo_path(str(tmp_path), pol)
    assert vm.check_log_source(None, None, str(vm.DEMO_LOG), 50, pol)[0] == "path" and vm.resolve_repo_path(str(vm.DEMO_PROJECT), pol)


def test_scanner_refuses_files_whose_real_path_leaves_the_project(tmp_path):
    write_repo(tmp_path, {"ok.py": "x = 1\n", "evil.py": "y = 2\n", "sub/also_evil/z.py": "z = 3\n"})
    real = os.path.realpath

    def fake(p, *a, **k):
        s = str(p)
        return "/somewhere/else/secret.py" if ("evil" in s) else real(p, *a, **k)
    with patch("code_analyzer.scanner.os.path.realpath", side_effect=fake):
        scan = scan_repository(tmp_path)
    assert list(scan.files) == ["ok.py"] and scan.stats.skipped["outside_root"] == 2


def test_retriever_never_opens_paths_taken_from_a_log():
    """A log can claim a stack frame in /etc/passwd or ../../secret.py. Retrieval must only use the scanned index."""
    from code_analyzer.retriever import CodeRetriever
    from code_analyzer.search import CodeIndex
    from log_analyzer.extractor import Frame
    rt = CodeRetriever(CodeIndex.build(SRC.parent))
    opened = []
    real_open = open

    def spy(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)
    with patch("builtins.open", spy), patch("pathlib.Path.read_text", side_effect=AssertionError("file read during retrieval")), \
            patch("pathlib.Path.read_bytes", side_effect=AssertionError("file read during retrieval")):
        for f in ("/etc/passwd", "../../../../etc/shadow", "C:\\Windows\\win.ini", "src/../../app.py", "\\\\server\\share\\x.py"):
            ctx = rt.retrieve_for_frame(Frame(f, 1, "x", None, "python"))
            assert not ctx.verified and (ctx.file_path is None or ctx.file_path in rt.index.files)
    assert opened == []


# ------------------------------------------------------------------ deployment mode and settings
def test_public_demo_mode_switches_risky_features_off():
    s = Settings.from_env(env={"PUBLIC_DEMO": "true", "STORE_HISTORY": "true", "JIRA_BASE_URL": "https://x", "AI_PROVIDER": "ollama"})
    assert s.public_demo and not s.local_paths_allowed and not s.history_enabled and not s.jira_enabled and not s.ai_allowed
    local = Settings.from_env(env={})
    assert local.local_paths_allowed and local.history_enabled and local.jira_enabled and local.ai_allowed
    assert not Settings.from_env(env={"ALLOW_LOCAL_PATHS": "false"}).local_paths_allowed
    assert Settings.from_env(env={"ALLOWED_ROOTS": os.pathsep.join(["/a", "/b"])}).allowed_roots == ("/a", "/b")


def test_session_overrides_cannot_change_hosts_keys_or_modes():
    base = Settings.from_env(env={"PUBLIC_DEMO": "true", "MAX_LOG_SIZE_MB": "10", "OLLAMA_HOST": "http://localhost:11434"})
    hostile = {"ollama_host": "http://evil.example", "api_key": "x", "api_base_url": "http://evil", "public_demo": False,
               "jira_base_url": "http://evil", "allow_local_paths": True, "allowed_roots": (), "max_log_size_mb": 500,
               "store_history": True, "ai_top_n": 99, "ollama_model": "m" * 500, "excluded_dirs": ()}
    s = apply_overrides(base, hostile)
    assert s.ollama_host == base.ollama_host and s.api_key == "" and s.public_demo and not s.local_paths_allowed and s.jira_base_url == ""
    assert s.max_log_size_mb == 10 and not s.store_history and s.ai_top_n == 8 and len(s.ollama_model) == 100
    local = apply_overrides(Settings.from_env(env={}), {"max_log_size_mb": 9999, "ai_top_n": -4})
    assert local.max_log_size_mb == 500 and local.ai_top_n == 0
    assert set(SAFE_OVERRIDES) == {"ai_top_n", "max_log_size_mb", "ollama_model", "redact_emails", "store_history"}


def test_public_demo_ui_hides_paths_history_jira_and_llm():
    from tests.fake_streamlit import installed, page
    with tempfile.TemporaryDirectory() as tmp, installed() as st:
        os.environ.update({"PUBLIC_DEMO": "true", "DB_PATH": str(Path(tmp) / "h.db")})
        try:
            from ui import state as S
            S.init()
            page("analyzer").render()
            labels = [a[0] for k, a, _ in st.calls if k in ("text_input", "toggle")]
            assert not any("path" in l.lower() or "folder" in l.lower() or "LLM" in l for l in labels), labels
            S.load_demo()                                   # the bundled demo still works
            st.click("analyze")
            page("analyzer").render()
            assert st.session_state["run_dict"] is not None and S.db().count() == 0           # and nothing is saved to History
            page("history").render()
            assert any("History is disabled in public-demo mode" in str(a[0]) for k, a, _ in st.calls if k == "info")
            st.session_state["page"] = "Bug Report"
            st.calls.clear()
            page("reports").render()
            assert any("disabled in public-demo mode" in str(a[0]) for k, a, _ in st.calls if k == "caption")
            st.session_state["log_path_text"] = str(Path(tmp) / "x.log")
            (Path(tmp) / "x.log").write_text("2026-09-30 10:00:00 ERROR [S] [T] [req=1] hi\n")
            st.click("analyze")
            page("analyzer").render()
            assert any("Local file paths are disabled" in str(a[0]) for k, a, _ in st.calls if k in ("caption", "error"))
        finally:
            for k in ("PUBLIC_DEMO", "DB_PATH"):
                os.environ.pop(k, None)


def test_online_provider_gets_a_privacy_warning():
    assert vm.ai_privacy_notice("ollama", False) is None
    assert "stays on this computer" in vm.ai_privacy_notice("ollama", True)
    assert "will be sent to the server" in vm.ai_privacy_notice("openai_compatible", True)


# ------------------------------------------------------------------ files, deployment config and code hygiene
@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_history_database_is_owner_only(tmp_path):
    from storage.database import HistoryDB
    HistoryDB(tmp_path / "h.db").save({"log_name": "a", "dashboard": {}})
    assert (tmp_path / "h.db").stat().st_mode & 0o777 == 0o600


def test_streamlit_and_docker_configuration_is_locked_down():
    import tomllib
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["server"]["address"] == "localhost" and cfg["server"]["maxUploadSize"] <= 50
    assert cfg["server"]["enableXsrfProtection"] is True and cfg["browser"]["gatherUsageStats"] is False
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in docker and ".env" not in docker.replace("--env-file .env", "") and "HEALTHCHECK" in docker
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert ".env" in ignore and "*.db" in ignore and ".git" in ignore
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()


FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_ATTRS = {("os", "system"), ("os", "popen"), ("pickle", "load"), ("pickle", "loads"), ("marshal", "load"), ("marshal", "loads"),
                   ("yaml", "load"), ("shelve", "open")}
FORBIDDEN_IMPORTS = {"pickle", "marshal", "shelve", "subprocess", "ctypes"}


def app_sources():
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT)
        if rel.parts[0] in ("tests", "scripts", ".venv", "benchmarks") and not (rel.parts[0] == "benchmarks" and rel.name == "machine.py"):
            continue
        yield rel, ast.parse(p.read_text(encoding="utf-8"))


def test_application_code_has_no_dynamic_execution_or_unsafe_deserialization():
    problems = []
    for rel, tree in app_sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id in FORBIDDEN_CALLS:
                    problems.append(f"{rel}:{node.lineno} {f.id}()")
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and (f.value.id, f.attr) in FORBIDDEN_ATTRS:
                    problems.append(f"{rel}:{node.lineno} {f.value.id}.{f.attr}()")
                for kw in node.keywords:
                    if kw.arg == "shell" and getattr(kw.value, "value", None) is True:
                        problems.append(f"{rel}:{node.lineno} shell=True")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else [(node.module or "").split(".")[0]]
                for n in names:
                    if n in FORBIDDEN_IMPORTS and not (n == "ctypes" and str(rel) == "benchmarks/machine.py"):
                        problems.append(f"{rel}:{node.lineno} import {n}")
    assert not problems, problems


def test_network_calls_go_through_the_no_redirect_opener():
    users = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT)
        if rel.parts[0] in ("tests", ".venv"):
            continue
        text = p.read_text(encoding="utf-8")
        if re.search(r"\burlopen\(", text) and str(rel) != "ai/http.py":
            users.append(str(rel))
    assert not users, users


def test_a_hostile_log_end_to_end_stays_inert(tmp_path):
    """Everything at once: terminal escapes, markup, secrets and a path-traversal stack frame in one log."""
    p = tmp_path / "evil.log"
    p.write_text(
        "\x1b[31m2026-09-30 10:00:00 ERROR\x1b[0m [Svc] [T-1] [req=abc123] Login failed password=hunter2 " + HOSTILE + "\n"
        'Traceback (most recent call last):\n  File "../../../../etc/passwd", line 1, in x\n    root:x:0:0\nValueError: bad '
        + "AK" + "IA" + "ABCDEFGHIJKLMNOP\n", encoding="utf-8")
    run = AnalysisPipeline(top_n=3).run(p, SRC.parent)
    gid = run.grouping.groups[0].id
    t = build_ticket(run, gid)
    blob = json.dumps(t.to_dict()) + render_markdown(t) + render_wiki(t)
    assert "hunter2" not in blob and "AKIAABCDEFGHIJKLMNOP" not in blob and "\x1b" not in blob
    assert not run.reports[gid].code_location_verified and run.errors == []
    prose = re.sub(r"```.*?```", "", render_markdown(t), flags=re.S)
    assert not LIVE_MD.search(prose) and not LIVE_WIKI.search(re.sub(r"\{code[^}]*\}.*?\{code\}", "", render_wiki(t), flags=re.S))
