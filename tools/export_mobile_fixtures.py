"""Golden data for the Expo phone app's TypeScript port of the training logic.

    python tools/export_mobile_fixtures.py          # rewrite mobile/src/core/__tests__/fixtures.json
    python tools/export_mobile_fixtures.py --check  # exit 1 if it's out of date (used by the Python tests)

The phone app (mobile/) re-implements src/ruskimaxxing's program, workout and PR logic in TypeScript.
This script runs the Python originals on the whole program and on worked examples and writes what they
produce; mobile's jest tests run the TypeScript versions on the same inputs and must match exactly, so
the two can never drift apart. Re-run it whenever the Python logic changes.
"""

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ruskimaxxing import workout as wo  # noqa: E402
from ruskimaxxing.exercises import CATALOG, JUMP_STANDARDS, MAIN, jump_level, jump_targets  # noqa: E402
from ruskimaxxing.program import (MONTHS, WEEKS, bodyfat_week, build_program, cycle_start, month_label,  # noqa: E402
                                  month_of, month_weeks, week_label)
from ruskimaxxing.storage import Store  # noqa: E402
from ruskimaxxing.tracking import (LogEntry, best_e1rm, e1rm_history, new_prs, rep_maxes,  # noqa: E402
                                   training_max)

OUT = ROOT / "mobile" / "src" / "core" / "__tests__" / "fixtures.json"
START = date(2026, 1, 5)  # a Monday


def program():
    return [{"week": s.week, "cycle": s.cycle, "phase": s.phase, "dayIndex": s.day_index, "day": s.day,
             "date": s.date(START).isoformat(),
             "exercises": [{"exercise": p.exercise, "sets": p.sets, "reps": p.reps, "percent": p.percent,
                            "note": p.note, "kind": p.kind} for p in s.exercises]}
            for s in build_program()]


def labels():
    return {"week": [week_label(w) for w in range(WEEKS + 1)],
            "month": [month_label(m) for m in range(MONTHS + 1)],
            "monthOf": [month_of(w) for w in range(WEEKS + 1)],
            "monthWeeks": [month_weeks(m) for m in range(MONTHS + 1)],
            "bodyfatWeek": [bodyfat_week(m) for m in range(1, MONTHS + 1)],
            "cycleStart": [cycle_start(START, c).isoformat() for c in range(6)]}


def entry_json(e: LogEntry) -> dict:
    return {"date": e.date.isoformat(), "exercise": e.exercise, "weight": e.weight, "reps": e.reps, "kind": e.kind,
            "note": e.note, "week": e.week, "day": e.day, "setNo": e.set_no, "rpe": e.rpe, "done": e.done}


def history(unit: str) -> list[LogEntry]:
    """Starting maxes plus a few weeks of logged training, in `unit`."""
    k = 1 if unit == "lb" else 0.4536
    before = START - timedelta(weeks=1)
    out = [
        LogEntry(before, "Squat", round(225 * k, 1), 5, "baseline", "starting max"),
        LogEntry(before, "Bench Press", round(185 * k, 1), 5, "baseline"),
        LogEntry(before, "Deadlift", round(275 * k, 1), 3, "baseline"),
        LogEntry(before, "Overhead Press", round(117.5 * k, 1), 5, "baseline"),
        LogEntry(before, "Box Jump", 20 if unit == "lb" else 51, 1, "baseline"),
        LogEntry(before, "Broad Jump", 84 if unit == "lb" else 213, 1, "baseline"),
    ]
    # cycle 1 training; a heavier squat in week 12 (test week) and one in week 14 (cycle 2)
    plan = [(1, 0, "Squat", 185, 6), (1, 0, "Bench Press", 155, 6), (2, 1, "Deadlift", 235, 5),
            (3, 2, "Box Squat", 205, 5), (3, 2, "Close-Grip Bench Press", 165, 5), (5, 0, "Squat", 205, 5),
            (6, 1, "Overhead Press", 105, 5), (9, 0, "Squat", 230, 3), (12, 0, "Squat", 255, 1),
            (12, 0, "Box Jump", 24, 1), (14, 0, "Squat", 215, 5), (2, 0, "Barbell Row", 135, 10),
            (7, 0, "Barbell Row", 145, 8), (12, 1, "Broad Jump", 90, 1)]
    for week, day, ex, weight, reps in plan:
        w = weight if CATALOG[ex].category == "plyo" else round(weight * k, 1)
        if CATALOG[ex].category == "plyo" and unit == "kg":
            w = round(weight * 2.54, 1)
        out.append(LogEntry(wo.session(week, day).date(START), ex, w, reps, "training", "", week=week, day=day,
                            set_no=1, rpe=8.0 if reps > 3 else None))
    # a set that wasn't done never counts
    out.append(LogEntry(wo.session(9, 0).date(START), "Bench Press", round(400 * k, 1), 1, "training", "",
                        week=9, day=0, set_no=1, done=False))
    return out


