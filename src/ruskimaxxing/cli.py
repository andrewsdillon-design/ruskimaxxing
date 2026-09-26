"""Command-line interface.

    ruskimaxxing                       open the desktop app
    ruskimaxxing excel FILE.xlsx       write the standalone spreadsheet
    ruskimaxxing plan --squat 225 5 --bench 155 5 [--week 3] [--start 2026-01-05]
    ruskimaxxing prilepin 200 85       one Prilepin prescription

Set RUSKIMAXXING_EDITION=supertotal to get the snatch / clean & jerk program.
"""

import argparse
from datetime import date

from ruskimaxxing.edition import app_name, is_supertotal
from ruskimaxxing.prilepin import load, zone_for
from ruskimaxxing.program import WEEKS, build_program, cycle_start, next_monday, week_label
from ruskimaxxing.tracking import LogEntry, training_max

LIFT_FLAGS = {"squat": "Squat", "bench": "Bench Press", "deadlift": "Deadlift", "press": "Overhead Press"}
if is_supertotal():
    LIFT_FLAGS |= {"snatch": "Snatch", "clean_jerk": "Clean & Jerk"}


def _prilepin(args):
    zone = zone_for(args.percent)
    lo, hi = zone.reps_per_set
    tlo, thi = zone.total_range
    print(f"Weight:        {load(args.one_rep_max, args.percent, args.increment):g}")
    print(f"Reps per set:  {lo}-{hi}")
    print(f"Total reps:    {zone.optimal_total} optimal ({tlo}-{thi})")


def _plan(args):
    start = date.fromisoformat(args.start) if args.start else next_monday()
    entries = [LogEntry(start, lift, w, int(r), "baseline")
               for flag, lift in LIFT_FLAGS.items() if (v := getattr(args, flag)) for w, r in [v]]
    for s in build_program():
        if args.week is not None and s.week != args.week:
            continue
        if s.day_index == 0:
            print(f"\n=== {week_label(s.week)} ===")
        print(f"\n{s.day} ({s.date(start):%a %b %d})")
        cs = cycle_start(start, s.cycle)
        for p in s.exercises:
            tm, estimated = training_max(entries, p.exercise, cs)
            w = p.weight(tm, args.increment)
            weight = f" @ {w:g}" + ("*" if estimated else "") if w else (f" @ {p.percent:g}%" if p.percent else "")
            sets = f"{p.sets} x {p.reps}" if p.sets else ""
            print(f"  {p.exercise:26} {sets:10}{weight}")
    print("\n* estimated from the main lift until you log that variation")


def _excel(args):
    from ruskimaxxing.excel import build_workbook
    print(f"Wrote {build_workbook(args.path)}")


def _gui(_args):
    from ruskimaxxing.gui import main as gui_main
    gui_main()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ruskimaxxing", description=f"{app_name()}: 1-year strength, mass & power program.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="open the desktop app (default)").set_defaults(func=_gui)

    p = sub.add_parser("excel", help="write the standalone Excel spreadsheet")
    p.add_argument("path", nargs="?", default=f"{app_name().replace(' ', '-')}.xlsx")
    p.set_defaults(func=_excel)

    p = sub.add_parser("plan", help="print the program with your weights")
    for flag in LIFT_FLAGS:
        p.add_argument(f"--{flag.replace('_', '-')}", dest=flag, nargs=2, type=float, metavar=("WEIGHT", "REPS"))
    p.add_argument("--week", type=int, choices=range(0, WEEKS + 1), metavar=f"0-{WEEKS}")
    p.add_argument("--start", help="Monday of week 1 (YYYY-MM-DD); default next Monday")
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
