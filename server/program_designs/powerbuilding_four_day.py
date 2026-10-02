"""Powerbuilding 4-Day: upper/lower, each main lift once a week heavy and trained again for volume.
See powerbuilding.py for the design.

    Day 1 - Lower: Squat      squat top + back-offs, Romanian deadlifts, split squats, hamstrings, calves
    Day 2 - Upper: Bench      bench top + back-offs, overhead press for volume, rows, chin-ups, arms
    Day 3 - Lower: Deadlift   deadlift top + back-offs, a squat variation for volume, legs and low back
    Day 4 - Upper: Press      overhead press top + back-offs, a bench variation for volume, back, delts
"""

from program_designs.powerbuilding import EXTRA_EXERCISES, FOUR_DAY  # noqa: F401  (export reads EXTRA_EXERCISES)

DAYS_PER_WEEK = 4


def build():
    return FOUR_DAY.build()
