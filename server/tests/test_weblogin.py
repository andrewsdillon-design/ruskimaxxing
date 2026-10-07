"""Website sign-up / log in / forgot / delete, and 'sign in with your browser' for the apps."""

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
os.environ["RUSKIMAXXING_CLOUD_AUTOSTART"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402

import ruskimaxxing_cloud.main as m  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://testserver")
    for k in ("STRIPE_SECRET_KEY", "SMTP_HOST"):
        monkeypatch.delenv(k, raising=False)
    return TestClient(m.create_app(f"sqlite:///{tmp_path}/cloud.db"), base_url="https://testserver")


def signup(client, email="new@example.com", pw="deadlift-500", pw2=None, nxt="/account"):
    return client.post("/account/register", data={"email": email, "password": pw, "password2": pw2 or pw,
                                                  "next": nxt}, follow_redirects=False)


def test_signup_page_and_account_creation(client):
    page = client.get("/account").text
    assert "Create an account" in page and "Forgot password?" in page
    form = client.get("/signup").text
    assert 'name="password2"' in form and 'href="/terms"' in form
    bad = signup(client, pw2="different-pass")
    assert bad.status_code == 400 and "match" in bad.text
    assert signup(client, email="nope").status_code == 400
    r = signup(client)
    assert r.status_code == 303 and r.headers["location"] == "/account"
    assert "Signed in as new@example.com" in client.get("/account").text
    # the same account works from the apps' API
    assert client.post("/api/login", json={"email": "new@example.com", "password": "deadlift-500"}).status_code == 200
    client.cookies.clear()
    dup = signup(client)
    assert dup.status_code == 409 and "already has an account" in dup.text


def test_login_next_is_local_only(client):
    signup(client)
    client.cookies.clear()
    r = client.post("/account/login", data={"email": "new@example.com", "password": "deadlift-500",
                                            "next": "https://evil.example/x"}, follow_redirects=False)
    assert r.headers["location"] == "/account"
    client.cookies.clear()
    r = client.post("/account/login", data={"email": "new@example.com", "password": "deadlift-500",
                                            "next": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/account"
    bad = client.post("/account/login", data={"email": "new@example.com", "password": "wrong-pass"})
    assert bad.status_code == 401 and "Wrong email or password" in bad.text


def test_forgot_and_delete_on_website(client):
    assert "Send reset link" in client.get("/account/forgot").text
    assert "reset link is on its way" in client.post("/account/forgot", data={"email": "x@example.com"}).text
    signup(client)
    assert "Delete my account" in client.get("/account/delete").text
    assert client.post("/account/delete", data={"password": "wrong-pass"}).status_code == 401
    assert "deleted" in client.post("/account/delete", data={"password": "deadlift-500"}).text
    assert client.post("/api/login", json={"email": "new@example.com", "password": "deadlift-500"}).status_code == 401


def test_app_sign_in_with_browser(client):
    start = client.post("/api/link/start", json={"edition": "supertotal", "phone": True}).json()
    assert start["url"].endswith("&app=1")      # phone apps' pages show nothing to buy (see test_billing)
    code, device = start["url"].split("code=")[1].split("&")[0], start["device_code"]
    assert start["code"] == f"{code[:4]}-{code[4:]}"
    assert client.post("/api/link/poll", json={"device_code": device}).status_code == 202   # not yet
    # the browser: not logged in -> sign-in page that comes back to the link
    page = client.get(f"/link?code={code}").text
    assert "Log in" in page and "Create an account" in page and f"/link?code={code}" in page
    # new user signs up from there and lands back on the link page
    r = signup(client, nxt=f"/link?code={code}")
    assert r.headers["location"] == f"/link?code={code}"
    confirm = client.get(r.headers["location"]).text
    assert "Connect this app" in confirm
    done = client.post("/link", data={"code": code}).text
    assert "You're signed in" in done and 'href="ruskimaxxingsupertotal://signed-in"' in done
    token = client.post("/api/link/poll", json={"device_code": device})
    assert token.status_code == 200 and token.json()["email"] == "new@example.com"
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token.json()['token']}"})
    assert me.status_code == 200
    # one use only
    assert client.post("/api/link/poll", json={"device_code": device}).status_code == 410
    assert "expired" in client.get(f"/link?code={code}").text


def test_link_needs_same_site_post_and_valid_code(client):
    start = client.post("/api/link/start", json={"edition": "standard"}).json()
    code = start["url"].split("code=")[1]
    signup(client)
    assert client.post("/link", data={"code": code}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/link/poll", json={"device_code": "made-up"}).status_code == 410
    done = client.post("/link", data={"code": code}).text
    assert "Return to the app" not in done           # desktop apps just switch back
    assert client.post("/api/link/start", json={"edition": "bogus"}).status_code == 400
