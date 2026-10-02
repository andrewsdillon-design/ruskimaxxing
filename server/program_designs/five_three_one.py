"""5/3/1 Leader/Anchor: Jim Wendler's 5/3/1 (Beyond 5/3/1 style) on the club calendar, 4 days a week.

One main lift per day, in Wendler's order:

    Day 1 - Press      jumps; overhead press 5/3/1; supplemental; push, pull, core assistance
    Day 2 - Deadlift   jumps; deadlift 5/3/1; supplemental; assistance
    Day 3 - Bench      throws; bench press 5/3/1; supplemental; assistance
    Day 4 - Squat      jumps; squat 5/3/1; supplemental; assistance

Wendler's percents are of a training max (TM), a conservative fraction of your 1RM. This site stores your
estimated 1RM, so every percent here is already converted. The TM is 85% of max, which is what Wendler
recommends with 5's PRO and Boring But Big (90% makes the last 5's PRO week a near-max set of 5). So 95%
of TM is 80.75% of max, and the weights come out the way Wendler wrote them.

The year keeps RuskiMaxxing's 12-week cycle, so clubs test together and leaderboards stay in step:

    weeks 1-3   Leader 1     5's PRO (every set x 5, no AMRAP) + Boring But Big 5 x 10 at 50% TM
    week 4      7th-week deload
    weeks 5-7   Leader 2     TM up a step (+5 lb press/bench, +10 lb squat/deadlift on a typical lifter)
                             5's PRO + BBB 5 x 10 at 60% TM
    week 8      7th-week deload
    weeks 9-10  Anchor       TM up another step. 3/3/3+ and 5/3/1+ with an all-out last set,
                             then First Set Last 5 x 5
    week 11     taper        70/80/90% TM for 3/3/1, crisp and fast
    week 12     test         a new max (a heavy single, or a rep max in good form)
    weeks 49-52 transition   easy volume, then a full deload

Leaders build volume, anchors show progress. Wendler recommends 2 leaders then 1 anchor, a deload
between each, and jumps or throws before lifting. Assistance uses his 50-100 reps of push, pull and
single-leg or core work each day.
"""

from ruskimaxxing.program import CYCLE_WEEKS, CYCLES, PLYO_NOTES, WEEKS, Prescription, Session

DAYS_PER_WEEK = 4
TM = 0.85  # training max as a fraction of 1RM
BUMP = (1.0, 1.025, 1.05)  # training max steps for Leader 1, Leader 2 and Anchor

# Wendler's weeks: (% of TM, reps) for the three working sets
FIVES = ((65, 75, 85), (70, 80, 90), (75, 85, 95))
ANCHOR = (((70, "3"), (80, "3"), (90, "3+")), ((75, "5"), (85, "3"), (95, "1+")))
BBB = (50, 60)  # Boring But Big % of TM by leader
DELOAD = ((40, "5"), (50, "5"), (60, "5"))
TAPER = ((70, "3"), (80, "3"), (90, "1"))

DAYS = (
    ("Day 1 - Press", "Overhead Press", "Box Jump",
     (("Dip", "10-20"), ("Chin-up", "10-20"), ("Hanging Leg Raise", "5-10"))),
    ("Day 2 - Deadlift", "Deadlift", "Broad Jump",
     (("Push-up", "10-20"), ("One-Arm Dumbbell Row", "10-20"), ("Walking Lunge", "5-10"))),
    ("Day 3 - Bench", "Bench Press", "Med Ball Chest Pass",
     (("Dip", "10-20"), ("Barbell Row", "10-20"), ("Ab Wheel Rollout", "5-10"))),
    ("Day 4 - Squat", "Squat", "Box Jump",
     (("Push-up", "10-20"), ("Chin-up", "10-20"), ("Back Extension", "5-10"))),
)

EXTRA_EXERCISES = {name: {"category": "accessory", "parent": None, "ratio": None}
                   for name in ("Push-up", "Ab Wheel Rollout")}

PRO_NOTE = "5's PRO: all sets for exactly 5 - no AMRAP in a leader. Bar speed should stay fast"
PLUS_NOTE = ("Last set is a + set: as many good reps as you can, stopping 1 short of a grind. "
             "Log the reps - they show your progress")
BBB_NOTE = "Boring But Big: 5 x 10, same lift. Rest 60-90 s. Done with one hard set left in you"
FSL_NOTE = "First Set Last: 5 x 5 at the day's first-set weight"
ASSIST_NOTE = ("Wendler's 50-100 reps: aim for 50-100 total (25-50 for single-leg and core) in as many sets "
               "as it takes. Bodyweight or light - quality reps")
