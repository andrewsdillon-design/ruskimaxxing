import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
os.environ["RUSKIMAXXING_CLOUD_AUTOSTART"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402

from ruskimaxxing_cloud.main import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path}/cloud.db"))


def test_catalog_lists_both_year1_programs(client):
    r = client.get("/v1/programs")
    assert r.status_code == 200
    slugs = {p["slug"] for p in r.json()["programs"]}
    assert {"ruskimaxxing-year1", "ruskimaxxing-supertotal-year1"} <= slugs
    assert "sessions" not in r.json()["programs"][0]  # the list stays small


def test_program_detail(client):
    prog = client.get("/v1/programs/ruskimaxxing-year1").json()
    assert prog["days_per_week"] == 3 and prog["weeks"] == 52
    assert len(prog["sessions"]) == 53 * 3  # baseline week 0 + 52 weeks
    first_loaded = next(e for s in prog["sessions"] if s["week"] == 1 for e in s["exercises"] if e["percent"])
    assert first_loaded["exercise"] == "Squat"
    st = client.get("/v1/programs/ruskimaxxing-supertotal-year1").json()
    assert "Snatch" in st["main_lifts"] and "Snatch" not in prog["main_lifts"]


def test_two_day_program(client):
    prog = client.get("/v1/programs/ruskimaxxing-2day-year1").json()
    assert prog["kind"] == "program" and prog["days_per_week"] == 2
    assert len(prog["sessions"]) == 53 * 2
    tests = {e["exercise"] for s in prog["sessions"] if s["week"] == 12 for e in s["exercises"] if e["kind"] == "test"
             and e["reps"] == "Max"}
    assert tests == {"Squat", "Bench Press", "Deadlift", "Overhead Press"}


def test_four_day_conjugate(client):
    prog = client.get("/v1/programs/ruskimaxxing-4day-conjugate-year1").json()
    assert prog["days_per_week"] == 4 and len(prog["sessions"]) == 53 * 4
    week1 = {s["day_index"]: s for s in prog["sessions"] if s["week"] == 1}
    me = [e for e in week1[0]["exercises"] if e["kind"] == "variation"][0]
    assert me["reps"] == "1-3RM" and me["percent"] is None
    speed_bench = [e for e in week1[3]["exercises"] if e["exercise"] == "Bench Press"][0]
    assert (speed_bench["sets"], speed_bench["reps"], speed_bench["percent"]) == (9, "3", 55.0)
    # max-effort variations rotate every 3-week block
    me5 = [e for s in prog["sessions"] if s["week"] == 5 and s["day_index"] == 1 for e in s["exercises"]
           if e["kind"] == "variation"][0]
    assert me5["exercise"] != [e for e in week1[1]["exercises"] if e["kind"] == "variation"][0]["exercise"]
    names = {e["exercise"] for s in prog["sessions"] for e in s["exercises"]}
    assert names <= set(prog["exercises"])


def test_strongman_addon(client):
    prog = client.get("/v1/programs/strongman-conditioning").json()
    assert prog["kind"] == "addon" and prog["main_lifts"] == []
    weeks = {s["week"] for s in prog["sessions"]}
    assert 11 not in weeks and 12 not in weeks  # off for taper and test weeks
    names = {e["exercise"] for s in prog["sessions"] for e in s["exercises"]}
    assert {"Sled Push", "Sled Drag", "Car Push", "Car Pull", "Atlas Stone to Lap", "Atlas Stone Load"} <= names
    assert all(e["percent"] is None for s in prog["sessions"] for e in s["exercises"])
    assert names <= set(prog["exercises"])


def test_unknown_program_404(client):
    assert client.get("/v1/programs/nope").status_code == 404


def test_exported_json_matches_generator(tmp_path):
    """The committed JSON must be regenerated whenever program.py changes."""
    script = ROOT / "server" / "deploy" / "export_programs.py"
    sys.path.insert(0, str(script.parent))
    import export_programs  # noqa: E402

    for slug, meta in export_programs.PROGRAMS.items():
        committed = json.loads((ROOT / "server" / "programs" / f"{slug}.json").read_text())
        assert committed == export_programs.export(slug, meta), (
            f"{slug}.json is stale - run: python server/deploy/export_programs.py")
