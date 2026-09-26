"""Phone app logic, run on Toga's dummy backend (no phone or display needed)."""


import pytest

pytest.importorskip("toga_dummy")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("TOGA_BACKEND", "toga_dummy")
    monkeypatch.setenv("RUSKIMAXXING_DATA_DIR", str(tmp_path))
    from datetime import date

    from ruskimaxxing.storage import Store
    from ruskimaxxing.tracking import LogEntry

    store = Store(tmp_path / "data.db")
    store.set("start", "2026-01-05")
    store.set("increment", "5")
    store.set("height", "70")
    store.add_lift(LogEntry(date(2025, 12, 29), "Squat", 225, 5, "baseline"))  # e1RM 262.5
    store.close()

    from ruskimaxxing_mobile.app import RuskiMaxxing
    a = RuskiMaxxing("RuskiMaxxing", "io.github.andrewsdillondesign.test")
    a.week, a.day = 1, 0
    a.render_workout()
    yield a


def block(app, name):
    return next(b for b in app.blocks if b["p"].exercise == name)


def test_workout_prefilled(app):
    squat = block(app, "Squat")["widgets"]
    assert len(squat) == 3
    assert [float(w["weight"].value) for w in squat] == [185.0] * 3
    assert [int(w["reps"].value) for w in squat] == [6] * 3
    assert not any(w["done"].value for w in squat)


def test_edit_done_save_and_reload(app):
    from decimal import Decimal
    squat = block(app, "Squat")["widgets"]
    squat[0]["done"].value = True
    squat[1]["done"].value = True
    squat[1]["reps"].value = Decimal(5)
    squat[1]["rpe"].value = "8"
    assert app.dirty
    app.autosave()
    saved = [e for e in app.store.workout(1, 0) if e.exercise == "Squat"]
    assert [(e.weight, e.reps, e.done) for e in saved] == [(185, 6, True), (185, 5, True), (185, 6, False)]
    assert saved[1].rpe == 8
    app.render_workout()
    assert block(app, "Squat")["widgets"][1]["reps"].value == 5


def test_add_set_and_all_done(app):
    app._add_set(app.blocks.index(block(app, "Squat")))
    assert len(block(app, "Squat")["widgets"]) == 4
    app._all_done(None)
    assert all(w["done"].value for w in block(app, "Squat")["widgets"])


def test_every_tab_refreshes(app):
    app.refresh_all()
    assert "Wk 1" in app.week_label.text
    assert app.day_select.value.startswith("Day 1")
