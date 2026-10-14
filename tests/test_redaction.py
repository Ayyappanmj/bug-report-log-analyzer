from ai.redaction import redact


def test_common_secrets_are_masked_and_counted():
    text = ("password=hunter2 api_key: 'abc123xyz' token=ghp_" + "a" * 36 + " AKIAABCDEFGHIJKLMNOP "
            "Authorization: Bearer abcdefghijklmnop1234567890 postgres://user:pa55@db:5432/app "
            "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4 sk-" + "b" * 30)
    r = redact(text)
    for leaked in ("hunter2", "abc123xyz", "ghp_" + "a" * 36, "AKIAABCDEFGHIJKLMNOP", "abcdefghijklmnop1234567890",
                   "pa55", "SflKxwRJSMeKKF2QT4", "b" * 30):
        assert leaked not in r.text, leaked
    assert "password=<REDACTED:secret>" in r.text and r.total >= 7
    assert r.counts["aws_key"] == 1 and r.counts["jwt"] == 1 and r.counts["url_credentials"] == 1


def test_private_key_block_is_removed():
    r = redact("x\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----\ny")
    assert "MIIEow" not in r.text and r.counts["private_key"] == 1 and r.text.startswith("x") and r.text.endswith("y")


def test_normal_log_text_is_untouched():
    text = "Checkout failed order=ORD-1516 user=u123 waited 5.0s at src/database.py:19 pool_size=10"
    assert redact(text).text == text and redact(text).total == 0


def test_email_toggle_and_idempotence():
    assert redact("mail bob@example.com").text == "mail <REDACTED:email>"
    assert redact("mail bob@example.com", redact_emails=False).text == "mail bob@example.com"
    once = redact("password=hunter2").text
    assert redact(once).text == once
