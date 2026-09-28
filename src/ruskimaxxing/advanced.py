"""Year 2 and Year 3 training engines: personalized, still three full-body
days a week with plyometrics every session, but built from the lifter's own
Year-1 (or Year-2) history via analysis.LifterProfile instead of a fixed
beginner template.

Year 2 - Heavy/Light/Medium daily undulating periodization (DUP)
    Intermediate lifters progress well on weekly undulation rather than long
    accumulation blocks (Zourdos et al. 2016, JSCR - HLM squat protocol beat a
    linear progression for 1RM gains). Each of the three weekly sessions keeps
    a fixed heavy/light/medium role (same day/lift layout as Year 1's DAYS),
    the %TM for each role rises across three-week "waves" the way Year 1's
    blocks do, and every loaded set carries an RPE target (Helms/Zourdos
    RIR-based RPE: 10 = 0 reps in reserve, 9 = 1, 8 = 2 ...) so the lifter can
    autoregulate around the plan (see autoreg.py). Reps per set and total reps
    stay inside Prilepin's chart for the working %.

Year 3 - Block periodization (Verkhoshansky)
    A lifter with two years of data is ready for the classic block sequence:
    a 4-week accumulation (higher volume, 65-75%), a 4-week transmutation
    (75-85%) and a 3-week realization (85-95%), each cycle still ending in a
    test week - the same 12-week cycle shape as Year 1, just run at higher
    intensity because the training max now comes from two years of tested
    maxes instead of a first guess.

Both years keep Year 1's individualization hooks and add two of their own:
    * the lifter's single worst-ranked weak point (analysis.LifterProfile.weakest)
      gets one extra working set on its main lift and an extra conjugate
      variation slot on the week's Day 3, so it accumulates more volume
      without crowding out the rest of the week;
    * any main lift analysis flags as stalled rotates, every 3-week block, to
      a new variation drawn from exercises.ROTATION for that lift (the same
      conjugate mechanism Year 1 already uses on Day 3) instead of grinding
      the same barbell lift that stopped producing PRs.

`build_year` is deterministic: the same profile, start date and edition
always produce the same list of Sessions.
"""

from dataclasses import dataclass
from datetime import date

from ruskimaxxing.analysis import LifterProfile
from ruskimaxxing.edition import is_supertotal
from ruskimaxxing.exercises import ROTATION
from ruskimaxxing.prilepin import zone_for
from ruskimaxxing.program import (CYCLE_WEEKS, CYCLES, DAYS, SLOTS, TESTED, TEST_PLYO,
                                  ACCESSORY_NOTE, TEST_NOTE, Block, Prescription, Session,
                                  _accessories, _plyo, _plyos, is_olympic)

WEEKS = 52
TEST_WEEK = CYCLE_WEEKS  # 12

# ----------------------------------------------------------------------------------
# Year 2: heavy/light/medium daily undulation, three-week waves within each cycle
# ----------------------------------------------------------------------------------

HLM_RPE = {"heavy": (8.0, 9.0), "medium": (7.0, 8.0), "light": (6.0, 7.0)}

YEAR2_WAVES = (
    Block("Wave 1", (1, 2, 3),
          {"heavy": (72.5, 75, 77.5), "medium": (65, 67.5, 70), "light": (57.5, 60, 62.5)}, "mid", 3, (4, 4)),
    Block("Wave 2", (5, 6, 7),
          {"heavy": (77.5, 80, 82.5), "medium": (70, 72.5, 75), "light": (60, 62.5, 65)}, "mid", 3, (4, 4)),
    Block("Wave 3", (9, 10),
          {"heavy": (82.5, 87.5), "medium": (72.5, 77.5), "light": (62.5, 67.5)}, "mid", 3, (3, 3)),
)
YEAR2_DELOAD = {4: 60.0, 8: 65.0}
YEAR2_TAPER_WEEK = 11

# ----------------------------------------------------------------------------------
# Year 3: classic Verkhoshansky block periodization, one 12-week cycle
# ----------------------------------------------------------------------------------

