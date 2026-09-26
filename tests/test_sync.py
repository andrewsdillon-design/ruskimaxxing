"""End-to-end: two devices backing up to and restoring from the real server code."""

import os
import sys
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("argon2")
if not (Path(__file__).resolve().parent.parent / "server").exists():
    pytest.skip("the cloud server lives in the ruskimaxxing repo", allow_module_level=True)
os.environ["RUSKIMAXXING_CLOUD_AUTOSTART"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from fastapi.testclient import TestClient  # noqa: E402

from ruskimaxxing.storage import Store  # noqa: E402
from ruskimaxxing.sync import Cloud, CloudError  # noqa: E402
from ruskimaxxing.tracking import BodyFat, BodyWeight, LogEntry  # noqa: E402
from ruskimaxxing_cloud.main import Base, create_app  # noqa: E402

URL = "https://cloud.test"


@pytest.fixture
def transport(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path}/cloud.db"
    app = create_app(url)
    if url.startswith("postgresql"):  # start each test from an empty database
        Base.metadata.drop_all(app.state.engine)
        Base.metadata.create_all(app.state.engine)
    client = TestClient(app)

    def call(method, url, body, token):
        r = client.request(method, url[len(URL):], json=body,
                           headers={"Authorization": f"Bearer {token}"} if token else {})
        return r.status_code, r.json()
    call.client = client
    return call


def device(tmp_path, name, transport):
    return Cloud(Store(tmp_path / f"{name}.db"), transport)


def test_lost_phone_restore(tmp_path, transport):
    phone = device(tmp_path, "old-phone", transport)
    s = phone.store
    s.set("start", "2026-01-05")
    s.set("height", "70")
    s.add_lift(LogEntry(date(2025, 12, 29), "Squat", 225, 5, "baseline"))
    s.save_workout(1, 0, [LogEntry(date(2026, 1, 5), "Squat", 185, 6, set_no=1),
                          LogEntry(date(2026, 1, 5), "Squat", 185, 5, set_no=2, rpe=8.5)])
    s.set_bodyweight(BodyWeight(1, date(2026, 1, 5), 180.5))
    s.set_bodyfat(BodyFat(1, date(2026, 1, 6), 18.5, "Bod Pod", 180))
    phone.register(URL, "lifter@example.com", "squat-heavy")
    assert phone.sync()[0] >= 6

    new = device(tmp_path, "new-phone", transport)
    new.login(URL, "lifter@example.com", "squat-heavy")
    new.sync()
    n = new.store
    assert n.get("start") == "2026-01-05" and n.get("height") == "70"
    assert sorted((e.exercise, e.weight, e.reps, e.rpe) for e in n.workout(1, 0)) == \
        [("Squat", 185, 5, 8.5), ("Squat", 185, 6, None)]
    assert [e.kind for e in n.lifts() if e.week is None] == ["baseline"]
    assert n.bodyweights()[0].weight == 180.5 and n.bodyfats()[0].method == "Bod Pod"
    assert n.get("cloud_token") != phone.store.get("cloud_token")  # login state is per device


def test_two_devices_merge_and_deletions(tmp_path, transport):
    a, b = device(tmp_path, "a", transport), device(tmp_path, "b", transport)
    a.register(URL, "x@y.com", "password1")
    b.login(URL, "x@y.com", "password1")
    a.store.set_bodyweight(BodyWeight(1, date(2026, 1, 5), 180))
    a.sync()
    b.sync()
    b.store.set_bodyweight(BodyWeight(1, date(2026, 1, 5), 182))   # later edit on b wins
    b.store.set_bodyweight(BodyWeight(2, date(2026, 1, 12), 183))
    b.sync()
    a.sync()
    assert [(w.week, w.weight) for w in a.store.bodyweights()] == [(1, 182), (2, 183)]
    a.store.delete_bodyweight(2)                                      # deletions travel too
    a.sync()
    b.sync()
    assert [w.week for w in b.store.bodyweights()] == [1]
    # re-saving a workout doesn't duplicate sets on the other device
    for _ in range(2):
        a.store.save_workout(1, 0, [LogEntry(date(2026, 1, 5), "Squat", 185, 6, set_no=1)])
        a.sync()
    b.sync()
    assert len(b.store.workout(1, 0)) == 1


def test_errors_and_logout(tmp_path, transport):
    c = device(tmp_path, "c", transport)
    with pytest.raises(CloudError):
        c.sync()
    c.register(URL, "c@y.com", "password1")
    with pytest.raises(CloudError, match="already has an account"):
        device(tmp_path, "d", transport).register(URL, "c@y.com", "password1")
    c.logout()
    assert not c.logged_in and "Not signed in" in c.status()
    c.login(URL, "c@y.com", "password1")
    c.delete_account("password1")
    assert not c.logged_in


def test_inactive_plan_restores_and_queues_backups(tmp_path, transport, monkeypatch):
    """Paid storage: without a plan, restore still works and local edits wait until backups are active."""
    free = device(tmp_path, "free", transport)
    free.register(URL, "free@y.com", "password1")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")   # billing on from here
    free.store.set_bodyweight(BodyWeight(1, date(2026, 1, 5), 180))
    with pytest.raises(CloudError, match="isn't active") as err:
        free.sync()
    assert err.value.code == 402 and "$" not in str(err.value)
    assert "aren't active" in free.status()
    monkeypatch.setenv("COMPLIMENTARY_EMAILS", "free@y.com")   # plan becomes active
    sent, _ = free.sync()
    assert sent >= 1                                           # the queued edit went up
    other = device(tmp_path, "other", transport)
    other.login(URL, "free@y.com", "password1")
    other.sync()
    assert other.store.bodyweights()[0].weight == 180


def test_sign_in_with_browser(tmp_path, transport):
    """The app opens the website; the person signs up there; the app picks up the login by itself."""
    phone = device(tmp_path, "phone", transport)
    phone.store.set("cloud_url", URL)
    phone.store.set_bodyweight(BodyWeight(1, date(2026, 1, 5), 181))
    link = phone.start_browser_sign_in(phone=True)
    assert phone.pending_code == link["code"] and "code" in phone.status()
    assert phone.poll_sign_in() is False                       # still waiting
    browser = transport.client
    code = link["url"].split("code=")[1]
    r = browser.post("/account/register", data={"email": "web@example.com", "password": "clean-jerk-1",
                                                "password2": "clean-jerk-1", "next": f"/link?code={code}"})
    assert "Connect this app" in r.text                         # followed the redirect back to the link page
    assert "You're signed in" in browser.post("/link", data={"code": code}).text
    assert phone.poll_sign_in() is True
    assert phone.logged_in and phone.email == "web@example.com" and phone.pending_code == ""
    assert phone.sync()[0] >= 1                                 # and backups work right away


def test_sign_in_link_expiry_and_cancel(tmp_path, transport):
    phone = device(tmp_path, "phone", transport)
    phone.store.set("cloud_url", URL)
    phone.start_browser_sign_in()
    phone.cancel_sign_in()
    assert phone.pending_code == "" and not phone.logged_in
    with pytest.raises(CloudError):
        phone.poll_sign_in()
    phone.start_browser_sign_in()
    phone.store.set("cloud_link_until", "1")                    # long expired
    assert phone.pending_code == "" and "Not signed in" in phone.status()
