"""Powerbuilding 2-Day: full body twice a week. See powerbuilding.py for the design.

    Day 1 - Squat and Bench      squat and bench top + back-off sets, Romanian deadlifts, back and arms
    Day 2 - Deadlift and Press   deadlift and overhead press top + back-off sets, a squat and a bench
                                 variation for volume, chin-ups and triceps
"""

from program_designs.powerbuilding import EXTRA_EXERCISES, TWO_DAY  # noqa: F401  (export reads EXTRA_EXERCISES)

DAYS_PER_WEEK = 2


def build():
    return TWO_DAY.build()
