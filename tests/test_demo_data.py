import ast
import re

from scripts.generate_demo_log import OUT, SRC, build_log

FRAME = re.compile(r'^\s+File "(src/[^"]+)", line (\d+), in (\S+)$')
TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) ")


def _log_text():
    return OUT.read_text(encoding="utf-8").replace("\r\n", "\n")


def _enclosing_function(path, lineno):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno <= lineno <= node.end_lineno:
            if best is None or node.lineno > best.lineno:
                best = node
    return best.name if best else "<module>"


def test_demo_sources_are_valid_python():
    for name in ("database.py", "payment_service.py", "checkout.py"):
        ast.parse((SRC / name).read_text(encoding="utf-8"))  # parsed only, never executed


def test_every_traceback_frame_matches_real_source():
    lines = _log_text().split("\n")
    checked = 0
    for i, line in enumerate(lines):
        m = FRAME.match(line)
        if not m:
            continue
        rel, no, func = m.group(1), int(m.group(2)), m.group(3)
        path = SRC.parent / rel
        src_lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[i + 1].strip() == src_lines[no - 1].strip(), (rel, no)
        assert _enclosing_function(path, no) == func, (rel, no, func)
        checked += 1
    assert checked > 0


def test_log_contains_expected_scenarios():
    text = _log_text()
    assert "DatabaseConnectionTimeout" in text
    assert "CheckoutError: Payment could not be completed" in text
    assert "KeyError: 'currency'" in text
    assert "The above exception was the direct cause" in text


def test_plain_timestamps_are_non_decreasing():
    stamps = [m.group(1) for l in _log_text().split("\n") if (m := TS.match(l))]
    assert len(stamps) > 100
    assert stamps == sorted(stamps)


def test_committed_log_matches_generator():
    assert build_log() == _log_text()
