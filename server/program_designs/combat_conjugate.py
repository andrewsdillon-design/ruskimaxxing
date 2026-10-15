"""Combat Sports Conjugate 2-Day: Westside-style upper/lower strength for wrestlers, grapplers, boxers,
kickboxers and MMA fighters, twice a week, with only a few minutes of conditioning.

The mat, the bag and sparring are where a fighter builds the gas tank, so the lifting is kept short and
crisp: get stronger and faster without leaving them too sore or tired for practice. Each day pairs a
max-effort lift with a dynamic-effort lift, then work for the neck, grip, hips and trunk that the sport
punishes, then one short power finisher instead of long conditioning.

    Day 1 - Lower    jump; work up to a 1-3RM on a rotating squat or deadlift variation; speed pulls or
                     speed box squats (whichever the max-effort lift wasn't); split squats, hamstrings,
                     groin and neck; a short sled sprint
    Day 2 - Upper    med ball throw; work up to a 1-3RM on a rotating press variation; speed bench;
                     weighted pull-ups, landmine press, anti-rotation and neck; heavy carries for grip

It keeps RuskiMaxxing's 12-week calendar so clubs test together:

    weeks 1-3   wave 1      dynamic work at 50 / 55 / 60% of the exercise's training max (pulls 60-70%)
    week 4      deload      variations rotate every block
    weeks 5-7   wave 2
    week 8      deload
    weeks 9-10  wave 3
    week 11     taper       heavy but short, no finisher
    week 12     test        vertical jump, squat and deadlift on Day 1; bench press on Day 2
    weeks 49-52 transition  easy volume, then a full deload

Max-effort work stops at the best clean single, double or triple - no grinders. Train on the days
furthest from hard sparring, and in fight week skip the max-effort lift and do the speed work only.
"""

from ruskimaxxing.program import CYCLE_WEEKS, CYCLES, PLYO_NOTES, TEST_NOTE, WEEKS, Prescription, Session

DAYS_PER_WEEK = 2
DAY_NAMES = ("Day 1 - Lower", "Day 2 - Upper")

EXTRA_EXERCISES = {
    **{name: {"category": "accessory", "parent": None, "ratio": None}
       for name in ("Bulgarian Split Squat", "Nordic Curl", "Copenhagen Plank", "Neck Harness Extension",
                    "Plate Neck Flexion", "Landmine Press", "Pallof Press", "Weighted Pull-up")},
    "Med Ball Rotational Throw": {"category": "plyo", "parent": None, "ratio": None},
    **{name: {"category": "strongman", "parent": None, "ratio": None} for name in ("Sled Push", "Farmer's Carry")},
}

# Max-effort variations, rotated every 4-week block. All of them work with a normal barbell except the
# safety squat bar, which is kind to shoulders that take a beating in grappling.
ME_SQUAT = ("Box Squat", "Front Squat", "Safety Bar Squat", "Pause Squat", "Pin Squat")
ME_PULL = ("Block Pull", "Paused Deadlift", "Deficit Deadlift", "Sumo Deadlift")
ME_PRESS = ("Floor Press", "Close-Grip Bench Press", "Spoto Press", "Pin Press", "Pause Bench Press",
            "2-Board Press")
LOWER_PLYOS = ("Broad Jump", "Lateral Bound", "Vertical Jump")
UPPER_PLYOS = ("Med Ball Chest Pass", "Med Ball Rotational Throw", "Plyo Push-up")

ROTATIONAL_NOTE = ("Side-on to a wall, load the back hip and throw the ball through the wall as hard as you can. "
                   "Every rep is a max-effort throw; switch sides each set")
PLYO = {**PLYO_NOTES, "Med Ball Rotational Throw": ROTATIONAL_NOTE}

WAVES = (50.0, 55.0, 60.0)  # dynamic effort, % of the exercise's own training max, by week in the block
PULL_WAVES = (60.0, 65.0, 70.0)

