from datetime import date

import pytest

from ruskimaxxing.analysis import profile
from ruskimaxxing.program import TEST_WEEKS, build_program
from ruskimaxxing.tracking import LogEntry


def entry(exercise, weight, reps, week=None, day=None, set_no=1, kind="training", rpe=None,
          d=date(2026, 1, 5)):
    return LogEntry(d, exercise, weight, reps, kind, "", week=week, day=day, set_no=set_no, rpe=rpe)


def test_weak_point_flags_squat_behind_deadlift():
    lifts = [
        entry("Squat", 200, 1, kind="baseline"),
        entry("Deadlift", 400, 1, kind="baseline"),
        entry("Bench Press", 200, 1, kind="baseline"),
        entry("Overhead Press", 130, 1, kind="baseline"),
    ]
    p = profile(lifts, [], "standard")
    assert p.training_max["Squat"] == 200
    assert p.training_max["Deadlift"] == 400
    assert p.weakest == "Squat"
    assert "Squat" in p.weak_points[0].reason
    assert "80%" in p.weak_points[0].reason or "80" in p.weak_points[0].reason


def test_no_weak_point_when_ratios_are_in_range():
    lifts = [
        entry("Squat", 350, 1, kind="baseline"),
        entry("Deadlift", 400, 1, kind="baseline"),
        entry("Bench Press", 260, 1, kind="baseline"),
        entry("Overhead Press", 160, 1, kind="baseline"),
    ]
    p = profile(lifts, [], "standard")
    assert p.weak_points == []


def test_stalled_lift_detected_across_last_two_test_weeks():
    lifts = [
        entry("Deadlift", 400, 1, week=36, day=0, kind="test"),
        entry("Deadlift", 400, 1, week=48, day=0, kind="test"),
        entry("Squat", 300, 1, week=36, day=0, kind="test"),
        entry("Squat", 320, 1, week=48, day=0, kind="test"),
    ]
    p = profile(lifts, [], "standard")
    stalled_lifts = {f.lift for f in p.stalled}
    assert "Deadlift" in stalled_lifts
    assert "Squat" not in stalled_lifts


def test_rpe_drift_is_positive_when_rpe_creeps_up():
    lifts = [entry("Bench Press", 200, 5, week=w, day=0, set_no=1, rpe=rpe)
             for w, rpe in zip(range(1, 9), [6, 6.5, 7, 7, 7.5, 8, 8, 8.5])]
    p = profile(lifts, [], "standard")
    assert p.rpe_drift["Bench Press"] > 0


def test_adherence_counts_sessions_with_at_least_one_done_set():
    sessions = build_program()
    hit = {(s.week, s.day_index) for s in sessions[:10]}
    lifts = [entry("Squat", 200, 5, week=w, day=d) for w, d in hit]
    p = profile(lifts, [], "standard")
    assert p.adherence == pytest.approx(len(hit) / len(sessions))


def test_supertotal_ratios_include_olympic_norms():
    lifts = [
        entry("Snatch", 150, 1, kind="baseline"),
        entry("Clean & Jerk", 200, 1, kind="baseline"),
        entry("Front Squat", 240, 1, kind="baseline"),
    ]
    p = profile(lifts, [], "supertotal")
    assert ("Snatch", "Clean & Jerk") in p.ratios


def test_gains_measure_baseline_to_final_e1rm():
    lifts = [
        entry("Squat", 200, 1, kind="baseline", week=0),
        entry("Squat", 300, 1, week=48, day=0, kind="test"),
    ]
    p = profile(lifts, [], "standard")
    assert p.gains["Squat"] == pytest.approx(100)
