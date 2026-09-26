from collections import Counter

import pytest

from ruskimaxxing.exercises import CATALOG, MAIN, ROTATION
from ruskimaxxing.prilepin import zone_for
from ruskimaxxing.program import (CYCLE_WEEKS, TEST_WEEKS, WEEKS, bodyfat_week, build_program,
                                  cycle_of, week_label)


@pytest.fixture(scope="module")
def sessions():
    return build_program()


def phases(sessions):
    return {s.week: s.phase for s in sessions}


def test_full_year_three_days_a_week(sessions):
    weeks = Counter(s.week for s in sessions)
    assert sorted(weeks) == list(range(0, WEEKS + 1))
    assert set(weeks.values()) == {3}


def test_tests_every_12th_week_after_deloads_and_taper(sessions):
    p = phases(sessions)
    assert [w for w, ph in p.items() if ph == "Test"] == list(TEST_WEEKS) == [12, 24, 36, 48]
    for cycle in range(4):
        base = cycle * CYCLE_WEEKS
        assert p[base + 4] == p[base + 8] == "Deload"
        assert p[base + 11] == "Taper"  # never test straight off a heavy week
        assert p[base + 10] == "Realization"
    assert [p[w] for w in range(49, 53)] == ["Transition"] * 3 + ["Deload"]
    assert p[0] == "Baseline"


def test_loaded_sessions_stay_inside_prilepin(sessions):
    for s in sessions:
        if s.phase not in {"Accumulation", "Transmutation", "Realization"}:
            continue
        for p in s.exercises:
            if p.is_loaded:
                zone = zone_for(p.percent)
                lo, hi = zone.total_range
                assert zone.reps_per_set[0] <= int(p.reps) <= zone.reps_per_set[1], p
                assert lo <= p.sets * int(p.reps) <= hi, p


def test_every_main_lift_tested_each_test_week(sessions):
    for week in TEST_WEEKS:
        tested = {p.exercise for s in sessions if s.week == week for p in s.exercises if p.reps == "Max"}
        assert set(MAIN) <= tested


def test_variations_rotate_every_block_and_get_tested(sessions):
    day3 = {s.week: s for s in sessions if s.day_index == 2}
    squat_vars = [next(p.exercise for p in day3[w].exercises if CATALOG[p.exercise].parent == "Squat")
                  for w in (1, 5, 9, 13)]
    assert len(set(squat_vars)) == 4 and all(v in ROTATION["Squat"] for v in squat_vars)
    test_vars = [p for p in day3[12].exercises if p.kind == "test"]
    assert {p.exercise for p in test_vars} == {p.exercise for p in day3[10].exercises if p.kind == "variation"}


def test_every_session_starts_with_plyometrics(sessions):
    for s in sessions:
        assert CATALOG[s.exercises[0].exercise].category == "plyo"


def test_box_jump_is_tested_and_baselined(sessions):
    for week in (0, *TEST_WEEKS):
        assert any(p.exercise == "Box Jump" and p.reps == "Max" for s in sessions if s.week == week for p in s.exercises)


def test_labels_and_cycles():
    assert week_label(0).startswith("Week 0 - Baseline")
    assert week_label(13) == "Week 13 - Cycle 2 - Accumulation"
    assert week_label(52) == "Week 52 - Transition - Deload"
    assert [cycle_of(w) for w in (0, 1, 12, 13, 48, 49, 52)] == [0, 1, 1, 2, 4, 5, 5]


def test_bodyfat_monthly():
    weeks = [bodyfat_week(m) for m in range(1, 13)]
    assert weeks[0] == 1 and weeks == sorted(weeks) and weeks[-1] <= 52
    assert all(3 <= b - a <= 5 for a, b in zip(weeks, weeks[1:]))


def test_month_labels():
    from ruskimaxxing.program import month_label
    assert month_label(0).startswith("Baseline")
    assert month_label(1) == "Month 1 - Weeks 1-4 - Cycle 1"
    assert month_label(4) == "Month 4 - Weeks 13-16 - Cycle 2"
    assert month_label(13) == "Month 13 - Weeks 49-52 - Transition"