ME_NOTE = ("Work up in 4-6 jumps to the heaviest clean single, double or triple. Stop when the bar slows down - "
           "no grinders, a fighter can't afford a tweaked back. Log the top set - it's this variation's PR")
DE_SQUAT_NOTE = "Speed: sit back to a parallel box, explode up. 45-60 s rest. Bar speed matters more than load"
DE_PULL_NOTE = "Speed pulls: reset each rep, pull as fast as you can. 45-60 s rest"
DE_BENCH_NOTE = "Speed: change grip every 2 sets (close, medium, wide), press as fast as you can"
ACC = "Leave 2 reps in the tank so you're fresh for practice; add weight when you hit the top of the range"
NECK = ("Start light; slow, controlled reps through a full pain-free range. A strong neck helps you take a hit "
        "and hold position in a scramble")
SLED = ("Short and all-out: 15 seconds of hard driving, walk back, rest until you're ready to go hard again. "
        "No sled? 6 x 8-second all-out bike sprints with 60 s rest")
CARRY = "Heaviest handles or dumbbells you can hold the whole way. Stand tall, crush the handles"

LOWER_ACC = [("Bulgarian Split Squat", "6-8 each leg"), ("Nordic Curl", "4-6"), ("Copenhagen Plank", "20-30s each side"),
             ("Neck Harness Extension", "15-20")]
UPPER_ACC = [("Weighted Pull-up", "5-8"), ("Landmine Press", "6-8 each arm"),
             ("Pallof Press", "10 each side"), ("Plate Neck Flexion", "15-20")]


