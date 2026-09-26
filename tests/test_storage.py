from datetime import date

from ruskimaxxing.storage import Store
from ruskimaxxing.tracking import BodyFat, BodyWeight, LogEntry


def test_roundtrip(tmp_path):
    s = Store(tmp_path / "d.db")
    s.set("units", "kg")
    added = s.add_lift(LogEntry(date(2026, 1, 1), "Squat", 100, 5, "baseline"))
    assert s.get("units") == "kg" and s.lifts()[0] == added and added.id
    s.set_bodyweight(BodyWeight(1, date(2026, 1, 5), 80))
    s.set_bodyweight(BodyWeight(1, date(2026, 1, 5), 81))  # one value per week
    assert [b.weight for b in s.bodyweights()] == [81]
    s.set_bodyfat(BodyFat(1, date(2026, 1, 6), 18.5, "InBody", 81))
    s.set_bodyfat(BodyFat(1, date(2026, 1, 7), 18.0, "InBody", 81))  # one value per month
    assert [f.percent for f in s.bodyfats()] == [18.0]
    s.delete_lift(added.id)
    assert s.lifts() == []
