"""RuskiMaxxing 2-Day: Year 1 for men who can only train twice a week.

Same year as the 3-day program (four 12-week cycles of accumulation, transmutation and realization blocks,
deloads, a taper and a test week, then a 4-week transition), so the generator in program.py builds it;
only the week's layout changes. Each lift is trained once a week heavy or medium and the main lifts that
lose a day get a conjugate variation slot instead:

    Day 1 - Heavy   box jump; squat (heavy), bench press (heavy), rotating deadlift variation (light)
    Day 2 - Light   broad jump; deadlift (medium), overhead press (heavy), squat (light),
                    rotating bench variation (medium)

Squat and bench are tested on Day 1, deadlift and overhead press on Day 2.
"""

from ruskimaxxing import program

DAYS_PER_WEEK = 2
DAY_OFFSETS = (0, 3)  # Monday / Thursday

DAYS = (
    ("Day 1 - Heavy", ("Box Jump",),
     [("Squat", "heavy"), ("Bench Press", "heavy"), ("@deadlift", "light")],
     [("Barbell Row", "8-10"), ("Face Pull", "12-15"), ("Plank", "30-60s")]),
    ("Day 2 - Light", ("Broad Jump",),
     [("Deadlift", "medium"), ("Overhead Press", "heavy"), ("Squat", "light"), ("@bench", "medium")],
     [("Chin-up", "6-10"), ("Back Extension", "10-15")]),
)
TESTED = {0: {"Squat", "Bench Press"}, 1: {"Deadlift", "Overhead Press"}}


def build():
    program.DAYS, program.TESTED, program.DAY_OFFSETS = DAYS, TESTED, DAY_OFFSETS
    return program.build_program()