YEAR3_BLOCKS = (
    Block("Accumulation", (1, 2, 3, 4),
          {"heavy": (65, 68, 71, 75), "medium": (60, 63, 66, 70), "light": (55, 58, 61, 65)}, "high", 4, (4, 4)),
    Block("Transmutation", (5, 6, 7, 8),
          {"heavy": (75, 78, 81, 85), "medium": (70, 73, 76, 80), "light": (65, 68, 71, 75)}, "high", 3, (4, 4)),
    Block("Realization", (9, 10, 11),
          {"heavy": (85, 90, 95), "medium": (78, 83, 88), "light": (70, 75, 80)}, "mid", 3, (3, 2)),
)
YEAR3_RPE_BY_BLOCK = {"Accumulation": (6.0, 7.0), "Transmutation": (8.0, 9.0), "Realization": (9.0, 10.0)}
YEAR3_DELOAD: dict[int, float] = {}  # block periodization relies on the block sequence, not weekly deloads
YEAR3_TAPER_WEEK = None

TRANSITION_PCT = (60.0, 62.5, 65.0)
TRANSITION_DELOAD_PCT = 55.0

_YEAR_CONFIG = {
    2: {"blocks": YEAR2_WAVES, "deload": YEAR2_DELOAD, "taper_week": YEAR2_TAPER_WEEK, "rpe": "intensity"},
    3: {"blocks": YEAR3_BLOCKS, "deload": YEAR3_DELOAD, "taper_week": YEAR3_TAPER_WEEK, "rpe": "block"},
}


def _sets_reps(percent: float, bias: str, lift: str, day: str) -> tuple[int, int]:
    """Sets/reps for a working percentage, capped by Prilepin's chart (same rule as Year 1)."""
    import math
    zone = zone_for(percent)
    lo, hi = zone.reps_per_set
    if is_olympic(lift):
        return max(3, math.ceil(zone.total_range[0] / lo)), lo
    reps = hi if bias == "high" else (lo + hi + 1) // 2
    pulls = "Deadlift" in lift or "Pull" in lift
    total = zone.total_range[0] if day == "light" or pulls else zone.optimal_total
    return max(3, math.ceil(total / reps)), reps


def _resolve(slot: str, block_idx: int) -> tuple[str, str]:
    """Same idea as program._resolve, but keyed straight off the block index (0-2)."""
    if slot in SLOTS:
        lift = SLOTS[slot]
        options = ROTATION[lift]
        return options[block_idx % len(options)], "variation"
    return slot, "main"


def _base_lift(slot: str) -> str:
    return SLOTS.get(slot, slot)


def _overlay(exercise: str, kind: str, base_lift: str, profile: LifterProfile, block_idx: int):
    """Apply weak-point priority and stalled-lift rotation to a resolved (exercise, kind)."""
    reason = ""
    stalled_lifts = {f.lift for f in profile.stalled}
    if kind == "main" and exercise in stalled_lifts and exercise in ROTATION:
        options = ROTATION[exercise]
        rotated = options[block_idx % len(options)]
        reason = f"{exercise} stalled in testing - rotating to {rotated} this block"
        exercise, kind = rotated, "variation"
    extra_sets = 0
    if profile.weakest and base_lift == profile.weakest:
        extra_sets = 1
        weak_reason = f"{base_lift} flagged as a weak point - extra working set"
        reason = f"{reason}; {weak_reason}" if reason else weak_reason
    return exercise, kind, extra_sets, reason


def _weak_point_extra_slot(profile: LifterProfile, block_idx: int) -> Prescription | None:
    """An extra conjugate variation slot for Day 3, dedicated to the lifter's weakest lift."""
    lift = profile.weakest
    if not lift or lift not in ROTATION:
        return None
    options = ROTATION[lift]
    variation_name = options[(block_idx + 1) % len(options)]  # offset from Day 3's own rotation
    return Prescription(variation_name, 3, "6", 62.5,
                        note=f"Extra volume for {lift} (flagged as a weak point)",
                        kind="variation", reason=f"{lift} flagged as a weak point - extra variation slot")


def _rpe_for(mode: str, phase: str, intensity: str) -> tuple[float, float] | None:
    if mode == "intensity":
        return HLM_RPE.get(intensity)
    return YEAR3_RPE_BY_BLOCK.get(phase)


def _plyo_sets_reps(base: tuple[int, int], bump: int) -> tuple[int, int]:
    sets, reps = base
    return sets + bump, reps


