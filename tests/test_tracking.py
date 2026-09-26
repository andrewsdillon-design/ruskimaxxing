from datetime import date

import pytest

from ruskimaxxing.exercises import box_jump_level, box_jump_targets
from ruskimaxxing.tracking import (BodyFat, LogEntry, best_e1rm, e1rm_history, estimate_1rm, new_prs,
                                   rep_maxes, training_max)

D = date(2026, 1, 1)


def e(ex, w, r, d=D, kind="training"):
    return LogEntry(d, ex, w, r, kind)


@pytest.mark.parametrize("weight, reps, expected", [(200, 1, 200), (150, 5, 175), (90, 10, 120)])
def test_estimate_1rm(weight, reps, expected):
    assert estimate_1rm(weight, reps) == pytest.approx(expected)


def test_rep_maxes_count_sets_with_more_reps():
    log = [e("2-Board Press", 200, 5), e("2-Board Press", 215, 2), e("1-Board Press", 205, 3)]
    rms = rep_maxes(log, "2-Board Press")
    assert rms[5].weight == 200 and rms[3].weight == 200 and rms[2].weight == 215 and rms[1].weight == 215
    assert 6 not in rms
    assert rep_maxes(log, "1-Board Press")[3].weight == 205  # variations tracked separately


def test_training_max_uses_sets_before_cycle_and_baseline():
    log = [e("Squat", 250, 5, date(2026, 1, 1), "baseline"), e("Squat", 300, 1, date(2026, 3, 20), "test")]
    assert training_max(log, "Squat", date(2026, 1, 5))[0] == pytest.approx(291.67, 0.01)
    assert training_max(log, "Squat", date(2026, 3, 30))[0] == 300


def test_variation_estimated_from_parent_until_logged():
    log = [e("Bench Press", 200, 1)]
    tm, estimated = training_max(log, "2-Board Press", date(2026, 2, 1))
    assert estimated and tm == pytest.approx(212)
    log.append(e("2-Board Press", 225, 1))
    assert training_max(log, "2-Board Press", date(2026, 2, 1)) == (225, False)


def test_new_prs():
    log = [e("Squat", 200, 5)]
    entry = e("Squat", 215, 3, date(2026, 1, 8))
    log.append(entry)
    prs = new_prs(log, entry)
    assert "1RM 215" in prs and "3RM 215" in prs and not any(p.startswith("5RM") for p in prs)
    assert prs[0].startswith("Estimated 1RM")


def test_e1rm_history_is_running_best():
    log = [e("Squat", 200, 1, date(2026, 1, 1)), e("Squat", 190, 1, date(2026, 1, 3)), e("Squat", 220, 1, date(2026, 1, 5))]
    assert [v for _, v in e1rm_history(log, "Squat")] == [200, 200, 220]
    assert best_e1rm(log, "Squat").weight == 220


def test_body_fat_lean_mass():
    assert BodyFat(1, D, 20, "Bod Pod", 200).lean_mass == 160


def test_box_jump_standards():
    targets = dict((level, h) for level, _, h in box_jump_targets(70))
    assert targets["Beginner"] == 7.5
    assert targets["Intermediate"] < targets["Proficient"] < targets["Elite"] < 70
    assert box_jump_level(24, 70) == "Intermediate"
    assert box_jump_level(66, 70) == "Elite"
    assert box_jump_level(None, 70) == "Not tested"
    assert dict((l, h) for l, _, h in box_jump_targets(178, "cm"))["Beginner"] == 19
