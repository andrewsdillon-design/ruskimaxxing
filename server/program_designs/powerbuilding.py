"""Powerbuilding: strength and size together, for men and women, 2 or 4 days a week.

Every main lift is a heavy top set followed by lighter back-off sets: the top set builds strength, the
back-offs add volume. After the main lifts come a compound in the 6-10 rep range and accessories for
size, with double progression.

    Top set      the day's heaviest set, a few reps short of failure
    Back-offs    3 sets (2 for deadlifts) at a lighter weight for more reps
    Volume       one compound variation, 3 x 6-10 at a percent of its own training max
    Accessories  3 sets of 8-15, 1-2 reps in the tank; when every set hits the top of the range,
                 add weight

The year keeps RuskiMaxxing's 12-week cycle, so clubs test together and leaderboards stay in step:

    weeks 1-3   Hypertrophy  top set of 6, back-offs of 8, volume 3 x 10
    week 4      deload
    weeks 5-7   Strength     top set of 4, back-offs of 6, volume 3 x 8
    week 8      deload
    weeks 9-10  Peak         top set of 2, back-offs of 4, volume 3 x 6
    week 11     taper        heavy doubles, half the volume
    week 12     test         squat, bench press, deadlift and overhead press
    weeks 49-52 transition   easy volume, then a full deload

Percents are of each exercise's training max (its estimated 1RM). They were checked against the
Epley rep table that the site uses. Top sets run from about 4 reps in the tank in week 1 to about
1 rep in the tank in the last week of each block. Back-off sets stay 2-5 reps short of failure.
That is hard enough to grow without grinding, and it works the same for men and women.

The volume compound's variation changes every block, the same way the Year 1 Day 3 variations do.
"""

from ruskimaxxing.program import CYCLE_WEEKS, CYCLES, PLYO_NOTES, TEST_NOTE, WEEKS, Prescription, Session

# by block: top set reps and % by week; back-off reps and % by week; volume reps and % by week
TOP = (("6", (75.0, 77.5, 80.0)), ("4", (80.0, 82.5, 85.0)), ("2", (87.5, 90.0)))
BACKOFF = (("8", (70.0, 72.5, 75.0)), ("6", (72.5, 75.0, 77.5)), ("4", (80.0, 82.5)))
VOLUME = (("10", (65.0, 67.5, 70.0)), ("8", (70.0, 72.5, 75.0)), ("6", (75.0, 77.5)))
PHASES = ("Hypertrophy", "Strength", "Peak")

TOP_NOTE = "Top set: the day's heaviest. Stop with 1-3 good reps left - no grinding"
BACKOFF_NOTE = "Back-off sets: same clean form, fast reps"
VOLUME_NOTE = "Controlled down, strong up. 2-3 reps in the tank"
ACC_NOTE = ("1-2 reps in the tank. When every set reaches the top of the range, add weight next time "
            "(5 lb / 2.5 kg, or the next dumbbell)")
EASY = "Easy - stop well short of failure"

# New accessories (not in the RuskiMaxxing app's catalog)
EXTRA_EXERCISES = {
    name: {"category": "accessory", "parent": None, "ratio": None}
    for name in ("Leg Curl", "Leg Extension", "Bulgarian Split Squat", "Calf Raise", "Hip Thrust",
                 "Seated Cable Row", "Skull Crusher", "Rear Delt Fly", "Ab Wheel Rollout")
}

ROTATIONS = {
    "@squat": ("Pause Squat", "Front Squat", "Box Squat", "Pin Squat"),  # no special bars needed
    "@bench": ("Close-Grip Bench Press", "Incline Bench Press", "Spoto Press", "Pause Bench Press"),
}


