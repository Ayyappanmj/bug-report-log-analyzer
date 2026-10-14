from config import Settings  # noqa: F401
from log_analyzer.ingest import parse_log_file
from scripts.generate_demo_log import OUT


def _raw():
    return OUT.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_demo_log_line_accounting():
    r = parse_log_file(OUT)
    st = r.stats
    assert st.total_lines == len(_raw().splitlines())
    assert st.total_lines == st.events + st.continuation_lines + st.blank_lines + st.unparsed_lines


def test_demo_log_unparsed_lines_are_the_two_injected_noise_lines():
    st = parse_log_file(OUT).stats
    assert st.unparsed_lines == 2
    assert set(st.unparsed_samples) == {"-- log rotated --", "Connection reset by peer"}


def test_demo_log_both_formats_detected():
    st = parse_log_file(OUT).stats
    assert st.events_by_format["bracketed"] > 0 and st.events_by_format["json"] > 0


def test_demo_log_timeout_tracebacks_match_raw_text_counts():
    r = parse_log_file(OUT)
    expected = _raw().count("DatabaseConnectionTimeout: Timed out after")
    got = sum("DatabaseConnectionTimeout: Timed out after" in e.stack_trace for e in r.events)
    assert expected > 0 and got == expected
    keyerrors = sum("KeyError: 'currency'" in e.stack_trace for e in r.events)
    assert keyerrors == _raw().count("KeyError: 'currency'") > 0


def test_demo_log_traceback_event_metadata():
    r = parse_log_file(OUT)
    e = next(x for x in r.events if "DatabaseConnectionTimeout: Timed out" in x.stack_trace)
    assert e.level == "ERROR" and e.service == "CheckoutService"
    assert e.request_id and e.timestamp and e.end_line > e.line_no
    assert 'File "src/payment_service.py"' in e.stack_trace


def test_demo_log_json_gateway_errors_have_status():
    r = parse_log_file(OUT)
    js = [e for e in r.events if e.fmt == "json"]
    assert js and all(e.http_status == 500 and e.service == "api-gateway" for e in js)
