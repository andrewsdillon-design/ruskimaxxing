"""PR tracking, training maxes and body measurements.

Every logged set of every movement feeds three things:
  * rep maxes - the heaviest weight lifted for at least N reps (1RM ... 12RM)
  * best estimated 1RM (Epley)
  * the training max each 12-week cycle is built from

Bodyweight is recorded once per program week; body fat once per month.
"""

from dataclasses import dataclass
from datetime import date

from ruskimaxxing.exercises import CATALOG

REP_MAX_COUNTS = (1, 2, 3, 4, 5, 6, 8, 10, 12)
BODYFAT_METHODS = ("Bod Pod", "InBody", "Hydrostatic (dunk tank)", "DEXA", "Calipers", "Other")

BODYFAT_GUIDE = """How to measure body fat once a month

Pick ONE method and stick with it - different methods disagree by several percent,
so the trend from a single method matters far more than any one number.

Bod Pod (air displacement)
  - Find one at a university kinesiology/exercise-science lab, sports-medicine clinic
    or larger gym; search "Bod Pod near me". Usually $25-$60 per test.
  - Wear tight, minimal clothing (compression shorts / sports bra) and a swim cap.
  - Test fasted (no food 2-3 h), no exercise that day, empty bladder.

InBody (bioelectrical impedance scale)
  - Many gyms, chiropractors, physical therapists and nutrition clinics have one;
    often free or $10-$30.
  - Hydration changes the reading a lot: test first thing in the morning, before
    eating, drinking large amounts, caffeine or training. Empty bladder, no lotion,
    stand barefoot on clean electrodes.

Hydrostatic / underwater weighing ("dunk tank", "float tank")
  - Offered by university labs, sports-performance centers and mobile body-fat
    trucks that visit gyms; usually $40-$75.
  - Fasted 3-4 h, no training that day. You exhale fully while submerged, so
    practice a slow, complete exhale; the tester usually takes 3 readings.

For every method
  - Same method, same place, same time of day, same pre-test routine each month.
  - Test in a deload week if you can, not right after a hard session.
  - Record the date, your body-fat %, the method, and the weight the test measured.
"""


@dataclass(frozen=True)
class LogEntry:
    date: date
    exercise: str
    weight: float
    reps: int
    kind: str = "training"  # "baseline", "training" or "test"
    note: str = ""
    id: int | None = None

    @property
    def e1rm(self) -> float:
        return estimate_1rm(self.weight, self.reps)


@dataclass(frozen=True)
class BodyWeight:
    week: int
    date: date
    weight: float


@dataclass(frozen=True)
class BodyFat:
    month: int  # 1-12, month of the program year
    date: date
    percent: float
    method: str
    weight: float | None = None

    @property
    def lean_mass(self) -> float | None:
        return None if self.weight is None else round(self.weight * (1 - self.percent / 100), 1)


def estimate_1rm(weight: float, reps: int) -> float:
    """Epley estimate of a one-rep max from a set of `reps` at `weight`."""
    if weight < 0 or reps < 1:
        raise ValueError("weight must be >= 0 and reps >= 1")
    if reps == 1:
        return float(weight)
    return weight * (1 + reps / 30)


def _for(entries, exercise):
    return [e for e in entries if e.exercise == exercise and e.weight > 0 and e.reps > 0]


def rep_maxes(entries, exercise: str) -> dict[int, LogEntry]:
    """Heaviest set with at least N reps, for each N in REP_MAX_COUNTS."""
    mine = _for(entries, exercise)
    result = {}
    for n in REP_MAX_COUNTS:
        qualifying = [e for e in mine if e.reps >= n]
        if qualifying:
            result[n] = max(qualifying, key=lambda e: (e.weight, -e.date.toordinal()))
    return result


def best_e1rm(entries, exercise: str, before: date | None = None) -> LogEntry | None:
    """Best estimated-1RM set. With `before`, only baseline sets and sets dated earlier count."""
    mine = [e for e in _for(entries, exercise)
            if before is None or e.kind == "baseline" or e.date < before]
    return max(mine, key=lambda e: e.e1rm, default=None)


def training_max(entries, exercise: str, cycle_start: date | None = None) -> tuple[float | None, bool]:
    """Max a cycle's percentages are based on -> (value, is_estimate).

    Uses the best e1RM logged before the cycle starts (baseline sets always
    count). A variation with no data is estimated from its parent lift.
    """
    best = best_e1rm(entries, exercise, cycle_start)
    if best:
        return best.e1rm, False
    info = CATALOG.get(exercise)
    if info and info.parent:
        parent = best_e1rm(entries, info.parent, cycle_start)
        if parent:
            return parent.e1rm * info.ratio, True
    return None, False


def new_prs(entries, entry: LogEntry) -> list[str]:
    """PRs `entry` sets against all earlier logged sets of the same exercise."""
    previous = [e for e in _for(entries, entry.exercise)
                if e is not entry and (entry.id is None or e.id != entry.id)]
    prs = []
    best_before = max((e.e1rm for e in previous), default=0)
    if entry.e1rm > best_before:
        prs.append(f"Estimated 1RM {entry.e1rm:.0f}")
    for n in REP_MAX_COUNTS:
        if entry.reps >= n:
            prior = max((e.weight for e in previous if e.reps >= n), default=0)
            if entry.weight > prior:
                prs.append(f"{n}RM {entry.weight:g}")
    return prs


def e1rm_history(entries, exercise: str) -> list[tuple[date, float]]:
    """Running best estimated 1RM over time (one point per training date)."""
    points, best = [], 0.0
    for e in sorted(_for(entries, exercise), key=lambda e: e.date):
        best = max(best, e.e1rm)
        if points and points[-1][0] == e.date:
            points[-1] = (e.date, best)
        else:
            points.append((e.date, best))
    return points
