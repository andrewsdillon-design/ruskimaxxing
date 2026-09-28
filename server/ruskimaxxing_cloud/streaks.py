"""Pure training-streak math (no DB, no I/O) - see server task spec for the business rules.

A user who owns at least one program year is scheduled to train 3 days a week: the weekday
their program started on, plus two and four days later (e.g. a Monday start -> Mon/Wed/Fri).
Each scheduled day they submit a barbell photo from the app, we record a "check" for that day.

Walking scheduled days forward from the first accepted check to today:
  - a scheduled day with no check, strictly before today, is a miss (today isn't missed until it ends)
  - one miss is forgiven if there was no other miss in the preceding 30 days
  - a miss that happens within 30 days of another miss resets the streak; the new streak starts at
    the next accepted check after that reset

Coaching-call discount: 10% per full 90-day streak, capped at 50%.
"""

from dataclasses import dataclass
from datetime import date, timedelta

TRAINING_OFFSETS = (0, 2, 4)          # days after the program's start weekday
FORGIVE_WINDOW_DAYS = 30              # a second miss inside this many days of a prior miss resets the streak
DISCOUNT_STEP_DAYS = 90               # each full period of this many streak-days adds to the discount
DISCOUNT_PCT_PER_STEP = 10
MAX_DISCOUNT_PCT = 50
MAX_DISCOUNT_STEPS = MAX_DISCOUNT_PCT // DISCOUNT_PCT_PER_STEP  # 5


@dataclass
class StreakResult:
    streak_start: date | None
    streak_days: int
    discount_pct: int
    misses_forgiven_in_window: int
    next_discount_at_days: int | None
    checked_today: bool
    today_is_training_day: bool


def is_training_day(day: date, start: date) -> bool:
    """True if `day` falls on one of the 3 scheduled weekdays derived from the program's `start` date."""
    scheduled_weekdays = {(start.weekday() + o) % 7 for o in TRAINING_OFFSETS}
    return day.weekday() in scheduled_weekdays


def _discount_for(streak_days: int) -> int:
    return min(MAX_DISCOUNT_PCT, DISCOUNT_PCT_PER_STEP * (streak_days // DISCOUNT_STEP_DAYS))


def _next_discount_at(streak_days: int) -> int | None:
    step = streak_days // DISCOUNT_STEP_DAYS
    if step >= MAX_DISCOUNT_STEPS:
        return None
    return (step + 1) * DISCOUNT_STEP_DAYS


def compute_streak(checks: list, start: date, today: date) -> StreakResult:
    """`checks` is a list/iterable of dates on which the user had an accepted (validated) photo check."""
    checked_today = today in checks
    today_is_training = is_training_day(today, start)
    check_set = set(checks)

    if not check_set:
        return StreakResult(None, 0, 0, 0, DISCOUNT_STEP_DAYS, checked_today, today_is_training)

    sorted_checks = sorted(check_set)
    streak_start = sorted_checks[0]
    miss_dates: list[date] = []  # miss dates (forgiven or not) since the current streak_start

    day = streak_start
    while day < today:
        if is_training_day(day, start) and day not in check_set:
            has_recent_miss = any((day - md).days <= FORGIVE_WINDOW_DAYS for md in miss_dates)
            if not has_recent_miss:
                miss_dates.append(day)
            else:
                next_check = next((c for c in sorted_checks if c > day), None)
                if next_check is None or next_check > today:
                    return StreakResult(None, 0, 0, 0, DISCOUNT_STEP_DAYS, checked_today, today_is_training)
                streak_start = next_check
                miss_dates = []
                day = next_check
                continue
        day += timedelta(days=1)

    streak_days = (today - streak_start).days + 1
    misses_forgiven_in_window = sum(1 for md in miss_dates if (today - md).days <= FORGIVE_WINDOW_DAYS)
    return StreakResult(streak_start, streak_days, _discount_for(streak_days), misses_forgiven_in_window,
                        _next_discount_at(streak_days), checked_today, today_is_training)
