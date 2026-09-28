from collections import Counter
from datetime import date

import pytest

from ruskimaxxing.advanced import WEEKS, build_year
from ruskimaxxing.analysis import Flag, LifterProfile
from ruskimaxxing.exercises import CATALOG, ROTATION
from ruskimaxxing.prilepin import zone_for

START = date(2027, 1, 4)


def make_profile(weak_points=(), stalled=()):
    return LifterProfile(
        edition="standard",
        training_max={"Squat": 300, "Bench Press": 220, "Deadlift": 400, "Overhead Press": 140},
        variation_max={},
        gains={},
        ratios={},
        weak_points=list(weak_points),
        stalled=list(stalled),
        rpe_drift={},
        adherence=1.0,
    )


@pytest.fixture(scope="module")
def plain_sessions():
    return build_year(2, make_profile(), START, "standard")


def test_52_weeks_three_sessions_each(plain_sessions):
    weeks = Counter(s.week for s in plain_sessions)
    assert sorted(weeks) == list(range(1, WEEKS + 1))
    assert set(weeks.values()) == {3}


def test_deload_weeks_present(plain_sessions):
    phases = {s.week: s.phase for s in plain_sessions if s.day_index == 0}
    assert phases[4] == "Deload" and phases[8] == "Deload"


def test_rpe_targets_present_on_loaded_sets(plain_sessions):
    loaded = [p for s in plain_sessions if s.phase in {"Wave 1", "Wave 2", "Wave 3"}
              for p in s.exercises if p.is_loaded and p.kind in ("main", "variation")]
    assert loaded
    assert all(p.rpe_target is not None for p in loaded)


def test_prilepin_caps_respected(plain_sessions):
    for s in plain_sessions:
        if s.phase not in {"Wave 1", "Wave 2", "Wave 3"}:
            continue
        for p in s.exercises:
            if p.is_loaded and p.kind in ("main", "variation"):
                zone = zone_for(p.percent)
                lo, hi = zone.total_range
                assert zone.reps_per_set[0] <= int(p.reps) <= zone.reps_per_set[1]


def test_both_editions_build():
    import os
    import subprocess
    import sys

    script = """
from datetime import date
from ruskimaxxing.advanced import build_year
from ruskimaxxing.analysis import LifterProfile
p = LifterProfile("supertotal", {}, {}, {}, {}, [], [], {}, 1.0)
s2 = build_year(2, p, date(2027, 1, 4), "supertotal")
s3 = build_year(3, p, date(2027, 1, 4), "supertotal")
print(len(s2), len(s3))
"""
    env = {**os.environ, "RUSKIMAXXING_EDITION": "supertotal"}
    out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "156 156"


def test_weak_lift_gets_extra_working_set_and_variation_slot():
    weak = make_profile(weak_points=[Flag("Squat", "Squat ratio low", 0.1)])
    baseline = build_year(2, make_profile(), START, "standard")
    weak_sessions = build_year(2, weak, START, "standard")

    def squat_sets(sessions):
        return sum(p.sets for s in sessions if s.phase == "Wave 1" for p in s.exercises if p.exercise == "Squat")

    assert squat_sets(weak_sessions) > squat_sets(baseline)

    # Day 3 gets a dedicated extra variation slot referencing the weak lift
    day3 = [s for s in weak_sessions if s.day_index == 2 and s.phase == "Wave 1"][0]
    assert any("weak point" in p.reason for p in day3.exercises)


def test_stalled_lift_rotates_variation_every_block():
    stalled = make_profile(stalled=[Flag("Deadlift", "Deadlift stalled", 10.0)])
    sessions = build_year(2, stalled, START, "standard")
    day2 = {s.week: s for s in sessions if s.day_index == 1}  # Deadlift lives on Day 2
    variations = []
    for wk in (5, 9):  # first week of Wave 2 and Wave 3
        p = next(p for p in day2[wk].exercises if p.reason and "Deadlift" in p.reason)
        variations.append(p.exercise)
    assert len(set(variations)) == len(variations)
    assert all(v in ROTATION["Deadlift"] for v in variations)


def test_year3_blocks_progress_to_higher_intensity():
    sessions = build_year(3, make_profile(), START, "standard")
    phases_by_week = {s.week: s.phase for s in sessions if s.day_index == 0}
    assert phases_by_week[1] == "Accumulation"
    assert phases_by_week[5] == "Transmutation"
    assert phases_by_week[9] == "Realization"

    def max_pct(week):
        return max(p.percent for s in sessions if s.week == week for p in s.exercises if p.is_loaded)

    assert max_pct(1) < max_pct(5) < max_pct(9)


def test_year_must_be_2_or_3():
    with pytest.raises(ValueError):
        build_year(1, make_profile(), START, "standard")
