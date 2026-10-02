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
    "ruskimaxxing-2day-year1": {
        "edition": "standard",
        "builder": "program_designs.two_day",
        "name": "RuskiMaxxing 2-Day Year 1",
        "description": ("The Year 1 program in two days a week for men with less time: same cycles, deloads and "
                        "test weeks, with a rotating variation standing in for the third day."),
    },
    "ruskimaxxing-4day-conjugate-year1": {
        "edition": "standard",
        "builder": "program_designs.four_day_conjugate",
        "name": "RuskiMaxxing 4-Day Conjugate Year 1",
        "description": ("Westside-style upper/lower: max-effort and dynamic-effort days for the lower and upper body, "
                        "four days a week, on the same 12-week test calendar as Year 1."),
    },
    "powerbuilding-2day": {
        "edition": "standard",
        "builder": "program_designs.powerbuilding_two_day",
        "level": "All levels",
        "name": "Powerbuilding 2-Day",
        "description": ("Strength and size for men and women, two full-body days a week: a heavy top set and "
                        "back-off sets on squat, bench, deadlift and press, then volume work for muscle. "
                        "Same 12-week test calendar as the club."),
    },
    "powerbuilding-4day": {
        "edition": "standard",
        "builder": "program_designs.powerbuilding_four_day",
        "level": "All levels",
        "name": "Powerbuilding 4-Day",
        "description": ("Strength and size for men and women, upper/lower four days a week: each main lift "
                        "heavy once a week with top and back-off sets, plus variation and accessory volume. "
                        "Same 12-week test calendar as the club."),
    },
    "531-leader-anchor": {
        "edition": "standard",
        "builder": "program_designs.five_three_one",
        "level": "Intermediate",
        "name": "5/3/1 Leader/Anchor",
        "description": ("Jim Wendler's 5/3/1 for men and women, four days a week: two leader cycles of 5's PRO "
                        "and Boring But Big, then an anchor with all-out + sets, on the club's 12-week test "
                        "calendar. Slow, steady progress that lasts for years."),
    },
    "strongman-conditioning": {
        "edition": "standard",
        "builder": "program_designs.strongman",
        "level": "All levels",
        "name": "Strongman Conditioning",
        "description": ("An add-on for any program: two finishers a week of sled pushes and drags, car pushes and "
                        "pulls, farmer's carries and atlas stones. Skipped in taper and test weeks."),
    },
}

# Runs inside a child interpreter so each edition imports program.py fresh with its own RUSKIMAXXING_EDITION.
_CHILD = r"""
import importlib, json, os, sys
from ruskimaxxing import program
from ruskimaxxing.exercises import CATALOG, MAIN
builder = os.environ.get("RM_BUILDER")
mod = importlib.import_module(builder) if builder else None
built = mod.build() if mod else program.build_program()
kind = getattr(mod, "KIND", "program")
sessions = [
    {"week": s.week, "cycle": s.cycle, "phase": s.phase, "day_index": s.day_index, "day": s.day,
     "exercises": [{"exercise": p.exercise, "sets": p.sets, "reps": p.reps, "percent": p.percent,
                    "note": p.note, "kind": p.kind} for p in s.exercises]}
    for s in built
]
exercises = {e.name: {"category": e.category, "parent": e.parent, "ratio": e.ratio} for e in CATALOG.values()}
exercises.update(getattr(mod, "EXTRA_EXERCISES", {}))
json.dump({"kind": kind, "main_lifts": [] if kind == "addon" else list(MAIN), "exercises": exercises,
           "sessions": sessions, "weeks": program.WEEKS,
           "days_per_week": getattr(mod, "DAYS_PER_WEEK", len(program.DAYS))}, sys.stdout)
"""


def export(slug: str, meta: dict) -> dict:
    env = {**os.environ, "RUSKIMAXXING_EDITION": meta["edition"], "RM_BUILDER": meta.get("builder", ""),
           "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "server")])}
    raw = subprocess.run([sys.executable, "-c", _CHILD], env=env, check=True, capture_output=True, text=True).stdout
    data = json.loads(raw)
    return {
        "slug": slug,
        "kind": data["kind"],  # "program", or "addon": finishers that ride on top of a program
        "name": meta["name"],
        "edition": meta["edition"],
        "level": meta.get("level", "Beginner"),
        "year": 1,
        "days_per_week": data["days_per_week"],
        "weeks": data["weeks"],
        "baseline_week": True,  # week 0 is an optional baseline test (an intro week for add-ons)
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
