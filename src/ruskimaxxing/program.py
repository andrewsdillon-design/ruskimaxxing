"""12-week beginner strength and mass program.

Structure (Verkhoshansky-style blocks, daily undulating intensity):

    Weeks 1-3   Accumulation   build muscle and work capacity (higher reps)
    Week  4     Deload
    Weeks 5-7   Transmutation  convert size into strength (moderate reps)
    Week  8     Deload
    Weeks 9-11  Realization    heavier, lower-rep strength work
    Week  12    Test           AMRAP sets to estimate new 1RMs

Three full-body days per week. Each main lift's intensity changes day to day
(heavy / medium / light), and Prilepin's chart sets the sets x reps for that
intensity. Accessory work adds the hypertrophy volume beginners need for mass.
"""

import math
from dataclasses import dataclass, field

from ruskimaxxing.prilepin import load, zone_for

MAIN_LIFTS = ("Squat", "Bench Press", "Deadlift", "Overhead Press")
WEEKS = 12


@dataclass(frozen=True)
class Block:
    name: str
    goal: str
    weeks: tuple[int, ...]
    # %1RM for heavy / medium / light days, one value per loading week
    intensity: dict[str, tuple[float, ...]]
    rep_bias: str  # "high" or "mid" end of Prilepin's reps-per-set range
    accessory_sets: int


BLOCKS = (
    Block("Accumulation", "Build muscle and work capacity", (1, 2, 3),
          {"heavy": (70, 72.5, 75), "medium": (65, 67.5, 70), "light": (60, 62.5, 65)},
          "high", 4),
    Block("Transmutation", "Turn new muscle into strength", (5, 6, 7),
          {"heavy": (77.5, 80, 82.5), "medium": (72.5, 75, 77.5), "light": (65, 67.5, 70)},
          "high", 3),
    Block("Realization", "Heavier, lower-rep strength work", (9, 10, 11),
          {"heavy": (85, 87.5, 90), "medium": (77.5, 80, 82.5), "light": (67.5, 70, 72.5)},
          "mid", 3),
)

DELOAD_WEEKS = {4: 60.0, 8: 65.0}  # week -> %1RM for all main lifts
TEST_WEEK = 12
TEST_PERCENT = 85.0

# (day name, [(main lift, day intensity)], [(accessory, reps)])
DAYS = (
    ("Day 1 - Heavy",
     [("Squat", "heavy"), ("Bench Press", "heavy")],
     [("Barbell Row", "8-10"), ("Face Pull", "12-15"), ("Dumbbell Curl", "10-12")]),
    ("Day 2 - Light",
     [("Squat", "light"), ("Overhead Press", "heavy"), ("Deadlift", "medium")],
     [("Chin-up or Lat Pulldown", "6-10"), ("Back Extension", "10-15"), ("Plank", "30-60s")]),
    ("Day 3 - Medium",
     [("Squat", "medium"), ("Bench Press", "medium")],
     [("Romanian Deadlift", "8-10"), ("Incline Dumbbell Press", "8-12"),
      ("One-Arm Dumbbell Row", "10-12"), ("Triceps Pushdown", "10-15")]),
)

ACCESSORY_NOTE = "Leave 1-2 reps in the tank; add weight when you hit the top of the range"


@dataclass(frozen=True)
class Prescription:
    exercise: str
    sets: int
    reps: str
    percent: float | None = None  # %1RM for main lifts, None for accessories
    note: str = ""

    @property
    def is_main(self) -> bool:
        return self.percent is not None

    def weight(self, maxes: dict[str, float], increment: float) -> float | None:
        one_rm = maxes.get(self.exercise)
        if self.percent is None or not one_rm:
            return None
        return load(one_rm, self.percent, increment)


@dataclass(frozen=True)
class Session:
    week: int
    phase: str
    day: str
    exercises: list[Prescription] = field(default_factory=list)


def estimate_1rm(weight: float, reps: int) -> float:
    """Epley estimate of a one-rep max from a set of `reps` at `weight`."""
    if weight < 0 or reps < 1:
        raise ValueError("weight must be >= 0 and reps >= 1")
    if reps == 1:
        return float(weight)
    return weight * (1 + reps / 30)


def _sets_reps(percent: float, bias: str, lift: str, day: str) -> tuple[int, int]:
    zone = zone_for(percent)
    lo, hi = zone.reps_per_set
    reps = hi if bias == "high" else (lo + hi + 1) // 2
    # Light days and deadlifts use the low end of Prilepin's total-rep range
    total = zone.total_range[0] if day == "light" or lift == "Deadlift" else zone.optimal_total
    return max(3, math.ceil(total / reps)), reps


def _loading_session(block: Block, week: int, day: tuple) -> Session:
    name, lifts, accessories = day
    idx = block.weeks.index(week)
    exercises = []
    for lift, intensity in lifts:
        pct = block.intensity[intensity][idx]
        sets, reps = _sets_reps(pct, block.rep_bias, lift, intensity)
        exercises.append(Prescription(lift, sets, str(reps), pct))
    exercises += [Prescription(a, block.accessory_sets, r, note=ACCESSORY_NOTE) for a, r in accessories]
    return Session(week, block.name, name, exercises)


def _deload_session(week: int, day: tuple) -> Session:
    name, lifts, accessories = day
    pct = DELOAD_WEEKS[week]
    exercises = [Prescription(lift, 2, "5", pct, "Easy week - move fast, recover") for lift, _ in lifts]
    exercises += [Prescription(a, 2, r, note="Easy - stop well short of failure") for a, r in accessories]
    return Session(week, "Deload", name, exercises)


def _test_session(day_index: int, day: tuple) -> Session:
    name, lifts, accessories = day
    tested = {0: ("Squat", "Bench Press"), 1: ("Deadlift", "Overhead Press")}.get(day_index, ())
    exercises = []
    for lift, _ in lifts:
        if lift in tested:
            exercises.append(Prescription(
                lift, 1, "AMRAP", TEST_PERCENT,
                "Warm up, then as many clean reps as possible; stop before form breaks"))
        else:
            exercises.append(Prescription(lift, 2, "5", 60.0, "Light technique work"))
    exercises += [Prescription(a, 2, r, note="Light") for a, r in accessories]
    if day_index == 2:
        exercises.append(Prescription(
            "Next cycle", 0, "-", note="Enter your new estimated 1RMs and start again at week 1"))
    return Session(TEST_WEEK, "Test", name, exercises)


def build_program() -> list[Session]:
    """All sessions for the 12-week program, in order."""
    sessions = []
    for week in range(1, WEEKS + 1):
        block = next((b for b in BLOCKS if week in b.weeks), None)
        for i, day in enumerate(DAYS):
            if block:
                sessions.append(_loading_session(block, week, day))
            elif week in DELOAD_WEEKS:
                sessions.append(_deload_session(week, day))
            else:
                sessions.append(_test_session(i, day))
    return sessions


def phase_for_week(week: int) -> str:
    return next(s.phase for s in build_program() if s.week == week)
