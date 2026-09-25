"""Command-line entry point: prescribe a Prilepin-based session."""

import argparse

from ruskimaxxing.prilepin import load, zone_for


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Prilepin-based set/rep prescription.")
    parser.add_argument("one_rep_max", type=float, help="current 1RM")
    parser.add_argument("percent", type=float, help="intensity as %% of 1RM")
    parser.add_argument("--increment", type=float, default=2.5, help="plate rounding (default 2.5)")
    args = parser.parse_args(argv)

    zone = zone_for(args.percent)
    lo, hi = zone.reps_per_set
    tlo, thi = zone.total_range
    print(f"Weight:        {load(args.one_rep_max, args.percent, args.increment):g}")
    print(f"Reps per set:  {lo}-{hi}")
    print(f"Total reps:    {zone.optimal_total} optimal ({tlo}-{thi})")


if __name__ == "__main__":
    main()
