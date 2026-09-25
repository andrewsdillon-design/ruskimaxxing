"""Command-line interface.

    ruskimaxxing                       open the desktop app
    ruskimaxxing excel FILE.xlsx       write the standalone spreadsheet
    ruskimaxxing plan --squat 225 5 --bench 155 5 [--week 3]
    ruskimaxxing prilepin 200 85       one Prilepin prescription
"""

import argparse

from ruskimaxxing.prilepin import load, zone_for
from ruskimaxxing.program import MAIN_LIFTS, build_program, estimate_1rm

LIFT_FLAGS = {"squat": "Squat", "bench": "Bench Press", "deadlift": "Deadlift", "press": "Overhead Press"}


def _prilepin(args):
    zone = zone_for(args.percent)
    lo, hi = zone.reps_per_set
    tlo, thi = zone.total_range
    print(f"Weight:        {load(args.one_rep_max, args.percent, args.increment):g}")
    print(f"Reps per set:  {lo}-{hi}")
    print(f"Total reps:    {zone.optimal_total} optimal ({tlo}-{thi})")


def _plan(args):
    maxes = {LIFT_FLAGS[f]: estimate_1rm(w, int(r)) for f in LIFT_FLAGS
             if (v := getattr(args, f)) for w, r in [v]}
    for lift in MAIN_LIFTS:
        if lift in maxes:
            print(f"{lift:15} est. 1RM {maxes[lift]:.0f}")
    for s in build_program():
        if args.week and s.week != args.week:
            continue
        print(f"\nWeek {s.week} ({s.phase}) - {s.day}")
        for p in s.exercises:
            w = p.weight(maxes, args.increment)
            weight = f" @ {w:g}" if w else (f" @ {p.percent:g}%" if p.percent else "")
            sets = f"{p.sets} x {p.reps}" if p.sets else ""
            print(f"  {p.exercise:26} {sets:10}{weight}")


def _excel(args):
    from ruskimaxxing.excel import build_workbook
    print(f"Wrote {build_workbook(args.path)}")


def _gui(_args):
    from ruskimaxxing.gui import main as gui_main
    gui_main()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ruskimaxxing", description="12-week beginner strength & mass program.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="open the desktop app (default)").set_defaults(func=_gui)

    p = sub.add_parser("excel", help="write the standalone Excel spreadsheet")
    p.add_argument("path", nargs="?", default="RuskiMaxxing-Program.xlsx")
    p.set_defaults(func=_excel)

    p = sub.add_parser("plan", help="print the program with your weights")
    for flag in LIFT_FLAGS:
        p.add_argument(f"--{flag}", nargs=2, type=float, metavar=("WEIGHT", "REPS"))
    p.add_argument("--week", type=int, choices=range(1, 13), metavar="1-12")
    p.add_argument("--increment", type=float, default=5, help="plate rounding (default 5)")
    p.set_defaults(func=_plan)

    p = sub.add_parser("prilepin", help="sets/reps for one intensity")
    p.add_argument("one_rep_max", type=float)
    p.add_argument("percent", type=float, help="intensity as %% of 1RM")
    p.add_argument("--increment", type=float, default=2.5)
    p.set_defaults(func=_prilepin)

    args = parser.parse_args(argv)
    getattr(args, "func", _gui)(args)


if __name__ == "__main__":
    main()
