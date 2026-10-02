"""RuskiMaxxing 4-Day Conjugate: Year 1 upper/lower, Westside style.

Four days a week, two max-effort and two dynamic-effort:

    Day 1 - Max Effort Lower     box jump; work up to a 1-3RM on a rotating squat or deadlift variation
    Day 2 - Max Effort Upper     med ball chest pass; work up to a 1-3RM on a rotating bench variation
    Day 3 - Dynamic Effort Lower broad jump; speed box squats 10 x 2 and speed deadlifts 6 x 1
    Day 4 - Dynamic Effort Upper plyo push-up; speed bench 9 x 3, overhead press for strength

The year keeps RuskiMaxxing's 12-week cycle so clubs test together and leaderboards stay in step:

    weeks 1-3   wave 1      dynamic work at 55 / 60 / 65% of the exercise's training max
    week 4      deload
    weeks 5-7   wave 2      same waves; max-effort variations rotate every 3-week block
    week 8      deload
    weeks 9-10  wave 3
    week 11     taper       competition lifts heavy but short, accessories cut
    week 12     test        squat, bench press, deadlift and overhead press maxes
    weeks 49-52 transition  easy volume, then a full deload

Max-effort lower alternates squat and deadlift variations each block. Max-effort work has no percentage:
work up in 4-6 jumps to the best single, double or triple you can do with good form, and log it - each
variation is tracked as its own PR.
"""

from ruskimaxxing.exercises import ROTATION
from ruskimaxxing.program import (ACCESSORY_NOTE, CYCLE_WEEKS, CYCLES, PLYO_NOTES, TEST_NOTE, WEEKS, Prescription,
                                  Session)

DAYS_PER_WEEK = 4
DAY_NAMES = ("Day 1 - Max Effort Lower", "Day 2 - Max Effort Upper", "Day 3 - Dynamic Effort Lower",
             "Day 4 - Dynamic Effort Upper")
PLYOS = ("Box Jump", "Med Ball Chest Pass", "Broad Jump", "Plyo Push-up")
TESTS = ("Squat", "Bench Press", "Deadlift", "Overhead Press")
TEST_PLYOS = {0: "Box Jump", 2: "Broad Jump", 3: "Vertical Jump"}

ACCESSORIES = (
    [("Glute-Ham Raise", "8-10"), ("Reverse Hyper", "10-15"), ("Walking Lunge", "10 each leg"),
     ("Hanging Leg Raise", "10-15")],
    [("Incline Dumbbell Press", "8-12"), ("One-Arm Dumbbell Row", "10-12"), ("Triceps Pushdown", "10-15"),
     ("Face Pull", "15")],
    [("Good Morning", "8"), ("Back Extension", "10-15"), ("Plank", "30-60s")],
    [("Chin-up", "6-10"), ("Dip", "8-12"), ("Lateral Raise", "12-15"), ("Hammer Curl", "10-12")],
)

WAVES = (55.0, 60.0, 65.0)  # dynamic effort, % of the exercise's own training max, by week in the block
PULL_WAVES = (65.0, 70.0, 75.0)
OHP = ((4, "6", (65.0, 67.5, 70.0)), (4, "5", (72.5, 75.0, 77.5)), (5, "3", (80.0, 82.5)))  # by block

ME_NOTE = ("Work up in 4-6 jumps to the heaviest single, double or triple you can do with good form. "
           "Log the top set - it's this variation's PR")
DE_SQUAT_NOTE = "Speed: sit back to a parallel box, explode up. 45-60 s rest. Bar speed matters more than load"
DE_PULL_NOTE = "Speed pulls: reset each rep, pull as fast as you can. 45-60 s rest"
DE_BENCH_NOTE = "Speed: change grip every 3 sets (close, medium, wide), press as fast as you can"


