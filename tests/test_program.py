import pytest

from ruskimaxxing.prilepin import zone_for
from ruskimaxxing.program import (DELOAD_WEEKS, MAIN_LIFTS, WEEKS, build_program,
                                  estimate_1rm)


@pytest.fixture(scope="module")
def sessions():
    return build_program()


def test_three_sessions_every_week(sessions):
    assert len(sessions) == WEEKS * 3
    for week in range(1, WEEKS + 1):
        assert [s.day[:5] for s in sessions if s.week == week] == ["Day 1", "Day 2", "Day 3"]


def test_every_main_lift_trained_weekly(sessions):
    for week in range(1, WEEKS + 1):
        trained = {p.exercise for s in sessions if s.week == week for p in s.exercises if p.is_main}
        assert trained == set(MAIN_LIFTS)


def test_loading_weeks_stay_inside_prilepin(sessions):
    for s in sessions:
        if s.phase in {"Deload", "Test"}:
            continue
        for p in s.exercises:
            if p.is_main:
                zone = zone_for(p.percent)
                lo, hi = zone.total_range
                assert zone.reps_per_set[0] <= int(p.reps) <= zone.reps_per_set[1], p
                assert lo <= p.sets * int(p.reps) <= hi, p


def test_heavy_day_intensity_rises_each_block(sessions):
    heavy = [p.percent for s in sessions if s.day.endswith("Heavy") and s.phase not in {"Deload", "Test"}
             for p in s.exercises if p.exercise == "Squat"]
    assert heavy == sorted(heavy)
    assert heavy[0] == 70 and heavy[-1] == 90


def test_deload_weeks_are_light(sessions):
    for s in sessions:
        if s.week in DELOAD_WEEKS:
            assert all(p.sets <= 2 for p in s.exercises)


def test_test_week_has_amrap_for_each_lift(sessions):
    amrap = {p.exercise for s in sessions if s.week == 12 for p in s.exercises if p.reps == "AMRAP"}
    assert amrap == set(MAIN_LIFTS)


def test_weights_use_maxes_and_rounding(sessions):
    squat = sessions[0].exercises[0]
    assert squat.exercise == "Squat" and squat.percent == 70
    assert squat.weight({"Squat": 300}, 5) == 210
    assert squat.weight({}, 5) is None


@pytest.mark.parametrize("weight, reps, expected", [(200, 1, 200), (150, 5, 175), (90, 10, 120)])
def test_estimate_1rm(weight, reps, expected):
    assert estimate_1rm(weight, reps) == pytest.approx(expected)


def test_estimate_1rm_rejects_bad_input():
    with pytest.raises(ValueError):
        estimate_1rm(100, 0)
