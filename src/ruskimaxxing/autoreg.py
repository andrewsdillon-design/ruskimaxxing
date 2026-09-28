"""Autoregulation: pure functions that adjust a planned Year-2/Year-3 session
to how the lifter is actually performing, on top of the plan advanced.py
builds. Nothing here reads or writes storage - callers pass in a Session (or
its Prescriptions) and get back an adjusted one.

RPE is RIR-based (Helms/Zourdos): RPE 10 = 0 reps in reserve, 9 = 1, 8 = 2...
so "two RPE off target" roughly means "two reps in the tank off target" and
maps to about a 2-2.5% change in load per RPE point - the standard rule of
thumb powerlifting coaches use when adjusting week to week.
"""

import dataclasses
from dataclasses import dataclass

from ruskimaxxing.program import Prescription, Session

PCT_PER_RPE = 0.025  # ~2.5% load change per RPE point away from target


@dataclass(frozen=True)
class Readiness:
    load_multiplier: float
    accessory_set_delta: int
    note: str


READINESS = {
    5: Readiness(1.025, 0, "Feeling great - a little extra today"),
    4: Readiness(1.0, 0, "As planned"),
    3: Readiness(0.95, 0, "A bit flat - lighten the load"),
    2: Readiness(0.90, -1, "Rough day - lighten up and cut an accessory set"),
    1: Readiness(1.0, 0, "Very rough - swap to a light technique day"),
}


def next_load(target_rpe: float, last_weight: float, last_reps: int, last_rpe: float,
             increment: float) -> float:
    """Adjust `last_weight` toward `target_rpe`, rounded to the lifter's plate increment.

    A completed set harder than target (higher RPE) means the load should
    come down next time; easier than target means it can go up.
    """
    if increment <= 0:
        raise ValueError("increment must be positive")
    off = last_rpe - target_rpe
    weight = last_weight * (1 - off * PCT_PER_RPE)
    return round(weight / increment) * increment


def readiness_adjust(session: Session, readiness: int) -> Session:
    """Scale a session's loaded sets by how ready the lifter says they feel (1-5).

    5 = a little heavier, 4 = as planned, 3 = a bit lighter, 2 = lighter and
    one fewer accessory set, 1 = swap every loaded main/variation set for a
    light technique set (a JuggernautAI-style readiness check-in).
    """
    if readiness not in READINESS:
        raise ValueError("readiness must be 1-5")
    rule = READINESS[readiness]
    exercises = []
    for p in session.exercises:
        if readiness == 1 and p.kind in ("main", "variation") and p.is_loaded:
            exercises.append(dataclasses.replace(
                p, percent=min(p.percent, 60.0), sets=max(2, p.sets - 1), reps="3",
                note="Readiness 1/5 - light technique day", rpe_target=(5.0, 6.0)))
            continue
        if p.kind == "accessory" and rule.accessory_set_delta:
            exercises.append(dataclasses.replace(p, sets=max(1, p.sets + rule.accessory_set_delta)))
            continue
        if p.is_loaded and rule.load_multiplier != 1.0:
            exercises.append(dataclasses.replace(p, percent=round(p.percent * rule.load_multiplier, 2)))
            continue
        exercises.append(p)
    return dataclasses.replace(session, exercises=tuple(exercises))


def deload_due(recent_sets: list[dict]) -> tuple[bool, str]:
    """Should this main lift deload now?

    `recent_sets` is chronologically ordered dicts with at least
    {"exercise", "load", "rpe", "target_reps", "actual_reps"} for one lift's
    comparable working sets (same or very similar load).

    Triggers (RP-style performance-based deload, on top of the plan's own
    scheduled deloads):
      * RPE drifted up by >= 1 at essentially the same load across the last
        two sessions (fatigue is building faster than the plan expects), or
      * two sessions in a row missed the target rep count.
    """
    if len(recent_sets) < 2:
        return False, "not enough data"
    a, b = recent_sets[-2], recent_sets[-1]
    if a.get("rpe") is not None and b.get("rpe") is not None:
        same_load = a.get("load") is None or b.get("load") is None or abs(a["load"] - b["load"]) < 1e-6
        if same_load and (b["rpe"] - a["rpe"]) >= 1:
            return True, (f"RPE drifted from {a['rpe']:g} to {b['rpe']:g} at the same load across "
                          "the last two sessions")
    missed = [s for s in recent_sets[-2:]
             if s.get("target_reps") is not None and s.get("actual_reps") is not None
             and s["actual_reps"] < s["target_reps"]]
    if len(missed) >= 2:
        return True, "missed the target rep count two sessions in a row"
    return False, "on track"


def reflow_week(week_sessions: list[Session], done_days: set[int], today_day: int) -> list[Session]:
    """Reflow a week where a Heavy day was missed.

    If Day 0 (Heavy) hasn't been done and a later day in the week hasn't
    happened yet either, move Heavy into that slot and drop the week's Light
    day (Day 1) rather than cramming both into the same day. Never produces
    two Heavy days in a row within the returned week. If Heavy was already
    done, or there's no free day left to move it to, the week is returned
    unchanged.
    """
    heavy = next((s for s in week_sessions if s.day_index == 0), None)
    light = next((s for s in week_sessions if s.day_index == 1), None)
    if heavy is None or 0 in done_days:
        return list(week_sessions)
    remaining_days = sorted(s.day_index for s in week_sessions
                            if s.day_index not in done_days and s.day_index > today_day)
    if not remaining_days:
        return list(week_sessions)
    move_to = remaining_days[0]
    out = []
    for s in week_sessions:
        if s.day_index == 0:
            continue  # dropped from its original slot
        if s.day_index == move_to:
            out.append(dataclasses.replace(heavy, day_index=move_to, day=heavy.day))
        elif light is not None and s.day_index == light.day_index:
            continue  # drop Light this week instead of cramming two sessions together
        else:
            out.append(s)
    return out
