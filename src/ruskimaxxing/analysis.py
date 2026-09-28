"""Turn a lifter's logged Year-1 training history into a profile that Years 2
and 3 can build a personalized program from.

Every function here is a pure function over a list of ruskimaxxing.tracking.LogEntry
(the same rows Store.lifts() returns) plus bodyweight history - no I/O, no UI.

Ratio norms used by `weak_points` are published rules of thumb, not lab
measurements, and are documented so a lifter can see exactly why a flag fired:

    squat / deadlift              0.80 - 0.90  (classic powerlifting ratio)
    bench press / squat           0.65 - 0.80
    overhead press / bench press  0.60 - 0.70
    snatch / clean & jerk         0.78 - 0.84  (supertotal only)
    clean & jerk / front squat    0.80 - 0.90  (supertotal only)

Sources: these are the ratios strength coaches commonly cite (e.g. Chad
Wesley Smith / Juggernaut Training Systems for the powerlifting ratios;
USAW coaching literature for the weightlifting ratios). They are heuristics
for flagging an obvious imbalance, not a diagnosis.
"""

from dataclasses import dataclass

from ruskimaxxing.edition import is_supertotal
from ruskimaxxing.exercises import CATALOG, MAIN, OLY
from ruskimaxxing.program import TEST_WEEKS, build_program
from ruskimaxxing.tracking import best_e1rm, training_max

RATIO_NORMS = (
    ("Squat", "Deadlift", 0.80, 0.90),
    ("Bench Press", "Squat", 0.65, 0.80),
    ("Overhead Press", "Bench Press", 0.60, 0.70),
)
SUPERTOTAL_RATIO_NORMS = (
    ("Snatch", "Clean & Jerk", 0.78, 0.84),
    ("Clean & Jerk", "Front Squat", 0.80, 0.90),
)
RATIO_SOURCE = ("Published powerlifting/weightlifting coaching rules of thumb: squat ~80-90% of "
                "deadlift, bench ~65-80% of squat, overhead press ~60-70% of bench; for supertotal, "
                "snatch ~78-84% of clean & jerk and clean & jerk ~80-90% of front squat.")

# How many of the most recent logged RPEs (per lift) feed the drift slope
RPE_DRIFT_WINDOW = 8
# Minimum points needed before we'll report a slope at all
RPE_DRIFT_MIN_POINTS = 3


@dataclass(frozen=True)
class Flag:
    """One weak-point, stalled-lift or other coaching flag, always with a reason."""
    lift: str
    reason: str
    severity: float = 0.0  # higher = more important; used to rank weak_points/stalled


@dataclass(frozen=True)
class LifterProfile:
    edition: str
    training_max: dict[str, float]          # main lifts (and tested Olympic lifts)
    variation_max: dict[str, float]          # any variation the lifter has actually logged
    gains: dict[str, float]                  # year-over-year e1RM gain, baseline -> final test
    ratios: dict[tuple[str, str], float]     # (numerator, denominator) -> actual ratio
    weak_points: list[Flag]                  # ranked worst-first
    stalled: list[Flag]
    rpe_drift: dict[str, float]               # lift -> RPE slope per logged session (+ = harder over time)
    adherence: float                          # share of planned Year-1 sessions with >=1 done set

    @property
    def weakest(self) -> str | None:
        return self.weak_points[0].lift if self.weak_points else None


def _done(entries):
    return [e for e in entries if e.done and e.weight > 0 and e.reps > 0]


def _main_lifts(edition: str) -> tuple[str, ...]:
    return MAIN + OLY if edition == "supertotal" or is_supertotal() else MAIN


def _training_maxes(lifts, edition):
    tms = {}
    for lift in _main_lifts(edition):
        tm, _ = training_max(lifts, lift)
        if tm:
            tms[lift] = tm
    variation_tms = {}
    logged_variations = {e.exercise for e in _done(lifts)
                          if CATALOG.get(e.exercise) and CATALOG[e.exercise].category == "variation"}
    for name in logged_variations:
        tm, _ = training_max(lifts, name)
        if tm:
            variation_tms[name] = tm
    return tms, variation_tms


