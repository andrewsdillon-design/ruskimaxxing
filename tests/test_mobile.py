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
    assert app.week_label.text.startswith("Month 1 of 13")
    assert app.day_select.value.startswith("Day 1")


def test_month_and_week_dropdowns(app):
    app.render_workout()
    assert app.month_select.value.startswith("Month 1 - Weeks 1-4")
    assert [r.value.split(" - ")[0] for r in app.week_select.items] == ["Wk 1", "Wk 2", "Wk 3", "Wk 4"]
    app.month_select.value = app.month_items[4]          # Month 4 -> jumps to its first week (13)
    app._month_changed(app.month_select)                 # (toga_dummy doesn't fire on_change itself)
    assert app.week == 13 and app.week_label.text == "Month 4 of 13  -  Week 13 of 52"
    app.week_select.value = app.week_items[2]     # third week of month 4
    app._week_changed(app.week_select)
    assert app.week == 15 and app.week_select.value.startswith("Wk 15")
    app.month_select.value = app.month_items[0]          # baseline
    app._month_changed(app.month_select)
    assert app.week == 0 and app.week_label.text.startswith("Baseline")


def test_day_dropdown(app):
    app.render_workout()
    app.day_select.value = app.day_items[2]
    app._day_changed(app.day_select)
    assert app.day == 2 and app.day_select.value.startswith("Day 3")


def texts(box):
    out = []
    for w in box.children:
        out += texts(w) if w.children else [getattr(w, "text", "")]
    return out


def test_cloud_section_is_just_a_link(app, monkeypatch):
    import time

    import ruskimaxxing_mobile.app as mod
    opened = []
    monkeypatch.setattr(mod, "open_url", opened.append)
    monkeypatch.setattr(app, "_watch_sign_in", lambda: None)
    app.refresh_cloud()
    assert texts(app.cloud_box) == ["Create account or log in at ruskimaxxing.com"]   # nothing else
    s = app.store
    s.set("cloud_link_device", "dev"), s.set("cloud_link_code", "ABCD-EFGH")
    s.set("cloud_link_url", "https://api.ruskimaxxing.com/link?code=ABCDEFGH")
    s.set("cloud_link_until", str(time.time() + 600))
    app.refresh_cloud()                                   # waiting: still just the link, no code or boxes
    assert texts(app.cloud_box) == ["Create account or log in at ruskimaxxing.com"]
    assert "come back here" in app.cloud_status.text
    import asyncio
    asyncio.run(app._cloud_sign_in(None))                 # tapping it again reopens the same page
    assert opened == ["https://api.ruskimaxxing.com/link?code=ABCDEFGH"]
    s.set("cloud_token", "t"), s.set("cloud_email", "me@example.com")
    app.refresh_cloud()
    assert "Back up now" in texts(app.cloud_box) and "me@example.com" in app.cloud_status.text
    app._cloud_delete(None)                               # in-app deletion: asks for the password
    assert "Delete forever" in texts(app.cloud_box)
    app._cloud_delete_web(None)                           # fallback: the website's delete page
    assert opened[-1] == "https://api.ruskimaxxing.com/account/delete?app=1"
    deleted = []

    def fake_delete(password):
        deleted.append(password)
        s.set("cloud_token", ""), s.set("cloud_email", "")
    monkeypatch.setattr(app.cloud, "delete_account", fake_delete)
    monkeypatch.setattr(app, "info", lambda *a: asyncio.sleep(0))
    app.delete_password.value = "hunter22"
    asyncio.run(app._cloud_delete_confirm(None))
    assert deleted == ["hunter22"] and not app.cloud.logged_in
    assert texts(app.cloud_box) == ["Create account or log in at ruskimaxxing.com"]


def test_privacy_and_terms_links(app, monkeypatch):
    import ruskimaxxing_mobile.app as mod
    opened = []
    monkeypatch.setattr(mod, "open_url", opened.append)
    def find(box, text):
        for w in box.children:
            if getattr(w, "text", None) == text:
                return w
            if w.children and (hit := find(w, text)):
                return hit
    setup = app.tabs.content[4].content
    find(setup.content, "Privacy policy").on_press()
    find(setup.content, "Terms").on_press()
    assert opened == ["https://api.ruskimaxxing.com/privacy?app=1", "https://api.ruskimaxxing.com/terms?app=1"]

def test_update_banner(app):
    from ruskimaxxing.updates import Update
    app.show_update(Update("99.0.0", "https://dl/app.apk", "https://page"))
    assert any("99.0.0" in t for t in texts(app.update_row))
    later = next(w for w in app.update_row.children[0].children if getattr(w, "text", "") == "Later")
    later.on_press()
    assert not app.update_row.children
    app.show_update(Update("99.0.0", "u", "p"))                 # dismissed: stays hidden
    assert not app.update_row.children and "99.0.0 is out" in app.update_status.text
