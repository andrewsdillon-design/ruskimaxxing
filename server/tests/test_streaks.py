"""Pure logic for the training streak / call-discount calculation (see streaks.py)."""

from datetime import date, timedelta

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ruskimaxxing_cloud.streaks import FORGIVE_WINDOW_DAYS, compute_streak, is_training_day  # noqa: E402

START = date(2026, 1, 5)  # a Monday -> scheduled Mon/Wed/Fri


def d(offset_days: int) -> date:
    return START + timedelta(days=offset_days)


def test_is_training_day_mon_wed_fri():
    assert is_training_day(d(0), START)      # Monday
    assert not is_training_day(d(1), START)  # Tuesday
    assert is_training_day(d(2), START)      # Wednesday
    assert not is_training_day(d(3), START)  # Thursday
    assert is_training_day(d(4), START)      # Friday
    assert not is_training_day(d(5), START)  # Saturday
    assert not is_training_day(d(6), START)  # Sunday
    assert is_training_day(d(7), START)      # next Monday


def test_no_checks_means_no_streak():
    r = compute_streak([], START, today=d(10))
    assert r.streak_start is None and r.streak_days == 0 and r.discount_pct == 0
    assert r.misses_forgiven_in_window == 0 and r.next_discount_at_days == 90
    assert r.checked_today is False


def test_perfect_streak_all_scheduled_days_checked():
    checks = [d(0), d(2), d(4), d(7), d(9), d(11)]
    r = compute_streak(checks, START, today=d(11))
    assert r.streak_start == d(0)
    assert r.streak_days == 12  # d(0)..d(11) inclusive
    assert r.checked_today is True
    assert r.today_is_training_day is True
    assert r.misses_forgiven_in_window == 0


def test_one_forgiven_miss_keeps_streak_alive():
    # miss Wednesday d(2), but no other miss within 30 days -> forgiven, streak intact
    checks = [d(0), d(4), d(7)]
    r = compute_streak(checks, START, today=d(7))
    assert r.streak_start == d(0)
    assert r.streak_days == d(7).toordinal() - d(0).toordinal() + 1
    assert r.misses_forgiven_in_window == 1


def test_second_miss_within_30_days_resets_streak():
    # miss d(2) (forgiven), then miss d(4) only 2 days later -> second miss resets the streak.
    # Next accepted check is d(7): new streak starts there.
    checks = [d(0), d(7), d(9)]
    r = compute_streak(checks, START, today=d(9))
    assert r.streak_start == d(7)
    assert r.streak_days == d(9).toordinal() - d(7).toordinal() + 1


def test_miss_after_31_days_forgiven_again():
    # First streak start d(0). Miss d(2) forgiven. A second miss more than 30 days later is also forgiven
    # (each miss only resets the streak if *another* miss happened in the preceding 30 days).
    miss1 = d(2)
    end = 2 + 40  # comfortably more than 30 days past miss1
    while not is_training_day(d(end), START):
        end += 1
    miss2 = d(end)
    assert (miss2 - miss1).days > FORGIVE_WINDOW_DAYS

    after = end + 1
    while not is_training_day(d(after), START):
        after += 1
    today = d(after)  # a training day strictly after miss2, so miss2 has actually occurred and can be tallied

    all_training_days = [day for o in range(0, after + 1) if is_training_day(day := d(o), START)]
    checks = [day for day in all_training_days if day not in (miss1, miss2)]
    r = compute_streak(checks, START, today=today)
    assert r.streak_start == d(0)
    assert r.misses_forgiven_in_window == 1  # only the recent forgiven miss (miss1 is now outside the window)


def test_today_not_counted_as_missed_even_if_unchecked():
    checks = [d(0), d(2)]
    r = compute_streak(checks, START, today=d(4))  # d(4) is a training day, not yet checked, but it's "today"
    assert r.today_is_training_day is True
    assert r.checked_today is False
    assert r.streak_start == d(0)
    assert r.streak_days == d(4).toordinal() - d(0).toordinal() + 1


def test_discount_thresholds():
    def days_streak(n):
        # a streak with no misses at all: checks only every training day for n days is unnecessary;
        # we can simulate a streak_start n-1 days before today with zero misses by only checking start+today
        # and disabling checks in between is invalid (misses would occur). Instead directly test discount math
        # via a fully-checked run - use a small helper that always checks every scheduled day.
        start = date(2020, 1, 6)  # Monday
        today = start + timedelta(days=n - 1)
        checks = []
        day = start
        while day <= today:
            if is_training_day(day, start):
                checks.append(day)
            day += timedelta(days=1)
        return compute_streak(checks, start, today)

    assert days_streak(89).discount_pct == 0
    assert days_streak(90).discount_pct == 10
    assert days_streak(450).discount_pct == 50
    assert days_streak(900).discount_pct == 50


def test_next_discount_at_days_caps_at_max():
    start = date(2020, 1, 6)
    today = start + timedelta(days=449)
    checks = []
    day = start
    while day <= today:
        if is_training_day(day, start):
            checks.append(day)
        day += timedelta(days=1)
    r = compute_streak(checks, start, today)
    assert r.discount_pct == 50
    assert r.next_discount_at_days is None
