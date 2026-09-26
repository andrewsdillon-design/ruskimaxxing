import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("stripe")
os.environ["RUSKIMAXXING_CLOUD_AUTOSTART"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402

import ruskimaxxing_cloud.main as m  # noqa: E402

WHSEC = "whsec_test_secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WHSEC)
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_test")
    monkeypatch.setenv("PUBLIC_URL", "https://testserver")
    monkeypatch.setenv("COMPLIMENTARY_EMAILS", "owner@example.com")
    monkeypatch.setattr(m, "stripe_checkout", lambda user, base: f"https://checkout.stripe.test/{user.id}")
    monkeypatch.setattr(m, "stripe_portal", lambda user, base: "https://billing.stripe.test/portal")
    return TestClient(m.create_app(f"sqlite:///{tmp_path}/cloud.db"), base_url="https://testserver")


def register(client, email="lifter@example.com"):
    r = client.post("/api/register", json={"email": email, "password": "squat-heavy"})
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()


BW = {"uid": "bw:1", "kind": "bodyweight", "updated": "2026-01-05T10:00:00.000000Z", "deleted": False,
      "data": {"week": 1, "date": "2026-01-05", "weight": 180}}


def webhook(client, event):
    payload = json.dumps(event)
    t = int(time.time())
    sig = hmac.new(WHSEC.encode(), f"{t}.{payload}".encode(), hashlib.sha256).hexdigest()
    return client.post("/stripe/webhook", content=payload,
                       headers={"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"})


def subscription(user_id, status="active", days=365, kind="customer.subscription.updated"):
    return {"id": "evt_1", "object": "event", "type": kind, "data": {"object": {
        "id": "sub_1", "object": "subscription", "customer": "cus_1", "status": status,
        "metadata": {"user_id": str(user_id)},
        "items": {"data": [{"current_period_end": int(time.time()) + days * 86400}]}}}}


def test_backup_needs_plan_but_restore_works(client):
    h, body = register(client)
    assert body["plan"]["active"] is False and body["plan"]["price"] == "$20/year"
    r = client.post("/api/sync", headers=h, json={"edition": "standard", "since": 0, "changes": [BW]})
    assert r.status_code == 402 and "isn't active" in r.json()["detail"]
    assert "$" not in r.json()["detail"] and "http" not in r.json()["detail"]  # apps never show a price or link
    r = client.post("/api/sync", headers=h, json={"edition": "standard", "since": 0, "changes": []})
    assert r.status_code == 200 and r.json()["plan"]["active"] is False     # restore still allowed


def test_complimentary_accounts_are_free(client):
    h, body = register(client, "owner@example.com")
    assert body["plan"]["active"] and body["plan"]["complimentary"]
    assert client.post("/api/sync", headers=h, json={"edition": "standard", "since": 0,
                                                      "changes": [BW]}).status_code == 200


def test_webhook_activates_and_lapses_plan(client):
    h, _ = register(client)
    assert client.get("/api/me", headers=h).json()["plan"]["until"] is None
    user_id = 1
    assert webhook(client, {"id": "evt_0", "object": "event", "type": "checkout.session.completed",
                            "data": {"object": {"client_reference_id": str(user_id), "customer": "cus_1"}}}
                   ).status_code == 200
    assert webhook(client, subscription(user_id)).status_code == 200
    plan = client.get("/api/me", headers=h).json()["plan"]
    assert plan["active"] and plan["status"] == "active" and plan["until"] >= time.strftime("%Y-%m-%d")
    assert client.post("/api/sync", headers=h, json={"edition": "standard", "since": 0,
                                                      "changes": [BW]}).status_code == 200
    webhook(client, subscription(user_id, "canceled", days=-10, kind="customer.subscription.deleted"))
    assert client.get("/api/me", headers=h).json()["plan"]["active"] is False
    r = client.post("/api/sync", headers=h, json={"edition": "standard", "since": 0, "changes": []})
    assert r.json()["changes"][0]["uid"] == "bw:1"                        # data kept after lapse


def test_webhook_rejects_bad_signature(client):
    r = client.post("/stripe/webhook", content=json.dumps(subscription(1)),
                    headers={"Stripe-Signature": "t=1,v1=forged"})
    assert r.status_code == 400


def test_account_page_login_subscribe_manage(client):
    register(client)
    assert "Log in" in client.get("/account").text
    bad = client.post("/account/login", data={"email": "lifter@example.com", "password": "nope"})
    assert bad.status_code == 401
    r = client.post("/account/login", data={"email": "lifter@example.com", "password": "squat-heavy"},
                    follow_redirects=False)
    assert r.status_code == 303 and "rmx_session" in r.headers["set-cookie"]
    page = client.get("/account").text
    assert "No active plan" in page and "Subscribe - $20/year" in page
    r = client.post("/account/subscribe", follow_redirects=False)
    assert r.headers["location"] == "https://checkout.stripe.test/1"
    # cross-site form posts are refused
    assert client.post("/account/subscribe", headers={"Origin": "https://evil.example"}).status_code == 403
    webhook(client, {"id": "e", "object": "event", "type": "checkout.session.completed",
                     "data": {"object": {"client_reference_id": "1", "customer": "cus_1"}}})
    webhook(client, subscription(1))
    assert "Plan active" in client.get("/account").text
    assert client.post("/account/manage", follow_redirects=False).headers["location"].startswith(
        "https://billing.stripe.test")


def test_no_stripe_keys_means_free(tmp_path, monkeypatch):
    for k in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_ID"):
        monkeypatch.delenv(k, raising=False)
    c = TestClient(m.create_app(f"sqlite:///{tmp_path}/free.db"))
    h, body = register(c)
    assert body["plan"]["active"] and not body["plan"]["billing"]
    assert c.post("/api/sync", headers=h, json={"edition": "standard", "since": 0, "changes": [BW]}).status_code == 200


def test_setup_stripe_script_creates_then_reuses(tmp_path):
    """setup_stripe.py against a fake Stripe: first run creates everything, second run reuses it."""
    import importlib.util
    from types import SimpleNamespace as NS
    spec = importlib.util.spec_from_file_location("setup_stripe", Path(__file__).parent.parent / "deploy" /
                                                  "setup_stripe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    made = {"price": [], "hook": [], "cfg": []}

    class Lister:
        def __init__(self, key, factory):
            self.key, self.factory = key, factory

        def list(self, **kw):
            return NS(data=made[self.key])

        def create(self, **kw):
            obj = self.factory(kw)
            made[self.key].append(obj)
            return obj

    fake = NS(Price=Lister("price", lambda kw: NS(id="price_1", **kw)),
              Product=NS(create=lambda **kw: NS(id="prod_1")),
              WebhookEndpoint=Lister("hook", lambda kw: NS(id="we_1", secret="whsec_1", url=kw["url"])),
              billing_portal=NS(Configuration=Lister("cfg", lambda kw: NS(id="bpc_1"))))
    env = mod.setup(fake, "https://api.x.com/")
    assert env == {"STRIPE_PRICE_ID": "price_1", "STRIPE_WEBHOOK_SECRET": "whsec_1", "STRIPE_PORTAL_CONFIG": "bpc_1"}
    price = made["price"][0]
    assert price.unit_amount == 2000 and price.recurring == {"interval": "year"} and price.currency == "usd"
    assert made["hook"][0].url == "https://api.x.com/stripe/webhook"
    again = mod.setup(fake, "https://api.x.com")
    assert again == {"STRIPE_PRICE_ID": "price_1", "STRIPE_PORTAL_CONFIG": "bpc_1"} and len(made["price"]) == 1
    envfile = tmp_path / "env"
    envfile.write_text("DATABASE_URL=x\nSTRIPE_PRICE_ID=old\n")
    mod.write_env(envfile, env)
    assert envfile.read_text() == ("DATABASE_URL=x\nSTRIPE_PRICE_ID=price_1\nSTRIPE_WEBHOOK_SECRET=whsec_1\n"
                                   "STRIPE_PORTAL_CONFIG=bpc_1\n")