EASY = "7th-week deload: easy, crisp, out of the gym fresh"
TEST_NOTE = ("Work up to a new max: a heavy single, or a 3-5 rep max in good form. Log it - it sets the "
             "next cycle's training max")


def pct(tm_pct: float, block: int = 0) -> float:
    """% of the stored max (an estimated 1RM) for a Wendler % of training max."""
    return round(tm_pct * TM * BUMP[block], 1)


def cycle_of(week: int) -> int:
    return 0 if week == 0 else min(CYCLES + 1, (week - 1) // CYCLE_WEEKS + 1)


def _plyo(name, sets, reps):
    return Prescription(name, sets, str(reps), note=PLYO_NOTES[name], kind="plyo")


def _jumps(day, sets=3):
    name = DAYS[day][2]
    return _plyo(name, sets, 5 if name == "Med Ball Chest Pass" else 3)


def _assist(day, note=ASSIST_NOTE, sets=5):
    return [Prescription(a, sets, r, note=note, kind="accessory") for a, r in DAYS[day][3]]


def _leader(day, block, idx):
    lift = DAYS[day][1]
    out = [_jumps(day)]
    out += [Prescription(lift, 1, "5", pct(p, block), PRO_NOTE, "main") for p in FIVES[idx]]
    out.append(Prescription(lift, 5, "10", pct(BBB[block], block), BBB_NOTE, "main"))
    return out + _assist(day)


def _anchor(day, idx):
    lift = DAYS[day][1]
    sets = ANCHOR[idx]
    out = [_jumps(day)]
    out += [Prescription(lift, 1, r, pct(p, 2), PLUS_NOTE if r.endswith("+") else "", "main") for p, r in sets]
    out.append(Prescription(lift, 5, "5", pct(sets[0][0], 2), FSL_NOTE, "main"))
    return out + _assist(day)


def _sets(day, scheme, block, note):
    lift = DAYS[day][1]
    return [Prescription(lift, 1, r, pct(p, block), note, "main") for p, r in scheme]


def _baseline(day):
    note = "Optional - skip if you entered maxes. Work up to a hard set of 3-5 (or a 1RM if you're experienced)"
    return [Prescription(DAYS[day][1], 1, "5RM", None, note, "test")] + \
        _assist(day, "Find an amount you can do in good form", 3)


def _transition(day, week_in):
    lift = DAYS[day][1]
    if week_in == 4:
        return [Prescription(lift, 3, "5", pct(50), "Full recovery week before the next year", "main")] + \
            _assist(day, "Easy", 3)
    return [_jumps(day, 2), Prescription(lift, 5, "10", pct((50, 55, 60)[week_in - 1]),
                                         "Easy volume - stay 3+ reps from failure", "main")] + _assist(day)


def _sessions(week: int) -> list[Session]:
    cycle = cycle_of(week)
    out = []
    for day, (name, lift, _plyo_name, _acc) in enumerate(DAYS):
        if week == 0:
            phase, ex = "Baseline", _baseline(day)
        elif cycle == CYCLES + 1:
            week_in = week - CYCLES * CYCLE_WEEKS
            phase, ex = ("Deload" if week_in == 4 else "Transition"), _transition(day, week_in)
        else:
            w = (week - 1) % CYCLE_WEEKS + 1
            block = 0 if w <= 4 else 1 if w <= 8 else 2
            if w in (4, 8):
                phase = "Deload"
                ex = [_jumps(day, 2)] + _sets(day, DELOAD, block, EASY) + _assist(day, "Easy - half the reps", 3)
            elif w == 11:
                phase = "Taper"
                ex = [_jumps(day, 2)] + _sets(day, TAPER, 0, "Crisp and fast - arrive at test week fresh") \
                    + _assist(day, "Light - save energy for test week", 3)
            elif w == 12:
                phase = "Test"
                ex = [Prescription(lift, 1, "Max", None, TEST_NOTE, "test")] + _assist(day, "Light", 3)
            elif block < 2:
                phase, ex = f"Leader {block + 1}", _leader(day, block, (w - 1) % 4)
            else:
                phase, ex = "Anchor", _anchor(day, (w - 1) % 4)
        out.append(Session(week, cycle, phase, day, name, tuple(ex)))
    return out


def build():
    return [s for week in range(0, WEEKS + 1) for s in _sessions(week)]