def scenario(unit: str, increment: float, height: float | None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "data.db")
        try:
            return _scenario(store, unit, increment, height)
        finally:
            store.close()  # Windows can't delete the temp folder while the database is open


def _scenario(store: Store, unit: str, increment: float, height: float | None) -> dict:
    store.set("units", unit)
    store.set("increment", f"{increment:g}")
    store.set("start", START.isoformat())
    if height:
        store.set("height", f"{height:g}")
    entries = history(unit)
    for e in entries:
        store.add_lift(e)
    cfg = wo.Settings.from_store(store)
    lifts = store.lifts()

    workouts = []
    for week, day in [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (3, 2), (4, 0), (9, 0), (11, 0),
                      (11, 1), (12, 0), (12, 1), (12, 2), (13, 0), (13, 2), (14, 0), (49, 0), (52, 1)]:
        blocks = wo.workout_model(store, week, day, cfg)
        workouts.append({"week": week, "day": day, "blocks": [
            {"exercise": b["p"].exercise, "source": b["source"], "planned": b["planned"], "note": b["note"],
             "rows": b["rows"]} for b in blocks]})

    tms = []
    for ex in list(MAIN) + ["Box Squat", "Pause Squat", "Close-Grip Bench Press", "Romanian Deadlift",
                            "Push Press", "Barbell Row"]:
        for cyc in range(0, 6):
            tm, est = training_max(lifts, ex, cycle_start(START, cyc))
            tms.append({"exercise": ex, "cycle": cyc, "tm": tm, "estimated": est})

    prs = {}
    for ex in list(MAIN) + ["Box Squat", "Barbell Row", "Box Jump"]:
        rms = rep_maxes(lifts, ex)
        best = best_e1rm(lifts, ex)
        prs[ex] = {"repMaxes": {str(n): entry_json(e) for n, e in rms.items()},
                   "bestE1rm": best.e1rm if best else None,
                   "history": [[d.isoformat(), v] for d, v in e1rm_history(lifts, ex)]}

    jumps = []
    for jump in JUMP_STANDARDS:
        for best in (None, 10, 20, 30, 51, 60, 84, 100, 213, 250):
            hu = cfg.height_unit
            jumps.append({"exercise": jump, "best": best, "height": height, "unit": hu,
                          "targets": [list(t) for t in jump_targets(jump, height, hu)],
                          "level": jump_level(jump, best, height, hu)})

    # save a session with edits: two done squat sets (one a PR), a done set with no reps, an extra set
    blocks = wo.workout_model(store, 13, 0, cfg)
    edits = [{"block": 1, "row": 0, "weight": f"{round(265 * (1 if unit == 'lb' else 0.4536), 1):g}",
              "reps": "3", "rpe": "9", "done": True},
             {"block": 1, "row": 1, "done": True},
             {"block": 2, "row": 0, "reps": "", "done": True},
             {"block": 0, "row": 0, "done": True}]
    for ed in edits:
        row = blocks[ed["block"]]["rows"][ed["row"]]
        for key in ("weight", "reps", "rpe", "done"):
            if key in ed:
                row[key] = ed[key]
    wo.add_set(blocks, 1)
    blocks[1]["note"] = "felt fast"
    saved, workout_prs, bad = wo.save_workout(store, 13, 0, blocks, cfg)
    after = wo.workout_model(store, 13, 0, cfg)

    new_pr_cases = []
    lifts = store.lifts()
    for e in [x for x in lifts if x.week == 13 and x.day == 0 and x.done]:
        new_pr_cases.append({"entry": entry_json(e), "prs": new_prs(lifts, e)})

    return {"unit": unit, "increment": increment, "height": height,
            "entries": [entry_json(e) for e in entries],
            "workouts": workouts, "trainingMaxes": tms, "prs": prs, "jumps": jumps,
            "save": {"week": 13, "day": 0, "edits": edits, "extraSetBlock": 1, "note": "felt fast",
                     "saved": [entry_json(e) for e in saved], "workoutPrs": workout_prs, "bad": bad,
                     "after": [{"exercise": b["p"].exercise, "source": b["source"], "note": b["note"],
                                "rows": b["rows"]} for b in after],
                     "progress": [list(wo.day_progress(store, 13, d)) for d in range(3)],
                     "newPrs": new_pr_cases}}


def build() -> dict:
    return {"start": START.isoformat(), "program": program(), "labels": labels(),
            "catalog": [{"name": e.name, "category": e.category, "parent": e.parent, "ratio": e.ratio}
                        for e in CATALOG.values()],
            "scenarios": [scenario("lb", 5.0, 70.0), scenario("kg", 2.5, 178.0), scenario("lb", 2.5, None)]}


def main(argv: list[str]) -> int:
    text = json.dumps(build(), indent=1, sort_keys=True) + "\n"
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is out of date: run python tools/export_mobile_fixtures.py")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
