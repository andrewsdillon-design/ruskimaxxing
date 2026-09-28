import pytest

from ruskimaxxing.autoreg import deload_due, next_load, readiness_adjust, reflow_week
from ruskimaxxing.program import Prescription, Session


def make_session(week=1, day_index=0, day="Day 1 - Heavy", exercises=()):
    return Session(week, 1, "Wave 1", day_index, day, tuple(exercises))


def test_next_load_rounds_to_increment_and_reduces_when_rpe_over_target():
    w = next_load(target_rpe=8, last_weight=200, last_reps=5, last_rpe=9, increment=5)
    assert w < 200
    assert w % 5 == 0


def test_next_load_increases_when_rpe_under_target():
    w = next_load(target_rpe=8, last_weight=200, last_reps=5, last_rpe=7, increment=5)
    assert w > 200


def test_next_load_unchanged_at_target_rpe():
    w = next_load(target_rpe=8, last_weight=200, last_reps=5, last_rpe=8, increment=5)
    assert w == 200


def test_next_load_rejects_bad_increment():
    with pytest.raises(ValueError):
        next_load(8, 200, 5, 8, 0)


@pytest.mark.parametrize("level,expect_lighter", [(5, False), (4, False), (3, True), (2, True)])
def test_readiness_scales_load(level, expect_lighter):
    session = make_session(exercises=[Prescription("Squat", 4, "5", 80.0, kind="main")])
    out = readiness_adjust(session, level)
    pct = out.exercises[0].percent
    if expect_lighter:
        assert pct < 80.0
    elif level == 5:
        assert pct > 80.0
    else:
        assert pct == 80.0


def test_readiness_2_drops_an_accessory_set():
    session = make_session(exercises=[Prescription("Barbell Row", 3, "8-10", kind="accessory")])
    out = readiness_adjust(session, 2)
    assert out.exercises[0].sets == 2


def test_readiness_1_swaps_to_light_technique():
    session = make_session(exercises=[Prescription("Squat", 4, "5", 85.0, kind="main")])
    out = readiness_adjust(session, 1)
    p = out.exercises[0]
    assert p.percent <= 60.0
    assert p.rpe_target == (5.0, 6.0)


def test_readiness_rejects_out_of_range():
    with pytest.raises(ValueError):
        readiness_adjust(make_session(), 0)


def test_deload_due_on_rpe_drift_at_equal_load():
    sets = [
        {"exercise": "Squat", "load": 300, "rpe": 8, "target_reps": 5, "actual_reps": 5},
        {"exercise": "Squat", "load": 300, "rpe": 9.5, "target_reps": 5, "actual_reps": 5},
    ]
    due, reason = deload_due(sets)
    assert due and "RPE" in reason


def test_deload_due_on_two_missed_rep_sessions():
    sets = [
        {"exercise": "Squat", "load": 300, "rpe": 8, "target_reps": 5, "actual_reps": 3},
        {"exercise": "Squat", "load": 300, "rpe": 8, "target_reps": 5, "actual_reps": 4},
    ]
    due, reason = deload_due(sets)
    assert due and "missed" in reason


def test_deload_not_due_when_on_track():
    sets = [
        {"exercise": "Squat", "load": 300, "rpe": 8, "target_reps": 5, "actual_reps": 5},
        {"exercise": "Squat", "load": 305, "rpe": 8, "target_reps": 5, "actual_reps": 5},
    ]
    due, _ = deload_due(sets)
    assert not due


def _week(heavy_done=False):
    return [
        make_session(1, 0, "Day 1 - Heavy", [Prescription("Squat", 4, "5", 80.0)]),
        make_session(1, 1, "Day 2 - Light", [Prescription("Squat", 3, "8", 60.0)]),
        make_session(1, 2, "Day 3 - Variations", [Prescription("Box Squat", 3, "5", 70.0)]),
    ]


def test_reflow_moves_missed_heavy_day_and_drops_light():
    week = _week()
    out = reflow_week(week, done_days=set(), today_day=0)
    assert len(out) == 2  # Light dropped - Heavy took its slot, only 2 sessions left this week
    assert not any(any(p.percent == 60.0 for p in s.exercises) for s in out)  # Light's own work is gone
    heavy = next(s for s in out if any(p.percent == 80.0 for p in s.exercises))
    assert heavy.day_index != 0


def test_reflow_never_produces_two_heavy_days_back_to_back():
    week = _week()
    out = reflow_week(week, done_days=set(), today_day=0)
    heavy_days = [s.day_index for s in out if any(p.percent == 80.0 for p in s.exercises)]
    assert len(heavy_days) == 1


def test_reflow_unchanged_when_heavy_already_done():
    week = _week()
    out = reflow_week(week, done_days={0}, today_day=1)
    assert [s.day_index for s in out] == [0, 1, 2]