def _gains(lifts, edition):
    gains = {}
    for lift in _main_lifts(edition):
        mine = _done([e for e in lifts if e.exercise == lift])
        if not mine:
            continue
        baseline_pool = [e for e in mine if e.kind == "baseline"] or [min(mine, key=lambda e: (e.week or 0, e.date))]
        baseline = max(e.e1rm for e in baseline_pool)
        final_entry = best_e1rm(lifts, lift)
        final = final_entry.e1rm if final_entry else baseline
        gains[lift] = final - baseline
    return gains


def _ratios_and_weak_points(training_maxes, edition):
    norms = RATIO_NORMS + (SUPERTOTAL_RATIO_NORMS if edition == "supertotal" or is_supertotal() else ())
    ratios, flags = {}, []
    for num, den, lo, hi in norms:
        if num not in training_maxes or den not in training_maxes or not training_maxes[den]:
            continue
        actual = training_maxes[num] / training_maxes[den]
        ratios[(num, den)] = actual
        if actual < lo:
            severity = lo - actual
            reason = (f"{num} is only {actual:.0%} of {den} (norm is {lo:.0%}-{hi:.0%} of {den}); "
                      f"{RATIO_SOURCE}")
            flags.append(Flag(num, reason, severity))
    flags.sort(key=lambda f: f.severity, reverse=True)
    return ratios, flags


def _stalled(lifts, edition):
    stalled = []
    for lift in _main_lifts(edition):
        by_week: dict[int, float] = {}
        for e in _done([x for x in lifts if x.exercise == lift and x.week in TEST_WEEKS]):
            by_week[e.week] = max(by_week.get(e.week, 0.0), e.e1rm)
        weeks = sorted(by_week)
        if len(weeks) < 2:
            continue
        prev, last = weeks[-2], weeks[-1]
        if by_week[last] <= by_week[prev]:
            stalled.append(Flag(
                lift,
                f"No e1RM PR from week {prev} ({by_week[prev]:.0f}) to week {last} ({by_week[last]:.0f})",
                by_week[prev] - by_week[last],
            ))
    stalled.sort(key=lambda f: f.severity, reverse=True)
    return stalled


def _slope(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def _rpe_drift(lifts, edition):
    drift = {}
    for lift in _main_lifts(edition):
        mine = [e for e in _done(lifts) if e.exercise == lift and e.rpe is not None]
        mine.sort(key=lambda e: (e.week or 0, e.day or 0, e.set_no or 0, e.date))
        recent = mine[-RPE_DRIFT_WINDOW:]
        if len(recent) < RPE_DRIFT_MIN_POINTS:
            continue
        drift[lift] = _slope(list(range(len(recent))), [e.rpe for e in recent])
    return drift


def _adherence(lifts):
    sessions = build_program()
    done = {(e.week, e.day) for e in lifts if e.done and e.week is not None and e.day is not None}
    if not sessions:
        return 0.0
    hit = sum(1 for s in sessions if (s.week, s.day_index) in done)
    return hit / len(sessions)


def profile(lifts, bodyweight, edition: str) -> LifterProfile:
    """Build a LifterProfile from a lifter's full logged history.

    `bodyweight` (a list of tracking.BodyWeight) is accepted for API symmetry
    with the rest of the app and future bodyweight-relative norms; it is not
    used by any calculation yet.
    """
    tms, variation_tms = _training_maxes(lifts, edition)
    gains = _gains(lifts, edition)
    ratios, weak_points = _ratios_and_weak_points(tms, edition)
    stalled = _stalled(lifts, edition)
    rpe_drift = _rpe_drift(lifts, edition)
    adherence = _adherence(lifts)
    return LifterProfile(edition, tms, variation_tms, gains, ratios, weak_points, stalled,
                         rpe_drift, adherence)