def cycle_of(week: int) -> int:
    return 0 if week == 0 else min(CYCLES + 1, (week - 1) // CYCLE_WEEKS + 1)


def _pick(options, cycle: int, block: int) -> str:
    return options[((max(cycle, 1) - 1) * 3 + block) % len(options)]


def _me_is_squat(cycle: int, block: int) -> bool:
    """Squat variation one block, deadlift variation the next; the order flips each cycle."""
    return bool((cycle + block) % 2)


def _plyo(name, sets, reps, note=None):
    return Prescription(name, sets, str(reps), note=note or PLYO[name], kind="plyo")


def _acc(day, sets, note=ACC):
    out = []
    for name, reps in (LOWER_ACC if day == 0 else UPPER_ACC):
        neck = "Neck" in name
        out.append(Prescription(name, 2 if neck else sets, reps, note=NECK if neck else note, kind="accessory"))
    return out


def _finisher(day, sets=None):
    if day == 0:
        return [Prescription("Sled Push", sets or 4, "15 s", note=SLED, kind="conditioning")]
    return [Prescription("Farmer's Carry", sets or 3, "40 yd", note=CARRY, kind="conditioning")]


def _baseline(day):
    note = "Optional - skip if you entered maxes. Work up to a hard set of 5 (or a 1RM if you're experienced)"
    find = "Find your best: log it and check the standards on Start Here"
    if day == 0:
        return [_plyo("Broad Jump", 1, "Max", find), Prescription("Squat", 1, "5RM", None, note, "test"),
                Prescription("Deadlift", 1, "5RM", None, note, "test")] \
            + _acc(0, 2, "Find a weight you can do for the top of the range")
    return [_plyo("Med Ball Chest Pass", 3, 3), Prescription("Bench Press", 1, "5RM", None, note, "test")] \
        + _acc(1, 2, "Find a weight you can do for the top of the range")


def _training_week(day, cycle, block, idx):
    """A normal loading week (idx = week within the 3-week wave)."""
    if day == 0:
        if _me_is_squat(cycle, block):
            me = Prescription(_pick(ME_SQUAT, cycle, block), 1, "1-3RM", None, ME_NOTE, "variation")
            de = Prescription("Deadlift", 5, "1", PULL_WAVES[idx], DE_PULL_NOTE, "main")
        else:
            me = Prescription(_pick(ME_PULL, cycle, block), 1, "1-3RM", None, ME_NOTE, "variation")
            de = Prescription("Box Squat", 6, "2", WAVES[idx], DE_SQUAT_NOTE, "main")
        plyo = LOWER_PLYOS[block]
        return [_plyo(plyo, 3, "3 each side" if plyo == "Lateral Bound" else 3), me, de] + _acc(0, 3) \
            + _finisher(0, 4 + idx)
    plyo = UPPER_PLYOS[block]
    return [_plyo(plyo, 3, "4 each side" if plyo == "Med Ball Rotational Throw" else 5),
            Prescription(_pick(ME_PRESS, cycle, block), 1, "1-3RM", None, ME_NOTE, "variation"),
            Prescription("Bench Press", 6, "3", WAVES[idx], DE_BENCH_NOTE, "main")] + _acc(1, 3) + _finisher(1)


def _deload(day, cycle, block):
    easy = "Easy week - move fast, recover"
    light = "Easy - stop well short of failure"
    if day == 0:
        squat = _me_is_squat(cycle, block)
        me = _pick(ME_SQUAT if squat else ME_PULL, cycle, block)
        return [_plyo(LOWER_PLYOS[block], 2, 3), Prescription(me, 3, "3", 70.0, easy, "variation")] \
            + _acc(0, 2, light) + _finisher(0, 3)
    return [_plyo("Med Ball Chest Pass", 2, 5),
            Prescription(_pick(ME_PRESS, cycle, block), 3, "3", 70.0, easy, "variation"),
            Prescription("Bench Press", 4, "3", 45.0, easy, "main")] + _acc(1, 2, light) + _finisher(1, 2)


def _taper(day):
    short = "Keep it heavy but short - no grinding"
    light = "Light - save energy for test week"
    if day == 0:
        return [_plyo("Vertical Jump", 2, 2), Prescription("Squat", 2, "2", 80.0, short, "main"),
                Prescription("Deadlift", 1, "2", 80.0, short, "main")] + _acc(0, 2, light)
    return [_plyo("Med Ball Chest Pass", 2, 3), Prescription("Bench Press", 3, "2", 80.0, short, "main")] \
        + _acc(1, 2, light)


def _test(day):
    test_jump = "Test day: best of 3-5. Log it and check the standards on Start Here"
    if day == 0:
        return [_plyo("Vertical Jump", 1, "Max", test_jump), Prescription("Squat", 1, "Max", None, TEST_NOTE, "test"),
                Prescription("Deadlift", 1, "Max", None, TEST_NOTE, "test")]
    return [_plyo("Med Ball Chest Pass", 2, 3), Prescription("Bench Press", 1, "Max", None, TEST_NOTE, "test")] \
        + _acc(1, 2, "Light")


def _transition(day, week_in):
    if week_in == 4:
        pct, sets, reps, note, acc = 55.0, 2, "5", "Full recovery week before the next year", "Easy"
    else:
        pct, sets, reps, note, acc = (60.0, 62.5, 65.0)[week_in - 1], 3, "8", "Easy volume - stay 3+ reps from failure", ACC
    acc_sets = 2 if week_in == 4 else 3
    if day == 0:
        return [_plyo("Broad Jump", 2, 3), Prescription("Squat", sets, reps, pct, note, "main"),
                Prescription("Deadlift", 2, reps, pct, note, "main")] + _acc(0, acc_sets, acc)
    return [_plyo("Med Ball Chest Pass", 2, 5), Prescription("Bench Press", sets, reps, pct, note, "main")] \
        + _acc(1, acc_sets, acc)


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
                phase = ("Wave 1", "Wave 2", "Wave 3")[block]
                ex = _training_week(day, cycle, block, (w - 1) % 4)
        out.append(Session(week, cycle, phase, day, name, tuple(ex)))
    return out


def build():
    return [s for week in range(0, WEEKS + 1) for s in _sessions(week)]