def cycle_of(week: int) -> int:
    return 0 if week == 0 else min(CYCLES + 1, (week - 1) // CYCLE_WEEKS + 1)


def _rotate(lift: str, cycle: int, block: int) -> str:
    options = ROTATION[lift]
    return options[((max(cycle, 1) - 1) * 3 + block) % len(options)]


def _me_lower(cycle: int, block: int) -> str:
    """Squat variation one block, deadlift variation the next; the order flips each cycle."""
    lift = "Squat" if (cycle + block) % 2 else "Deadlift"
    return _rotate(lift, cycle, block)


def _plyo(name, sets, reps, note=None):
    return Prescription(name, sets, str(reps), note=note or PLYO_NOTES[name], kind="plyo")


def _acc(day, sets, note=ACCESSORY_NOTE):
    return [Prescription(a, sets, r, note=note, kind="accessory") for a, r in ACCESSORIES[day]]


def _baseline(day):
    note = "Optional - skip if you entered maxes. Work up to a hard set of 5 (or a 1RM if you're experienced)"
    lift = TESTS[day]
    plyo = TEST_PLYOS.get(day)
    out = [_plyo(plyo, 1, "Max", "Find your best: log it and check the standards on Start Here")] if plyo else []
    out.append(Prescription(lift, 1, "5RM", None, note, "test"))
    return out + _acc(day, 2, "Find a weight you can do for the top of the range")


def _training_week(day, cycle, block, idx, phase):
    """A normal loading week (idx = week within the 3-week wave)."""
    if day == 0:
        return [_plyo("Box Jump", 3, 3), Prescription(_me_lower(cycle, block), 1, "1-3RM", None, ME_NOTE,
                                                      "variation")] + _acc(0, 3)
    if day == 1:
        return [_plyo("Med Ball Chest Pass", 3, 5),
                Prescription(_rotate("Bench Press", cycle, block), 1, "1-3RM", None, ME_NOTE, "variation")] + _acc(1, 3)
    if day == 2:
        return [_plyo("Broad Jump", 3, 3),
                Prescription("Box Squat", 10, "2", WAVES[idx], DE_SQUAT_NOTE, "main"),
                Prescription("Deadlift", 6, "1", PULL_WAVES[idx], DE_PULL_NOTE, "main")] + _acc(2, 3)
    sets, reps, pcts = OHP[block]
    return [_plyo("Plyo Push-up", 3, 5),
            Prescription("Bench Press", 9, "3", WAVES[idx], DE_BENCH_NOTE, "main"),
            Prescription("Overhead Press", sets, reps, pcts[min(idx, len(pcts) - 1)], kind="main")] + _acc(3, 3)


def _deload(day, cycle, block):
    easy = "Easy week - move fast, recover"
    if day == 0:
        return [_plyo("Box Jump", 2, 3), Prescription(_me_lower(cycle, block), 3, "3", 70.0, easy, "variation")] \
            + _acc(0, 2, "Easy - stop well short of failure")
    if day == 1:
        return [_plyo("Med Ball Chest Pass", 2, 5),
                Prescription(_rotate("Bench Press", cycle, block), 3, "3", 70.0, easy, "variation")] \
            + _acc(1, 2, "Easy - stop well short of failure")
    if day == 2:
        return [_plyo("Broad Jump", 2, 3), Prescription("Box Squat", 6, "2", 50.0, easy, "main"),
                Prescription("Deadlift", 4, "1", 60.0, easy, "main")] + _acc(2, 2, "Easy - stop well short of failure")
    return [_plyo("Plyo Push-up", 2, 5), Prescription("Bench Press", 6, "3", 50.0, easy, "main"),
            Prescription("Overhead Press", 3, "5", 60.0, easy, "main")] + _acc(3, 2, "Easy - stop well short of failure")


def _taper(day):
    short = "Keep it heavy but short - no grinding"
    lift = TESTS[day]
    plyo = PLYOS[day]
    return [_plyo(plyo, 2, 2 if plyo != "Med Ball Chest Pass" else 3),
            Prescription(lift, 3 if day < 2 else 2, "2", 80.0, short, "main")] \
        + _acc(day, 2, "Light - save energy for test week")


def _test(day):
    out = []
    if day in TEST_PLYOS:
        out.append(_plyo(TEST_PLYOS[day], 1, "Max", "Test day: best of 3-5. Log it and check the standards on Start Here"))
    out.append(Prescription(TESTS[day], 1, "Max", None, TEST_NOTE, "test"))
    return out + _acc(day, 2, "Light")


def _transition(day, week_in):
    if week_in == 4:
        pct, sets, reps, note, acc = 55.0, 2, "5", "Full recovery week before the next year", "Easy"
    else:
        pct, sets, reps, note, acc = (60.0, 62.5, 65.0)[week_in - 1], 3, "8", "Easy volume - stay 3+ reps from failure", \
            ACCESSORY_NOTE
    return [_plyo(PLYOS[day], 2, 3), Prescription(TESTS[day], sets, reps, pct, note, "main")] + \
        _acc(day, 2 if week_in == 4 else 3, acc)


def _sessions(week: int) -> list[Session]:
    cycle = cycle_of(week)
    out = []
    for day, name in enumerate(DAY_NAMES):
        if week == 0:
            phase, ex = "Baseline", _baseline(day)
        elif cycle == CYCLES + 1:
            week_in = week - CYCLES * CYCLE_WEEKS
            phase, ex = ("Deload" if week_in == 4 else "Transition"), _transition(day, week_in)
        else:
            w = (week - 1) % CYCLE_WEEKS + 1
            block = 0 if w <= 4 else 1 if w <= 8 else 2
            if w in (4, 8):
                phase, ex = "Deload", _deload(day, cycle, block)
            elif w == 11:
                phase, ex = "Taper", _taper(day)
            elif w == 12:
                phase, ex = "Test", _test(day)
            else:
                idx = (w - 1) % 4
                phase = ("Wave 1", "Wave 2", "Wave 3")[block]
                ex = _training_week(day, cycle, block, idx, phase)
        out.append(Session(week, cycle, phase, day, name, tuple(ex)))
    return out


def build():
    return [s for week in range(0, WEEKS + 1) for s in _sessions(week)]
