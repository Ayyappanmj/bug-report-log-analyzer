from datetime import datetime

from log_analyzer.parser import LogParser


def parse(text):
    p = LogParser()
    events = list(p.parse_lines(text.split("\n")))
    return events, p.stats


def test_bracketed_line_fields():
    ev, st = parse("2026-09-30 10:22:14,123 ERROR [PaymentService] [Thread-7] [req=abc123] Charge failed status=500")
    e = ev[0]
    assert (e.level, e.service, e.thread, e.request_id) == ("ERROR", "PaymentService", "Thread-7", "abc123")
    assert e.timestamp == datetime(2026, 9, 30, 10, 22, 14, 123000)
    assert e.message == "Charge failed status=500" and e.http_status == 500
    assert st.events == 1


def test_dash_request_id_is_none():
    ev, _ = parse("2026-09-30 10:00:00,000 INFO  [App] [Main] [req=-] hello")
    assert ev[0].request_id is None


def test_spec_example_service_then_exception_on_next_line():
    text = ("2026-09-30 10:22:14 ERROR PaymentService\n"
            "DatabaseConnectionTimeout\n"
            '  File "payment/service.py", line 184, in charge\n'
            "    result = database.execute(query)")
    ev, st = parse(text)
    assert len(ev) == 1
    assert ev[0].service == "PaymentService"
    assert ev[0].message == "DatabaseConnectionTimeout"
    assert "line 184" in ev[0].stack_trace
    assert st.unparsed_lines == 0


def test_lone_word_without_continuation_is_message_not_service():
    ev, _ = parse("2026-09-30 10:22:14 INFO started")
    assert ev[0].service is None and ev[0].message == "started"


def test_generic_formats():
    ev, _ = parse("2026-09-30T10:22:14Z WARNING: Disk usage high\n"
                  "2026-09-30 10:22:15 [ERROR] OrderService: failed to save\n"
                  "2026-09-30 10:22:16 FATAL [Worker] crashed")
    assert [e.level for e in ev] == ["WARN", "ERROR", "CRITICAL"]
    assert ev[1].service == "OrderService" and ev[1].message == "failed to save"
    assert ev[2].service == "Worker"


def test_java_style_stack_trace_attached():
    text = ("2026-09-30 10:22:14 ERROR [Api] boom\n"
            "java.lang.IllegalStateException: bad\n"
            "\tat com.acme.Foo.bar(Foo.java:10)\n"
            "Caused by: java.sql.SQLException: down\n"
            "\t... 5 more\n"
            "2026-09-30 10:22:15 INFO [Api] next")
    ev, st = parse(text)
    assert len(ev) == 2
    assert len(ev[0].continuation) == 4 and (ev[0].end_line - ev[0].line_no) == 4
    assert st.unparsed_lines == 0


def test_json_lines_with_alternate_keys():
    ev, _ = parse('{"time": "2026-09-30T10:00:00Z", "severity": "error", "service": "gw", '
                  '"msg": "upstream failed", "status_code": 502, "correlationId": "x"}\n'
                  '{"ts": 1700000000, "level": 30, "message": "ok", "request_id": "r1"}')
    assert ev[0].level == "ERROR" and ev[0].http_status == 502 and ev[0].fmt == "json"
    assert ev[1].level == "INFO" and ev[1].request_id == "r1" and ev[1].timestamp is not None


def test_json_stack_field_becomes_stack_trace():
    ev, st = parse('{"level": "error", "message": "x", "stack": "Trace\\n  at a\\n  at b"}')
    assert ev[0].continuation == ["Trace", "  at a", "  at b"]
    assert st.continuation_lines == 0  # embedded, not separate physical lines


def test_json_without_known_keys_is_unparsed():
    ev, st = parse('{"foo": 1}')
    assert ev == [] and st.unparsed_lines == 1


def test_http_status_from_access_log_style():
    ev, _ = parse("2026-09-30 10:00:00 INFO [gw] POST /api/checkout 500 12ms")
    assert ev[0].http_status == 500


def test_empty_input():
    ev, st = parse("")
    assert ev == [] and st.events == 0 and st.unparsed_lines == 0


def test_garbage_only_input_is_counted_not_crashing():
    ev, st = parse("hello\n\nworld\n\x00\x01 junk")
    assert ev == []
    assert st.unparsed_lines == 3 and st.blank_lines == 1
    assert st.total_lines == 4


def test_stray_line_does_not_join_previous_event():
    text = ("2026-09-30 10:00:00 INFO [A] one\n"
            "-- log rotated --\n"
            "2026-09-30 10:00:01 INFO [A] two")
    ev, st = parse(text)
    assert len(ev) == 2 and ev[0].continuation == []
    assert st.unparsed_samples == ["-- log rotated --"]


def test_continuation_cap_counts_dropped_lines():
    p = LogParser(max_continuation=3)
    lines = ["2026-09-30 10:00:00 ERROR [A] x"] + [f"  frame {i}" for i in range(10)]
    ev = list(p.parse_lines(lines))
    assert len(ev[0].continuation) == 3
    assert p.stats.dropped_continuation_lines == 7 and p.stats.continuation_lines == 10


def test_line_accounting_identity():
    text = ("2026-09-30 10:00:00 ERROR [A] x\n  a\n\n  b\n\nnoise\n\n"
            "2026-09-30 10:00:01 INFO [A] y")
    _, st = parse(text)
    assert st.total_lines == st.events + st.continuation_lines + st.blank_lines + st.unparsed_lines