def _session(week: int, year: int, profile: LifterProfile) -> list[Session]:
    cfg = _YEAR_CONFIG[year]
    blocks, deload, taper_week, rpe_mode = cfg["blocks"], cfg["deload"], cfg["taper_week"], cfg["rpe"]
    cycle = min(CYCLES + 1, (week - 1) // CYCLE_WEEKS + 1)
    sessions = []
    for i, (name, plyo, lifts, accessories) in enumerate(DAYS):
        if cycle == CYCLES + 1:
            week_in = week - CYCLES * CYCLE_WEEKS  # 1-4
            resolved = [(_base_lift(s), *_resolve(s, 0)) for s, _ in lifts]
            if week_in < 4:
                phase = "Transition"
                pct = TRANSITION_PCT[week_in - 1]
                exercises = _plyos(plyo, cycle, 0, 3, 3)
                exercises += [Prescription(ex, 3, "3" if is_olympic(ex) else "8", pct,
                                           "Easy volume - stay 3+ reps from failure", kind)
                             for _, ex, kind in resolved]
            else:
                phase = "Deload"
                exercises = _plyos(plyo, cycle, 0, 2, 3)
                exercises += [Prescription(ex, 2, "2" if is_olympic(ex) else "5", TRANSITION_DELOAD_PCT,
                                           "Full recovery week", kind) for _, ex, kind in resolved]
            exercises += _accessories(accessories, 3)
            sessions.append(Session(week, cycle, phase, i, name, tuple(exercises)))
            continue

        w = (week - 1) % CYCLE_WEEKS + 1
        block_idx = 0
        for bi, b in enumerate(blocks):
            if w in b.weeks:
                block_idx = bi
        block = next((b for b in blocks if w in b.weeks), None)

        if block:
            phase = block.name
            idx = block.weeks.index(w)
            exercises = _plyos(plyo, cycle, block_idx, *block.plyo)
            for slot, intensity in lifts:
                base_lift = _base_lift(slot)
                ex, kind = _resolve(slot, block_idx)
                ex, kind, extra, reason = _overlay(ex, kind, base_lift, profile, block_idx)
                pct = block.intensity[intensity][idx]
                sets, reps = _sets_reps(pct, block.rep_bias, ex, intensity)
                exercises.append(Prescription(ex, sets + extra, str(reps), pct, kind=kind,
                                              rpe_target=_rpe_for(rpe_mode, phase, intensity), reason=reason))
            if i == 2:  # Day 3: weak-point lift also gets a dedicated extra variation slot
                extra_slot = _weak_point_extra_slot(profile, block_idx)
                if extra_slot:
                    exercises.append(extra_slot)
            exercises += _accessories(accessories, block.accessory_sets)
        elif w in deload:
            phase = "Deload"
            exercises = _plyos(plyo, cycle, block_idx, 2, 3)
            resolved = [(_base_lift(s), *_resolve(s, block_idx)) for s, _ in lifts]
            exercises += [Prescription(ex, 2, "2" if is_olympic(ex) else "5", deload[w],
                                       "Easy week - move fast, recover", kind) for _, ex, kind in resolved]
            exercises += _accessories(accessories, 2, "Easy - stop well short of failure")
        elif taper_week is not None and w == taper_week:
            phase = "Taper"
            exercises = _plyos(plyo, cycle, block_idx, 2, 2)
            for slot, intensity in lifts:
                ex, kind = _resolve(slot, block_idx)
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
            exercises = [_plyo(TEST_PLYO[i], 1, "Max", "Test day: log it - it sets next cycle's weights")]
            for slot, intensity in lifts:
                ex, kind = _resolve(slot, block_idx)
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


def build_year(year: int, profile: LifterProfile, start: date, edition: str) -> list[Session]:
    """Every session of Year 2 or Year 3, week 1 through 52.

    `edition` selects standard vs supertotal via the same DAYS/TESTED tables
    Year 1 uses (ruskimaxxing.program), so both editions build without any
    extra branching here.
    """
    if year not in (2, 3):
        raise ValueError("year must be 2 or 3")
    return [s for week in range(1, WEEKS + 1) for s in _session(week, year, profile)]
