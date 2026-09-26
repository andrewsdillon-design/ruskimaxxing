import os

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app(tmp_path):
    if not os.environ.get("DISPLAY"):
        pytest.skip("needs a display (run under xvfb-run)")
    from datetime import date

    from ruskimaxxing.gui import App
    from ruskimaxxing.storage import Store
    from ruskimaxxing.tracking import LogEntry

    store = Store(tmp_path / "d.db")
    store.set("start", "2026-01-05")
    store.set("increment", "5")
    store.add_lift(LogEntry(date(2025, 12, 29), "Squat", 225, 5, "baseline"))  # e1RM 262.5
    root = tk.Tk()
    app = App(root, store)
    app.week.set(app.week_labels[1])
    app.day_var.set(0)
    app.refresh()
    yield app
    root.destroy()


def block(app, name):
    return next(b for b in app.wo_blocks if b["p"].exercise == name)


def test_every_tab_builds(app):
    for i in range(app.tabs.index("end")):
        app.tabs.select(i)
        app.root.update()
    assert app.export_data()["baseline"] == [("Squat", 225, 5)]


def test_workout_prefilled_with_plan(app):
    squat = block(app, "Squat")
    assert len(squat["vars"]) == squat["p"].sets == 3
    assert [v["weight"].get() for v in squat["vars"]] == ["185"] * 3  # 70% of 262.5, nearest 5
    assert [v["reps"].get() for v in squat["vars"]] == ["6"] * 3
    assert not any(v["done"].get() for v in squat["vars"])
    assert block(app, "Barbell Row")["vars"][0]["reps"].get() == "8"  # low end of 8-10


def test_edit_mark_done_save_and_reload(app):
    squat = block(app, "Squat")
    squat["vars"][2]["reps"].set("5")        # missed a rep on the last set
    squat["vars"][0]["rpe"].set("8")
    squat["note_var"].set("felt good")
    app._add_set(app.wo_blocks.index(block(app, "Squat")))
    block(app, "Squat")["vars"][3]["weight"].set("195")
    app._mark_all_done()
    prs = app._save_workout(quiet=True)
    assert any(p.startswith("Squat:") for p in prs)

    saved = [e for e in app.store.workout(1, 0) if e.exercise == "Squat"]
    assert [(e.weight, e.reps, e.done) for e in saved] == [(185, 6, True), (185, 6, True), (185, 5, True),
                                                           (195, 5, True)]
    assert saved[0].rpe == 8 and saved[0].note == "felt good"

    app.day_var.set(1)
    app.refresh()
    app.day_var.set(0)
    app.refresh()
    reloaded = block(app, "Squat")["vars"]
    assert [v["reps"].get() for v in reloaded] == ["6", "6", "5", "5"] and reloaded[3]["weight"].get() == "195"
    assert "15/15 sets" in app.day_buttons[0].cget("text") or "sets" in app.day_buttons[0].cget("text")


def test_unsaved_edits_are_kept_when_switching_day(app):
    block(app, "Squat")["vars"][0]["weight"].set("190")
    block(app, "Squat")["vars"][0]["done"].set(True)
    app.day_var.set(2)
    app.refresh()
    first = [e for e in app.store.workout(1, 0) if e.exercise == "Squat"][0]
    assert first.weight == 190 and first.done


def test_month_and_week_dropdowns(app):
    assert app.month_pick.get().startswith("Month 1 - Weeks 1-4")
    assert len(app.week_combo["values"]) == 4
    app.month_pick.set(app.month_labels[13])
    app._pick_month()
    assert app._week() == 49 and app.week_combo["values"][-1].startswith("Week 52")
    app._today()
    assert app.month_pick.get() == app.month_labels[__import__("ruskimaxxing.program").program.month_of(app._week())]


def test_cloud_sign_in_states(app, monkeypatch):
    import time
    import webbrowser

    def labels():
        return [w.cget("text") for w in app.cloud_btns.winfo_children()]
    assert "Sign up or log in on the website" in labels()
    s = app.store
    s.set("cloud_link_device", "dev"), s.set("cloud_link_code", "ABCD-EFGH")
    s.set("cloud_link_until", str(time.time() + 600))
    app.refresh_cloud()
    assert "Code ABCD-EFGH" in labels() and "Cancel" in labels()
    app._cloud_cancel()
    assert "Sign up or log in on the website" in labels()
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    s.set("cloud_token", "t"), s.set("cloud_email", "me@example.com")
    app.refresh_cloud()
    assert "Back up now" in labels()
    app._cloud_delete()
    assert opened == ["https://api.ruskimaxxing.com/account/delete"]


def test_update_bar(app):
    from ruskimaxxing.updates import Update
    app._show_update(Update("99.0.0", "https://dl/win.exe", "https://page"), asked=False)
    assert app.update_bar.winfo_manager() == "pack"
    texts = [w.cget("text") for w in app.update_bar.winfo_children()]
    assert any("99.0.0" in t for t in texts) and "Download" in texts
    next(w for w in app.update_bar.winfo_children() if w.cget("text") == "Not now").invoke()
    assert app.update_bar.winfo_manager() == ""
    app._show_update(Update("99.0.0", "u", "p"), asked=False)       # dismissed: stays hidden
    assert app.update_bar.winfo_manager() == ""
    app._show_update(None, asked=True)
    assert "latest" in app.update_status.cget("text")
