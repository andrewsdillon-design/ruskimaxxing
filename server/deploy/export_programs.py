"""Write the program catalog that /v1/programs serves.

Runs the app's own program generator (src/ruskimaxxing/program.py) once per edition and saves every
session of the year as JSON in server/programs/. Partner sites such as orthodoxbarbellclub.com read
those files through the API, so the program is defined in one place: this repo.

Run it after changing program.py or exercises.py, then commit the JSON:

    python server/deploy/export_programs.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "server" / "programs"

PROGRAMS = {
    "ruskimaxxing-year1": {
        "edition": "standard",
        "name": "RuskiMaxxing Year 1",
        "description": ("Beginner strength and mass year: three full-body days a week, plyometrics every session, "
                        "four 12-week cycles that end in a max test. Squat, bench press, deadlift and overhead press."),
    },
    "ruskimaxxing-supertotal-year1": {
        "edition": "supertotal",
        "name": "RuskiMaxxing Supertotal Year 1",
        "description": ("The Year 1 program with the snatch and clean & jerk added: the five-lift supertotal plus "
                        "the overhead press, three days a week."),
    },
}

# Runs inside a child interpreter so each edition imports program.py fresh with its own RUSKIMAXXING_EDITION.
_CHILD = r"""
import json, sys
from ruskimaxxing import program
from ruskimaxxing.exercises import CATALOG, MAIN
sessions = [
    {"week": s.week, "cycle": s.cycle, "phase": s.phase, "day_index": s.day_index, "day": s.day,
     "exercises": [{"exercise": p.exercise, "sets": p.sets, "reps": p.reps, "percent": p.percent,
                    "note": p.note, "kind": p.kind} for p in s.exercises]}
    for s in program.build_program()
]
exercises = {e.name: {"category": e.category, "parent": e.parent, "ratio": e.ratio} for e in CATALOG.values()}
json.dump({"main_lifts": list(MAIN), "exercises": exercises, "sessions": sessions,
           "weeks": program.WEEKS, "days_per_week": len(program.DAYS)}, sys.stdout)
"""


def export(slug: str, meta: dict) -> dict:
    env = {**os.environ, "RUSKIMAXXING_EDITION": meta["edition"], "PYTHONPATH": str(ROOT / "src")}
    raw = subprocess.run([sys.executable, "-c", _CHILD], env=env, check=True, capture_output=True, text=True).stdout
    data = json.loads(raw)
    return {
        "slug": slug,
        "name": meta["name"],
        "edition": meta["edition"],
        "level": "Beginner",
        "year": 1,
        "days_per_week": data["days_per_week"],
        "weeks": data["weeks"],
        "baseline_week": True,  # week 0 is an optional baseline test
        "description": meta["description"],
        "percent_of": "training max",  # every percent is of that exercise's own training max
        "rounding": "nearest plate increment: round(tm * percent / 100 / increment) * increment",
        "main_lifts": data["main_lifts"],
        "exercises": data["exercises"],
        "sessions": data["sessions"],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, meta in PROGRAMS.items():
        program = export(slug, meta)
        path = OUT / f"{slug}.json"
        path.write_text(json.dumps(program, indent=1) + "\n")
        print(f"wrote {path.relative_to(ROOT)} ({len(program['sessions'])} sessions)")


if __name__ == "__main__":
    main()
