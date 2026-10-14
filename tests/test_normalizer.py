from datetime import datetime

from log_analyzer.normalizer import normalize_level, parse_epoch, parse_timestamp


def test_level_aliases():
    assert normalize_level("WARNING") == "WARN"
    assert normalize_level("fatal") == "CRITICAL"
    assert normalize_level("Err") == "ERROR"
    assert normalize_level(50) == "ERROR"
    assert normalize_level("nonsense") is None
    assert normalize_level(None) is None


def test_timestamp_formats():
    assert parse_timestamp("2026-09-30 10:22:14,123") == datetime(2026, 9, 30, 10, 22, 14, 123000)
    assert parse_timestamp("2026-09-30T10:22:14.5") == datetime(2026, 9, 30, 10, 22, 14, 500000)
    assert parse_timestamp("2026-09-30 10:22:14") == datetime(2026, 9, 30, 10, 22, 14)


def test_timezone_converted_to_utc():
    assert parse_timestamp("2026-09-30T10:00:00Z") == datetime(2026, 9, 30, 10, 0, 0)
    assert parse_timestamp("2026-09-30T10:00:00+02:00") == datetime(2026, 9, 30, 8, 0, 0)
    assert parse_timestamp("2026-09-30T10:00:00-0530") == datetime(2026, 9, 30, 15, 30, 0)


def test_invalid_timestamps_return_none():
    assert parse_timestamp("2026-13-45 99:99:99") is None
    assert parse_timestamp("not a date") is None
    assert parse_timestamp("") is None


def test_epoch_seconds_and_millis():
    assert parse_epoch(1_700_000_000) == parse_epoch(1_700_000_000_000)
    assert parse_epoch("x") is None


def test_normalize_message_masks_volatile_parts():
    from log_analyzer.normalizer import normalize_message as n
    assert n("Timed out after 5.0s (pool_size=10)") == "Timed out after <N>s (pool_size=<N>)"
    assert n("user=u123 from ip=10.0.3.44") == "user=u<N> from ip=<IP>"
    assert n("req 3fe1e8 failed") == "req <HEX> failed"
    assert n("id 550e8400-e29b-41d4-a716-446655440000 ok") == "id <UUID> ok"
    assert n("mail bob@example.com at 2026-09-30 10:00:00,123") == "mail <EMAIL> at <TS>"
    assert n("  extra   spaces ") == "extra spaces"
    assert n("") == ""


def test_normalized_messages_of_same_problem_are_equal():
    from log_analyzer.normalizer import normalize_message as n
    assert n("Charge failed order=ORD-1001 (waited 5.0s)") == n("Charge failed order=ORD-2047 (waited 5.2s)")
    assert n("Disk full") != n("Disk almost full")