def cycle_of(week: int) -> int:
    return 0 if week == 0 else min(CYCLES + 1, (week - 1) // CYCLE_WEEKS + 1)


def _volume_lift(slot: str, cycle: int, block: int) -> str:
    if slot in ROTATIONS:
        options = ROTATIONS[slot]
        return options[((max(cycle, 1) - 1) * 3 + block) % len(options)]
    return slot


def _plyo(name, sets, reps, note=None):
    return Prescription(name, sets, str(reps), note=note or PLYO_NOTES[name], kind="plyo")


class Design:
    """days: (name, plyo, strength lifts, volume slots, accessories) per training day."""

    def __init__(self, days, tested):
        self.days, self.tested = days, tested

    def _acc(self, day, sets, note=ACC_NOTE):
        return [Prescription(a, sets, r, note=note, kind="accessory") for a, r in self.days[day][4]]

    def _volume(self, day, cycle, block, sets, reps, pct, note=VOLUME_NOTE):
        out = []
        for slot in self.days[day][3]:
            lift = _volume_lift(slot, cycle, block)
            out.append(Prescription(lift, sets, reps, pct, note, "variation" if slot in ROTATIONS else "main"))
        return out

    def _training(self, day, cycle, block, idx):
        _, plyo, strength, _, _ = self.days[day]
        top_reps, top_pcts = TOP[block]
        bo_reps, bo_pcts = BACKOFF[block]
        vol_reps, vol_pcts = VOLUME[block]
        out = [_plyo(plyo, 3, 3 if plyo not in ("Med Ball Chest Pass", "Plyo Push-up") else 5)]
        for lift in strength:
            out.append(Prescription(lift, 1, top_reps, top_pcts[idx], TOP_NOTE, "main"))
            out.append(Prescription(lift, 2 if "Deadlift" in lift else 3, bo_reps, bo_pcts[idx], BACKOFF_NOTE,
                                    "main"))
        out += self._volume(day, cycle, block, 3, vol_reps, vol_pcts[idx])
        return out + self._acc(day, 3 if block < 2 else 2)

    def _deload(self, day, cycle, block, pct):
        _, plyo, strength, _, _ = self.days[day]
        out = [_plyo(plyo, 2, 3)]
        out += [Prescription(lift, 3, "5", pct, "Easy week - move fast, recover", "main") for lift in strength]
        out += self._volume(day, cycle, block, 2, "8", pct - 5, EASY)
        return out + self._acc(day, 2, EASY)

    def _taper(self, day):
        _, plyo, strength, _, _ = self.days[day]
        out = [_plyo(plyo, 2, 2)]
        out += [Prescription(lift, 3 if "Deadlift" not in lift else 2, "2", 82.5,
                             "Keep it heavy but short - no grinding", "main") for lift in strength]
        return out + self._acc(day, 2, "Light - save energy for test week")

    def _test(self, day):
        _, plyo, strength, _, _ = self.days[day]
        out = []
        for lift in strength:
            if lift in self.tested.get(day, ()):
                out.append(Prescription(lift, 1, "Max", None, TEST_NOTE, "test"))
            else:
                out.append(Prescription(lift, 2, "3", 60.0, "Light technique work", "main"))
        return out + self._acc(day, 2, "Light")

    def _baseline(self, day):
        _, plyo, strength, _, _ = self.days[day]
        note = "Optional - skip if you entered maxes. Work up to a hard set of 5 (or a 1RM if you're experienced)"
        out = [Prescription(lift, 1, "5RM", None, note, "test") for lift in strength]
        return out + self._acc(day, 2, "Find a weight you can do for the top of the range")

    def _transition(self, day, week_in):
        _, plyo, strength, _, _ = self.days[day]
        if week_in == 4:
            return [Prescription(lift, 2, "5", 55.0, "Full recovery week before the next year", "main")
                    for lift in strength] + self._acc(day, 2, "Easy")
        pct = (60.0, 62.5, 65.0)[week_in - 1]
        return [_plyo(plyo, 2, 3)] + [Prescription(lift, 3, "10", pct, "Easy volume - stay 3+ reps from failure",
                                                   "main") for lift in strength] + self._acc(day, 3)

    def sessions(self, week: int) -> list[Session]:
        cycle = cycle_of(week)
        out = []
        for day, (name, *_rest) in enumerate(self.days):
            if week == 0:
                phase, ex = "Baseline", self._baseline(day)
            elif cycle == CYCLES + 1:
                week_in = week - CYCLES * CYCLE_WEEKS
                phase, ex = ("Deload" if week_in == 4 else "Transition"), self._transition(day, week_in)
            else:
                w = (week - 1) % CYCLE_WEEKS + 1
                block = 0 if w <= 4 else 1 if w <= 8 else 2
                if w in (4, 8):
                    phase, ex = "Deload", self._deload(day, cycle, block, 60.0 if w == 4 else 65.0)
                elif w == 11:
                    phase, ex = "Taper", self._taper(day)
                elif w == 12:
                    phase, ex = "Test", self._test(day)
                else:
                    phase, ex = PHASES[block], self._training(day, cycle, block, (w - 1) % 4)
            out.append(Session(week, cycle, phase, day, name, tuple(ex)))
        return out

    def build(self) -> list[Session]:
        return [s for week in range(0, WEEKS + 1) for s in self.sessions(week)]


TWO_DAY = Design(
    (
        ("Day 1 - Squat and Bench", "Box Jump", ("Squat", "Bench Press"), ("Romanian Deadlift",),
         (("Barbell Row", "8-12"), ("Lateral Raise", "12-20"), ("Dumbbell Curl", "10-15"))),
        ("Day 2 - Deadlift and Press", "Broad Jump", ("Deadlift", "Overhead Press"), ("@squat", "@bench"),
         (("Chin-up", "6-12"), ("Triceps Pushdown", "10-15"))),
    ),
    {0: {"Squat", "Bench Press"}, 1: {"Deadlift", "Overhead Press"}},
)

FOUR_DAY = Design(
    (
        ("Day 1 - Lower: Squat", "Box Jump", ("Squat",), ("Romanian Deadlift",),
         (("Bulgarian Split Squat", "8-12 each leg"), ("Leg Curl", "10-15"), ("Calf Raise", "10-15"),
          ("Hanging Leg Raise", "10-15"))),
        ("Day 2 - Upper: Bench", "Med Ball Chest Pass", ("Bench Press",), ("Overhead Press",),
         (("Barbell Row", "8-12"), ("Chin-up", "6-12"), ("Dumbbell Curl", "10-15"), ("Triceps Pushdown", "10-15"))),
        ("Day 3 - Lower: Deadlift", "Broad Jump", ("Deadlift",), ("@squat",),
         (("Leg Press", "10-15"), ("Leg Extension", "12-15"), ("Back Extension", "10-15"),
          ("Ab Wheel Rollout", "8-12"))),
        ("Day 4 - Upper: Press", "Plyo Push-up", ("Overhead Press",), ("@bench",),
         (("One-Arm Dumbbell Row", "8-12"), ("Lat Pulldown", "10-15"), ("Lateral Raise", "12-20"),
          ("Rear Delt Fly", "15-20"), ("Skull Crusher", "10-15"))),
    ),
    {0: {"Squat"}, 1: {"Bench Press"}, 2: {"Deadlift"}, 3: {"Overhead Press"}},
)
