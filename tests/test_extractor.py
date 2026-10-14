from log_analyzer.extractor import exception_in_message, parse_exception_chain

PY_CHAIN = """Traceback (most recent call last):
  File "src/checkout.py", line 17, in process_checkout
    self.payments.charge(order["id"], order["total"])
  File "src/database.py", line 19, in _acquire_connection
    raise DatabaseConnectionTimeout(
DatabaseConnectionTimeout: Timed out after 5.0s

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "src/checkout.py", line 19, in process_checkout
    raise CheckoutError(
CheckoutError: Payment could not be completed""".split("\n")

JAVA = """java.lang.IllegalStateException: request failed
\tat com.acme.Api.handle(Api.java:42)
\tat com.acme.Server.run(Server.java:10)
Caused by: java.sql.SQLTransientConnectionException: pool exhausted
\tat com.acme.Db.acquire(Db.java:77)
\t... 5 more""".split("\n")


def test_python_chain_root_and_surfaced():
    c = parse_exception_chain(PY_CHAIN)
    assert c.style == "python"
    assert [e.short_type for e in c.exceptions] == ["DatabaseConnectionTimeout", "CheckoutError"]
    assert c.root.short_type == "DatabaseConnectionTimeout"
    assert c.surfaced.short_type == "CheckoutError"
    assert (c.raise_site.file, c.raise_site.line, c.raise_site.function) == ("src/database.py", 19, "_acquire_connection")
    assert c.raise_site.code == "raise DatabaseConnectionTimeout("
    assert c.root.message == "Timed out after 5.0s"


def test_java_chain_root_is_last_cause():
    c = parse_exception_chain(JAVA)
    assert c.surfaced.short_type == "IllegalStateException"
    assert c.root.short_type == "SQLTransientConnectionException"
    assert (c.raise_site.file, c.raise_site.line) == ("Db.java", 77)
    assert c.raise_site.language == "java"


def test_spec_example_without_traceback_header():
    c = parse_exception_chain(["DatabaseConnectionTimeout",
                               '  File "payment/service.py", line 184, in charge',
                               "    result = database.execute(query)"])
    assert c.root.short_type == "DatabaseConnectionTimeout" and c.root.message == ""
    assert c.raise_site.file == "payment/service.py" and c.raise_site.line == 184
    assert c.raise_site.code == "result = database.execute(query)"


def test_python_311_caret_lines_are_skipped():
    lines = ["Traceback (most recent call last):",
             '  File "a.py", line 3, in f',
             "    x = d[k]",
             "        ~^^^",
             '  File "a.py", line 9, in g',
             "    f()",
             "KeyError: 'k'"]
    c = parse_exception_chain(lines)
    assert [(f.line, f.code) for f in c.root.frames] == [(3, "x = d[k]"), (9, "f()")]
    assert c.raise_site.line == 9


def test_javascript_frames():
    c = parse_exception_chain(["TypeError: x is undefined", "    at handler (/app/src/pay.js:10:5)",
                               "    at /app/src/index.js:3:1"])
    assert c.root.short_type == "TypeError"
    assert [(f.file, f.line, f.function) for f in c.root.frames] == [
        ("/app/src/pay.js", 10, "handler"), ("/app/src/index.js", 3, "<anonymous>")]


def test_windows_path_frame():
    c = parse_exception_chain(["Traceback (most recent call last):",
                               '  File "C:\\app\\src\\pay.py", line 7, in charge', "    boom()",
                               "ValueError: bad"])
    assert c.raise_site.file == "C:\\app\\src\\pay.py"


def test_no_exception_lines():
    assert parse_exception_chain([]).exceptions == []
    c = parse_exception_chain(["  some indented text", "another line"])
    assert c.root is None and c.raise_site is None and c.style == "none"


def test_non_exception_lines_are_not_misread():
    c = parse_exception_chain(["The above exception was the direct cause", "Connection reset by peer",
                               "Note: something happened"])
    assert c.exceptions == []


def test_exception_in_message():
    assert exception_in_message("failed with SocketTimeoutException after 5s") == "SocketTimeoutException"
    assert exception_in_message("all good") is None
