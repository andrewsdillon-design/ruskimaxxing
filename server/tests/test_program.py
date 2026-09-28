"""Program-year one-time purchases: chain enforcement, consent, refunds, webhook, and admin visibility."""

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("stripe")
os.environ["RUSKIMAXXING_CLOUD_AUTOSTART"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

import ruskimaxxing_cloud.main as m  # noqa: E402
from ruskimaxxing_cloud import totp  # noqa: E402

WHSEC = "whsec_test_secret"


@pytest.fixture
def app_and_client(tmp_path, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WHSEC)
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_test")
    monkeypatch.setenv("PUBLIC_URL", "https://testserver")
    monkeypatch.setattr(m, "stripe_checkout_program_year",
                        lambda user, base, year, consent_version: f"https://checkout.stripe.test/{user.id}/{year}")
    monkeypatch.setattr(m, "stripe_refund_purchase", lambda purchase: True)
    app = m.create_app(f"sqlite:///{tmp_path}/cloud.db")
    return app, TestClient(app, base_url="https://testserver")


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


@pytest.fixture
def app(app_and_client):
    return app_and_client[0]


def register_and_login(client, email="lifter@example.com"):
    client.post("/api/register", json={"email": email, "password": "squat-heavy"})
    r = client.post("/account/login", data={"email": email, "password": "squat-heavy"}, follow_redirects=False)
    assert r.status_code == 303
    return r.cookies


def webhook(client, event):
    payload = json.dumps(event)
    t = int(time.time())
    sig = hmac.new(WHSEC.encode(), f"{t}.{payload}".encode(), hashlib.sha256).hexdigest()
    return client.post("/stripe/webhook", content=payload,
                       headers={"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"})


def program_year_event(user_id, year, session_id="cs_1", consent_version="2026-09-28", amount_total=19900,
                       payment_intent="pi_1"):
    return {"id": session_id, "object": "event", "type": "checkout.session.completed",
           "data": {"object": {"id": session_id, "object": "checkout.session", "mode": "payment",
                               "client_reference_id": str(user_id), "customer": "cus_1",
                               "payment_intent": payment_intent, "amount_total": amount_total, "currency": "usd",
                               "metadata": {"kind": "program_year", "year": str(year), "user_id": str(user_id),
                                           "consent_version": consent_version}}}}


def test_price_map_default_and_next_purchasable_year():
    assert m.program_year_prices() == {2: 19900, 3: 29900}
    assert m.next_purchasable_year([1]) == 2
    assert m.next_purchasable_year([1, 2]) == 3
    assert m.next_purchasable_year([1, 2, 3]) is None  # nothing configured past year 3


def test_checkout_requires_both_checkboxes(client):
    cookies = register_and_login(client)
    r = client.post("/account/program/2/checkout", cookies=cookies)
    assert r.status_code == 400 and "tick both boxes" in r.text
    r = client.post("/account/program/2/checkout", data={"consent": "yes"}, cookies=cookies)
    assert r.status_code == 400
    r = client.post("/account/program/2/checkout", data={"consent": "yes", "terms": "yes"}, cookies=cookies,
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("https://checkout.stripe.test/")


def test_chain_enforcement_cant_skip_a_year(client):
    cookies = register_and_login(client)
    r = client.post("/account/program/3/checkout", data={"consent": "yes", "terms": "yes"}, cookies=cookies)
    assert r.status_code == 400 and "previous program year" in r.text.lower()


def test_cant_buy_a_year_not_in_the_price_map(client):
    cookies = register_and_login(client)
    r = client.post("/account/program/99/checkout", data={"consent": "yes", "terms": "yes"}, cookies=cookies)
    assert r.status_code == 400 and "available yet" in r.text


def test_webhook_creates_purchase_and_grants_consent_idempotently(client, app):
    cookies = register_and_login(client)
    with m.Session(app.state.engine) as s:
        user_id = s.scalar(select(m.User.id).where(m.User.email == "lifter@example.com"))

    r = webhook(client, program_year_event(user_id, 2))
    assert r.status_code == 200

    with m.Session(app.state.engine) as s:
        user = s.get(m.User, user_id)
        assert user.coaching_consent_at is not None
        assert user.coaching_consent_version == "2026-09-28"
        purchases = s.scalars(select(m.ProgramPurchase).where(m.ProgramPurchase.user_id == user_id)).all()
        assert len(purchases) == 1 and purchases[0].year == 2 and purchases[0].amount_cents == 19900
        events = s.scalars(select(m.ConsentEvent).where(m.ConsentEvent.user_id == user_id)).all()
        assert len(events) == 1 and events[0].action == "grant" and events[0].source == "purchase"

    # replaying the same event (same session id) must not create a duplicate purchase
    webhook(client, program_year_event(user_id, 2))
    with m.Session(app.state.engine) as s:
        purchases = s.scalars(select(m.ProgramPurchase).where(m.ProgramPurchase.user_id == user_id)).all()
        assert len(purchases) == 1

    me = client.get("/api/me", headers=_auth_header(client, "lifter@example.com")).json()
    assert me["program_years"] == [1, 2]


def _auth_header(client, email):
    r = client.post("/api/login", json={"email": email, "password": "squat-heavy"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_refund_only_most_recent_year_within_window(client, app):
    cookies = register_and_login(client)
    with m.Session(app.state.engine) as s:
        user_id = s.scalar(select(m.User.id).where(m.User.email == "lifter@example.com"))
    webhook(client, program_year_event(user_id, 2, session_id="cs_y2", payment_intent="pi_y2"))
    webhook(client, program_year_event(user_id, 3, session_id="cs_y3", payment_intent="pi_y3", amount_total=29900))

    # Year 2 is no longer the most recent purchase, so it can't be refunded directly
    r = client.post("/account/program/2/refund", cookies=cookies, follow_redirects=False)
    assert r.headers["location"] == "/account/program?msg=norefund"

    r = client.post("/account/program/3/refund", cookies=cookies, follow_redirects=False)
    assert r.headers["location"] == "/account/program?msg=refunded"
    with m.Session(app.state.engine) as s:
        p3 = s.scalar(select(m.ProgramPurchase).where(m.ProgramPurchase.user_id == user_id, m.ProgramPurchase.year == 3))
        assert p3.refunded_at is not None
    me = client.get("/api/me", headers=_auth_header(client, "lifter@example.com")).json()
    assert me["program_years"] == [1, 2]


def test_refund_outside_window_is_refused(client, app):
    cookies = register_and_login(client)
    with m.Session(app.state.engine) as s:
        user_id = s.scalar(select(m.User.id).where(m.User.email == "lifter@example.com"))
    webhook(client, program_year_event(user_id, 2))
    with m.Session(app.state.engine) as s:
        purchase = s.scalar(select(m.ProgramPurchase).where(m.ProgramPurchase.user_id == user_id))
        purchase.purchased_at = m.utcnow() - timedelta(days=m.REFUND_DAYS + 1)
        s.commit()
    r = client.post("/account/program/2/refund", cookies=cookies, follow_redirects=False)
    assert r.headers["location"] == "/account/program?msg=norefund"


def test_withdraw_clears_consent_and_hides_data_from_admin(client, app):
    cookies = register_and_login(client)
    with m.Session(app.state.engine) as s:
        user_id = s.scalar(select(m.User.id).where(m.User.email == "lifter@example.com"))
    webhook(client, program_year_event(user_id, 2))

    page = client.get("/account/program", cookies=cookies).text
    assert "granted" in page

    r = client.post("/account/consent/withdraw", cookies=cookies, follow_redirects=False)
    assert r.status_code == 303
    with m.Session(app.state.engine) as s:
        user = s.get(m.User, user_id)
        assert user.coaching_consent_at is None
        events = s.scalars(select(m.ConsentEvent).where(m.ConsentEvent.user_id == user_id,
                                                        m.ConsentEvent.action == "withdraw")).all()
        assert len(events) == 1 and events[0].source == "account"

    # program years keep working even without consent
    me = client.get("/api/me", headers=_auth_header(client, "lifter@example.com")).json()
    assert me["program_years"] == [1, 2]

    # admin no longer sees training data for this user
    secret = totp.new_secret()
    with m.Session(app.state.engine) as s:
        admin = m.User(email="admin@example.com", password_hash=m.ph.hash("correct-horse-battery-9"),
                       is_admin=True, totp_secret=secret)
        s.add(admin)
        s.commit()
    r = client.post("/admin/login", data={"email": "admin@example.com", "password": "correct-horse-battery-9",
                                          "code": totp.current_code(secret)}, follow_redirects=False)
    assert r.status_code == 303
    detail = client.get(f"/admin/users/{user_id}").text
    assert "hidden" in detail.lower()


def test_re_grant_requires_owning_a_paid_year(client):
    cookies = register_and_login(client)
    r = client.post("/account/consent/grant", data={"consent": "yes"}, cookies=cookies)
    assert r.status_code == 400


def test_api_me_program_years_defaults_to_year_one(client):
    register_and_login(client)
    me = client.get("/api/me", headers=_auth_header(client, "lifter@example.com")).json()
    assert me["program_years"] == [1]
    assert "streak" not in me or me.get("streak") is None
