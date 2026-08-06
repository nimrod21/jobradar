from datetime import datetime, timedelta, timezone

from worker.dates import parse_date


def test_iso8601():
    dt = parse_date("2026-08-04T12:30:00Z")
    assert dt == datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc)


def test_iso8601_offset_normalised_to_utc():
    dt = parse_date("2026-08-04T14:30:00+02:00")
    assert dt == datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc)


def test_date_only():
    dt = parse_date("2026-08-04")
    assert dt == datetime(2026, 8, 4, tzinfo=timezone.utc)


def test_epoch_seconds():
    dt = parse_date(1754308800)  # 2025-08-04T12:00:00Z
    assert dt.year == 2025 and dt.tzinfo is not None


def test_epoch_milliseconds():
    s = parse_date(1754308800)
    ms = parse_date(1754308800000)
    assert s == ms


def test_epoch_as_string():
    assert parse_date("1754308800") == parse_date(1754308800)


def test_rfc822_rss():
    dt = parse_date("Tue, 04 Aug 2026 09:00:00 GMT")
    assert dt == datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)


def test_zoho_mdy():
    assert parse_date("08/04/2026") == datetime(2026, 8, 4, tzinfo=timezone.utc)


def test_mdy_future_rejected():
    future = datetime.now(timezone.utc) + timedelta(days=400)
    assert parse_date(future.strftime("%m/%d/%Y")) is None


def test_garbage_returns_none():
    assert parse_date("posted recently") is None
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date([]) is None


def test_datetime_passthrough_gets_tz():
    naive = datetime(2026, 1, 1, 10, 0)
    assert parse_date(naive).tzinfo is not None
