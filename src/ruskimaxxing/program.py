"""One-year beginner strength and mass program.

The year is four 12-week cycles plus a 4-week transition:

    Week 0          Baseline test (optional - skip if you enter known maxes)
    Weeks 1-48      4 cycles of 12 weeks, maxes tested in weeks 12, 24, 36, 48
    Weeks 49-52     Transition: lighter hypertrophy work, then a full deload

Each 12-week cycle (Verkhoshansky-style blocks, daily undulating intensity):

    1-3   Accumulation    build muscle and work capacity (higher reps)
    4     Deload
    5-7   Transmutation   turn new muscle into strength
    8     Deload
    9-10  Realization     heavy, lower-rep strength work
    11    Taper           volume cut ~50%, intensity kept - arrive at the test fresh
    12    Test            new maxes on every main lift, the block's variations and jumps

Three full-body days per week, each opening with plyometrics (box jump / broad
jump). Days 1-2 train the competition lifts; Day 3 is a conjugate max-effort day
whose variations rotate every 3-week block. The supertotal edition adds the
snatch (Day 1), clean & jerk (Day 2) and a rotating Olympic variation (Day 3).

Every percentage is of that exercise's own training max (the best estimated 1RM
logged before the cycle started), so each cycle builds on the last test.
Prilepin's chart sets sets x reps for every loaded session.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

from ruskimaxxing.edition import is_supertotal
from ruskimaxxing.exercises import CATALOG, MAIN, OLY, PLYO_GUIDE, ROTATION
from ruskimaxxing.prilepin import load, zone_for

WEEKS = 52
CYCLE_WEEKS = 12
CYCLES = 4
TEST_WEEKS = tuple(c * CYCLE_WEEKS for c in range(1, CYCLES + 1))  # 12, 24, 36, 48
DAY_OFFSETS = (0, 2, 4)  # Mon / Wed / Fri when week 1 starts on a Monday
MAIN_LIFTS = MAIN


@dataclass(frozen=True)
class Block:
    name: str
    weeks: tuple[int, ...]  # week numbers inside the cycle
    intensity: dict[str, tuple[float, ...]]  # %TM per day type, one per loading week
    rep_bias: str
    accessory_sets: int
    plyo: tuple[int, int]  # sets, reps


BLOCKS = (
    Block("Accumulation", (1, 2, 3),
          {"heavy": (70, 72.5, 75), "medium": (65, 67.5, 70), "light": (60, 62.5, 65)}, "high", 4, (4, 3)),
    Block("Transmutation", (5, 6, 7),
          {"heavy": (77.5, 80, 82.5), "medium": (72.5, 75, 77.5), "light": (65, 67.5, 70)}, "high", 3, (4, 3)),
    Block("Realization", (9, 10),
          {"heavy": (85, 90), "medium": (77.5, 80), "light": (67.5, 70)}, "mid", 3, (3, 2)),
)
DELOAD = {4: 60.0, 8: 65.0}  # cycle week -> %TM
TAPER_WEEK, TEST_WEEK = 11, 12

SLOTS = {"@squat": "Squat", "@bench": "Bench Press", "@deadlift": "Deadlift", "@olympic": "Olympic",
         "@plyo": "Plyo"}
# Jump tested (and baselined) each day of a test week
TEST_PLYO = ("Box Jump", "Broad Jump", "Vertical Jump")

if is_supertotal():
    DAYS = (
        ("Day 1 - Heavy", ("Box Jump",),
         [("Snatch", "heavy"), ("Squat", "heavy"), ("Bench Press", "heavy")],
         [("Barbell Row", "8-10"), ("Face Pull", "12-15")]),
        ("Day 2 - Light", ("Broad Jump", "Med Ball Chest Pass"),
         [("Clean & Jerk", "heavy"), ("Squat", "light"), ("Overhead Press", "medium"), ("Deadlift", "medium")],
         [("Chin-up", "6-10"), ("Plank", "30-60s")]),
        ("Day 3 - Variations", ("@plyo",),
         [("@olympic", "medium"), ("@squat", "medium"), ("@bench", "medium"), ("@deadlift", "light")],
         [("Incline Dumbbell Press", "8-12"), ("Triceps Pushdown", "10-15")]),
    )
    TESTED = {0: {"Snatch", "Squat", "Bench Press"}, 1: {"Clean & Jerk", "Deadlift", "Overhead Press"}}
else:
    DAYS = (
        ("Day 1 - Heavy", ("Box Jump",),
         [("Squat", "heavy"), ("Bench Press", "heavy")],
         [("Barbell Row", "8-10"), ("Face Pull", "12-15"), ("Dumbbell Curl", "10-12")]),
        ("Day 2 - Light", ("Broad Jump", "Med Ball Chest Pass"),
         [("Squat", "light"), ("Overhead Press", "heavy"), ("Deadlift", "medium")],
         [("Chin-up", "6-10"), ("Back Extension", "10-15"), ("Plank", "30-60s")]),
        ("Day 3 - Variations", ("@plyo",),
         [("@squat", "medium"), ("@bench", "medium"), ("@deadlift", "light")],
         [("Incline Dumbbell Press", "8-12"), ("One-Arm Dumbbell Row", "10-12"), ("Triceps Pushdown", "10-15")]),
    )
    TESTED = {0: {"Squat", "Bench Press"}, 1: {"Deadlift", "Overhead Press"}}

ACCESSORY_NOTE = "Leave 1-2 reps in the tank; add weight when you hit the top of the range"
TEST_NOTE = "Work up in small jumps to a new max (1RM, or a 3RM/5RM if you prefer). Log it - it sets next cycle's weights"
PLYO_NOTES = PLYO_GUIDE


@dataclass(frozen=True)
class Prescription:
    exercise: str
    sets: int
    reps: str
    percent: float | None = None  # % of this exercise's training max
    note: str = ""
    kind: str = "main"  # "main", "variation", "accessory", "plyo" or "test"

    @property
    def is_loaded(self) -> bool:
        return self.percent is not None

    @property
    def is_main(self) -> bool:  # kept for older callers
        return self.is_loaded

    def weight(self, training_max: float | None, increment: float) -> float | None:
        if self.percent is None or not training_max:
            return None
        return load(training_max, self.percent, increment)


@dataclass(frozen=True)
class Session:
    week: int
    cycle: int  # 0 = baseline, 1-4 = cycles, 5 = transition
    phase: str
    day_index: int
    day: str
    exercises: tuple[Prescription, ...]

    def date(self, start: date) -> date:
        return start + timedelta(weeks=self.week - 1, days=DAY_OFFSETS[self.day_index])


def cycle_of(week: int) -> int:
    if week == 0:
        return 0
    return min(CYCLES + 1, (week - 1) // CYCLE_WEEKS + 1)


def cycle_start(start: date, cycle: int) -> date:
    """First day of a cycle; its training maxes use sets logged before this date."""
    return start + timedelta(weeks=max(0, cycle - 1) * CYCLE_WEEKS)


def variation(lift: str, cycle: int, block: int) -> str:
    """Variation used for `lift` in block 0-2 of `cycle` (cycle 5 = transition)."""
    options = ROTATION[lift]
    return options[((max(cycle, 1) - 1) * 3 + block) % len(options)]


def is_olympic(exercise: str) -> bool:
    info = CATALOG.get(exercise)
    return exercise in OLY or bool(info and info.parent in OLY)


def _resolve(slot: str, cycle: int, block: int) -> tuple[str, str]:
    if slot in SLOTS:
        return variation(SLOTS[slot], cycle, block), "variation"
    return slot, "main"


def _sets_reps(percent: float, bias: str, lift: str, day: str) -> tuple[int, int]:
    zone = zone_for(percent)
    lo, hi = zone.reps_per_set
    if is_olympic(lift):
        # Olympic lifts: low reps per set, low end of Prilepin's total range
        return max(3, math.ceil(zone.total_range[0] / lo)), lo
    reps = hi if bias == "high" else (lo + hi + 1) // 2
    # Light days and deadlift patterns use the low end of Prilepin's total-rep range
    pulls = "Deadlift" in lift or "Pull" in lift
    total = zone.total_range[0] if day == "light" or pulls else zone.optimal_total
    return max(3, math.ceil(total / reps)), reps


def _accessories(accessories, sets, note=ACCESSORY_NOTE):
    return [Prescription(a, sets, r, note=note, kind="accessory") for a, r in accessories]


def _plyo(name, sets, reps, note=None):
    return Prescription(name, sets, str(reps), note=note or PLYO_NOTES[name], kind="plyo")


def _plyos(slots, cycle, block, sets, reps):
    out = []
    for slot in slots:
        name = _resolve(slot, cycle, block)[0]
        if name == "Med Ball Chest Pass":
            out.append(_plyo(name, max(2, sets - 1), 5 if sets > 2 else 3))
        else:
            out.append(_plyo(name, sets, reps))
    return out


def _plyo_test(day_index, baseline=False):
    name = TEST_PLYO[day_index]
    note = ("Find your best: " if baseline else "Test day: ") + {
        "Box Jump": "work up box by box to the highest box you land cleanly",
        "Broad Jump": "best of 3-5 jumps for distance",
        "Vertical Jump": "best of 3-5 jumps (jump mark minus standing reach)",
    }[name] + ". Log it and check the standards on Start Here"
    return _plyo(name, 1, "Max", note)


def _session(week: int) -> list[Session]:
    cycle = cycle_of(week)
    sessions = []
    for i, (name, plyo, lifts, accessories) in enumerate(DAYS):
        # plyo is a tuple of plyo slots; "@plyo" rotates with the variation blocks
        if week == 0:
            phase = "Baseline"
            exercises = [_plyo_test(i, baseline=True)]
            for s, _ in lifts:
                ex, _ = _resolve(s, 1, 0)
                if ex == "Squat" and i == 1:
                    continue
                reps = "1RM" if is_olympic(ex) else "5RM"
                note = ("Work up to a technically clean heavy single" if is_olympic(ex) else
                        "Work up to a hard set of 5 (or a 1RM if you're experienced)")
                exercises.append(Prescription(ex, 1, reps, None, "Optional - skip if you entered maxes. " + note, "test"))
            exercises += _accessories(accessories, 2, "Find a weight you can do for the top of the range")
        elif cycle == CYCLES + 1:
            week_in = week - CYCLES * CYCLE_WEEKS  # 1-4
            resolved = [_resolve(s, cycle, 0) for s, _ in lifts]
            if week_in < 4:
                phase = "Transition"
                pct = (60, 62.5, 65)[week_in - 1]
                exercises = _plyos(plyo, cycle, 0, 3, 3)
                exercises += [Prescription(ex, 3, "3" if is_olympic(ex) else "8", pct,
                                           "Easy volume - stay 3+ reps from failure", kind) for ex, kind in resolved]
                exercises += _accessories(accessories, 4)
            else:
                phase = "Deload"
                exercises = _plyos(plyo, cycle, 0, 2, 3)
                exercises += [Prescription(ex, 2, "2" if is_olympic(ex) else "5", 55.0,
                                           "Full recovery week before the next year", kind) for ex, kind in resolved]
                exercises += _accessories(accessories, 2, "Easy")
        else:
            w = (week - 1) % CYCLE_WEEKS + 1
            block_idx = 0 if w <= 4 else 1 if w <= 8 else 2
            block = next((b for b in BLOCKS if w in b.weeks), None)
            resolved = [(*_resolve(s, cycle, block_idx), intensity) for s, intensity in lifts]
            if block:
                phase = block.name
                idx = block.weeks.index(w)
                exercises = _plyos(plyo, cycle, block_idx, *block.plyo)
                for ex, kind, intensity in resolved:
                    pct = block.intensity[intensity][idx]
                    sets, reps = _sets_reps(pct, block.rep_bias, ex, intensity)
                    exercises.append(Prescription(ex, sets, str(reps), pct, kind=kind))
                exercises += _accessories(accessories, block.accessory_sets)
            elif w in DELOAD:
                phase = "Deload"
                exercises = _plyos(plyo, cycle, block_idx, 2, 3)
                exercises += [Prescription(ex, 2, "2" if is_olympic(ex) else "5", DELOAD[w],
                                           "Easy week - move fast, recover", kind) for ex, kind, _ in resolved]
                exercises += _accessories(accessories, 2, "Easy - stop well short of failure")
            elif w == TAPER_WEEK:
                phase = "Taper"
                exercises = _plyos(plyo, cycle, block_idx, 2, 2)
                for ex, kind, intensity in resolved:
                    if kind == "variation":
                        exercises.append(Prescription(ex, 2, "2" if is_olympic(ex) else "3", 75.0, "Crisp and fast", kind))
                    elif intensity == "light":
                        exercises.append(Prescription(ex, 2, "3", 65.0, "Easy", kind))
                    else:
                        exercises.append(Prescription(ex, 3 if i == 0 else 2, "1" if is_olympic(ex) else "2", 80.0,
                                                      "Keep it heavy but short - no grinding", kind))
                exercises += _accessories(accessories, 2, "Light - save energy for test week")
            else:
                phase = "Test"
                tested = TESTED.get(i, set())
                exercises = [_plyo_test(i)]
                for ex, kind, _ in resolved:
                    if kind == "variation":
                        reps = "1RM" if is_olympic(ex) else "3RM"
                        exercises.append(Prescription(ex, 1, reps, None,
                                                      f"Work up to a {reps} - tracked as its own PR", "test"))
                    elif ex in tested:
                        exercises.append(Prescription(ex, 1, "Max", None, TEST_NOTE, "test"))
                    else:
                        exercises.append(Prescription(ex, 2, "3", 60.0, "Light technique work", kind))
                exercises += _accessories(accessories, 2, "Light")
        sessions.append(Session(week, cycle, phase, i, name, tuple(exercises)))
    return sessions


def build_program() -> list[Session]:
    """Every session of the year, week 0 (baseline) through week 52."""
    return [s for week in range(0, WEEKS + 1) for s in _session(week)]


def week_label(week: int) -> str:
    phase = _session(week)[0].phase
    if week == 0:
        return "Week 0 - Baseline test (optional)"
    cycle = cycle_of(week)
    if cycle > CYCLES:
        return f"Week {week} - Transition" + (" - Deload" if phase == "Deload" else "")
    return f"Week {week} - Cycle {cycle} - {phase}"


MONTH_WEEKS = 4
MONTHS = WEEKS // MONTH_WEEKS  # 13 training months of 4 weeks; 3 months = one 12-week cycle


def month_of(week: int) -> int:
    """Training month (1-13) a week belongs to; week 0 (baseline) is month 0."""
    return 0 if week == 0 else (week - 1) // MONTH_WEEKS + 1


def month_weeks(month: int) -> list[int]:
    return [0] if month == 0 else list(range((month - 1) * MONTH_WEEKS + 1, month * MONTH_WEEKS + 1))


def bodyfat_week(month: int) -> int:
    """Program week of the monthly body-fat test: the first week of each training month."""
    return (month - 1) * MONTH_WEEKS + 1


SHOULDER_TIP = ("SHOULDER TIP - for you malchiki with no shoulder development: 100 reps each of front raises, "
                "lateral (medial) raises and rear delt raises EVERY night before bed with 5 lb (2.5 kg) "
                "dumbbells. Go buy a pair and keep them by your nightstand.")


def next_monday(today: date | None = None) -> date:
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)
