import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
os.environ["RUSKIMAXXING_CLOUD_AUTOSTART"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402

from ruskimaxxing_cloud.main import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path}/cloud.db"))


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(client, email="lifter@example.com", password="squat-heavy"):
    r = client.post("/api/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_register_login_logout(client):
    token = register(client)
    assert client.get("/api/me", headers=auth(token)).json()["email"] == "lifter@example.com"
    assert client.post("/api/register", json={"email": "LIFTER@example.com", "password": "another-pw"}).status_code == 409
    assert client.post("/api/login", json={"email": "lifter@example.com", "password": "wrong-pass"}).status_code == 401
    t2 = client.post("/api/login", json={"email": "Lifter@Example.com ", "password": "squat-heavy"}).json()["token"]
    client.post("/api/logout", headers=auth(t2))
    assert client.get("/api/me", headers=auth(t2)).status_code == 401
    assert client.get("/api/me", headers=auth(token)).status_code == 200  # other session unaffected


def test_short_password_rejected(client):
    assert client.post("/api/register", json={"email": "a@b.co", "password": "short"}).status_code == 422


def change(uid, updated, deleted=False, data=None):
    return {"uid": uid, "kind": "bodyweight", "updated": updated, "deleted": deleted,
            "data": data or {"week": 1, "date": "2026-01-05", "weight": 180}}


def test_sync_last_write_wins_and_incremental(client):
    t = auth(register(client))
    r = client.post("/api/sync", headers=t, json={"edition": "standard", "since": 0,
                                                   "changes": [change("bw:1", "2026-01-05T10:00:00.000000Z")]})
    assert r.json()["seq"] == 1 and len(r.json()["changes"]) == 1
    older = change("bw:1", "2026-01-05T09:00:00.000000Z", data={"week": 1, "date": "2026-01-05", "weight": 999})
    r = client.post("/api/sync", headers=t, json={"edition": "standard", "since": 1, "changes": [older]})
    assert r.json()["changes"] == [] and r.json()["seq"] == 1           # older edit ignored
    newer = change("bw:1", "2026-01-06T09:00:00.000000Z", data={"week": 1, "date": "2026-01-05", "weight": 181})
    r = client.post("/api/sync", headers=t, json={"edition": "standard", "since": 1, "changes": [newer]})
    assert r.json()["changes"][0]["data"]["weight"] == 181
    r = client.post("/api/sync", headers=t, json={"edition": "supertotal", "since": 0, "changes": []})
    assert r.json()["changes"] == []                                    # editions are separate


def test_users_cannot_see_each_other(client):
    a, b = auth(register(client, "a@x.com")), auth(register(client, "b@x.com"))
    client.post("/api/sync", headers=a, json={"edition": "standard", "since": 0,
                                               "changes": [change("bw:1", "2026-01-05T10:00:00.000000Z")]})
    assert client.post("/api/sync", headers=b, json={"edition": "standard", "since": 0}).json()["changes"] == []
    assert client.post("/api/sync", json={"edition": "standard", "since": 0}).status_code == 401


def test_delete_account_removes_everything(client):
    t = auth(register(client))
    client.post("/api/sync", headers=t, json={"edition": "standard", "since": 0,
                                               "changes": [change("bw:1", "2026-01-05T10:00:00.000000Z")]})
    assert client.request("DELETE", "/api/account", headers=t, json={"password": "nope-nope"}).status_code == 401
    assert client.request("DELETE", "/api/account", headers=t, json={"password": "squat-heavy"}).json()["deleted"]
    assert client.post("/api/login", json={"email": "lifter@example.com", "password": "squat-heavy"}).status_code == 401


def test_reset_page_and_privacy(client):
    assert client.post("/api/password-reset", json={"email": "nobody@x.com"}).json()["ok"]
    assert "Invalid" in client.post("/reset", data={"token": "bogus", "password": "whatever1"}).text or \
        "invalid" in client.post("/reset", data={"token": "bogus", "password": "whatever1"}).text
    assert "Delete account" in client.get("/privacy").text
