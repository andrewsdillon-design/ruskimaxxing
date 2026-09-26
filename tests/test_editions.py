import os
import subprocess
import sys

SCRIPT = """
from ruskimaxxing.exercises import MAIN, CATALOG
from ruskimaxxing.program import build_program, TEST_WEEKS
s = build_program()
tested = {p.exercise for x in s if x.week == 12 for p in x.exercises if p.reps == "Max"}
oly = [p for x in s if x.phase == "Realization" for p in x.exercises if p.exercise in ("Snatch", "Clean & Jerk")]
print(MAIN)
print(sorted(tested))
print(max((int(p.reps) for p in oly), default=0))
print("Power Snatch" in CATALOG)
"""


def run(edition):
    env = {**os.environ, "RUSKIMAXXING_EDITION": edition}
    return subprocess.run([sys.executable, "-c", SCRIPT], env=env, capture_output=True, text=True, check=True).stdout


def test_supertotal_edition_adds_olympic_lifts():
    out = run("supertotal").splitlines()
    assert "Snatch" in out[0] and "Clean & Jerk" in out[0]
    assert "'Snatch'" in out[1] and "'Clean & Jerk'" in out[1]
    assert int(out[2]) <= 2          # Olympic lifts stay at low reps in heavy blocks
    assert out[3] == "True"


def test_standard_edition_has_no_olympic_lifts():
    out = run("standard").splitlines()
    assert "Snatch" not in out[0] and out[3] == "False"
