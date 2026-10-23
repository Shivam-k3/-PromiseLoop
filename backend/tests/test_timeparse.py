"""Deadline parsing rules."""

from datetime import date, datetime, time, timezone

import pytest

from app.services.timeparse import parse_deadline

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)  # a Thursday


def test_relative_tomorrow_is_resolved():
    deadline = parse_deadline("send the demo by tomorrow", "UTC", NOW)
    assert deadline is not None
    assert deadline.date == date(2026, 10, 23)
    assert deadline.precision == "day"


def test_time_of_day_word_is_picked_up():
    deadline = parse_deadline("send the demo by tomorrow evening", "UTC", NOW)
    assert deadline is not None
    assert deadline.date == date(2026, 10, 23)
    assert deadline.time == time(18, 0)
    assert deadline.precision == "day"
    assert deadline.label.lower() == "tomorrow evening"


def test_explicit_clock_time_is_exact():
    deadline = parse_deadline("call the client at 5pm today", "UTC", NOW)
    assert deadline is not None
    assert deadline.date == date(2026, 10, 22)
    assert deadline.time == time(17, 0)
    assert deadline.precision == "exact"


def test_explicit_numeric_date():
    deadline = parse_deadline("submit the report on 30/10/2026", "UTC", NOW)
    assert deadline is not None
    assert deadline.date == date(2026, 10, 30)
    assert deadline.ambiguous is False


def test_iso_date():
    deadline = parse_deadline("ship it by 2026-11-02", "UTC", NOW)
    assert deadline is not None
    assert deadline.date == date(2026, 11, 2)


def test_bare_weekday_is_ambiguous():
    deadline = parse_deadline("meet Priya on Friday", "UTC", NOW)
    assert deadline is not None
    assert deadline.date == date(2026, 10, 23)
    assert deadline.ambiguous is True
    assert deadline.question is not None
    assert "Which Friday" in deadline.question


def test_deadline_marker_is_not_repeated_in_clarification():
    deadline = parse_deadline("by Friday", "UTC", NOW)
    assert deadline is not None
    assert deadline.question is not None
    assert "Which Friday" in deadline.question
    assert "By Friday" not in deadline.question


def test_next_weekday_is_not_ambiguous():
    deadline = parse_deadline("meet Priya next Friday", "UTC", NOW)
    assert deadline is not None
    assert deadline.date == date(2026, 10, 30)
    assert deadline.ambiguous is False


def test_in_n_days():
    deadline = parse_deadline("remind me in 3 days", "UTC", NOW)
    assert deadline is not None
    assert deadline.date == date(2026, 10, 25)


def test_no_deadline_returns_none():
    assert parse_deadline("I promised Abhishek a demo", "UTC", NOW) is None


def test_timezone_conversion_is_correct():
    deadline = parse_deadline("send the demo by tomorrow evening", "Asia/Kolkata", NOW)
    assert deadline is not None
    # 18:00 in Asia/Kolkata (UTC+5:30) is 12:30 UTC
    assert deadline.as_utc("Asia/Kolkata") == datetime(2026, 10, 23, 12, 30, tzinfo=timezone.utc)


def test_daylight_saving_is_respected():
    deadline = parse_deadline("send the demo by tomorrow evening", "Europe/Berlin", NOW)
    assert deadline is not None
    # Europe/Berlin switches to CEST (UTC+2) on 25 October 2026; 22 October is CEST too.
    assert deadline.as_utc("Europe/Berlin").utcoffset() is not None
    assert deadline.as_utc("Europe/Berlin").hour == 16


@pytest.mark.parametrize(
    "phrase",
    ["by tomorrow evening", "tomorrow evening", "by end of day tomorrow", "due tomorrow"],
)
def test_common_phrases_always_yield_a_deadline(phrase):
    deadline = parse_deadline(f"I promised Abhishek {phrase}", "UTC", NOW)
    assert deadline is not None
    assert deadline.date == date(2026, 10, 23)
