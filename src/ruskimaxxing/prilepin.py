"""Prilepin's chart: recommended reps per set and total reps by intensity zone."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Zone:
    low: float  # % of 1RM, inclusive
    high: float  # % of 1RM, exclusive (except the top zone)
    reps_per_set: tuple[int, int]
    optimal_total: int
    total_range: tuple[int, int]


ZONES = (
    Zone(0, 70, (3, 6), 24, (18, 30)),
    Zone(70, 80, (3, 6), 18, (12, 24)),
    Zone(80, 90, (2, 4), 15, (10, 20)),
    Zone(90, 100.01, (1, 2), 7, (4, 10)),
)


def zone_for(percent: float) -> Zone:
    """Return the Prilepin zone for an intensity given as % of 1RM."""
    if not 0 < percent <= 100:
        raise ValueError(f"percent must be in (0, 100], got {percent}")
    for zone in ZONES:
        if zone.low <= percent < zone.high:
            return zone
    raise AssertionError("unreachable")


def load(one_rep_max: float, percent: float, increment: float = 2.5) -> float:
    """Working weight for a percentage of 1RM, rounded to the nearest plate increment."""
    return round(one_rep_max * percent / 100 / increment) * increment
