"""Terms page, 30-day refunds, renewal consent/confirmation emails and renewal reminders."""

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("stripe")
os.environ["RUSKIMAXXING_CLOUD_AUTOSTART"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy.orm import Session  # noqa: E402

import ruskimaxxing_cloud.main as m  # noqa: E402
from test_billing import client, register, subscription, webhook  # noqa: E402,F401


@pytest.fixture
def mail(monkeypatch):
    sent = []
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("CONTACT_EMAIL", "help@ruskimaxxing.test")
    monkeypatch.setattr(m, "send_mail", lambda to, subject, text: sent.append((to, subject, text)))
    return sent


def login(client):
    register(client)
    client.post("/account/login", data={"email": "lifter@example.com", "password": "squat-heavy"})


def paid(client):
    webhook(client, {"id": "e", "object": "event", "type": "checkout.session.completed",
                     "data": {"object": {"client_reference_id": "1", "customer": "cus_1"}}})
    webhook(client, subscription(1))


def test_terms_page(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_NAME", "Iron Eagle LLC")
    monkeypatch.setenv("GOVERNING_STATE", "Texas")
    text = client.get("/terms").text
    for needed in ("renews automatically every year", "until you cancel", "Full refund of any payment within 30 days",
                   "Manage billing / cancel", "30 to 45 days before each renewal", "not medical advice",
                   "Iron Eagle LLC", "laws of Texas", "at least 13"):
        assert needed in text, needed
    assert 'href="/terms"' in client.get("/privacy").text


def test_subscribe_box_shows_renewal_terms(client):
    login(client)
    page = client.get("/account").text
    assert "renews automatically" in page and "until you cancel" in page and 'name="agree"' in page
    assert "Full refund of any payment within 30 days" in page


def test_purchase_confirmation_email(client, mail):
    login(client)
    paid(client)
    to, subject, text = mail[0]
    assert to == "lifter@example.com" and "renewing automatically" in text
    assert "/account" in text and "Manage billing / cancel" in text and "30 days" in text


def test_cancelled_plan_shows_no_renewal(client):
    login(client)
    paid(client)
    assert "Renews automatically on" in client.get("/account").text
    event = subscription(1)
    event["data"]["object"]["cancel_at_period_end"] = True
    webhook(client, event)
    assert "cancelled" in client.get("/account").text


def test_refund_within_30_days(client, mail, monkeypatch):
    login(client)
    paid(client)
    calls = []
    monkeypatch.setattr(m, "stripe_refund_latest", lambda user: calls.append(user.id) or True)
    r = client.post("/account/refund", follow_redirects=False)
    assert r.headers["location"] == "/account?msg=refunded" and calls == [1]
    page = client.get("/account?msg=refunded").text
    assert "Refund issued" in page and "No active plan" in page
    assert any("refund" in subject.lower() for _, subject, _ in mail)


def test_refund_too_late(client, monkeypatch):
    login(client)
    paid(client)
    monkeypatch.setattr(m, "stripe_refund_latest", lambda user: False)
    r = client.post("/account/refund", follow_redirects=False)
    assert r.headers["location"] == "/account?msg=norefund"
    assert "Plan active" in client.get("/account").text
    assert client.post("/account/refund", headers={"Origin": "https://evil.example"}).status_code == 403


def test_stripe_refund_latest_logic(monkeypatch):
    """Against a fake Stripe: refunds a recent charge and cancels the plan; refuses old or refunded charges."""
    import time
    from types import SimpleNamespace as NS
    log = []
    charge = NS(id="ch_1", paid=True, refunded=False, created=time.time() - 5 * 86400)
    fake = NS(api_key=None,
              Charge=NS(list=lambda **k: NS(data=[charge])),
              Refund=NS(create=lambda **k: log.append(("refund", k["charge"]))),
              Subscription=NS(list=lambda **k: NS(data=[NS(id="sub_1", status="active"),
                                                        NS(id="sub_0", status="canceled")]),
                              cancel=lambda sid: log.append(("cancel", sid))))
    monkeypatch.setitem(sys.modules, "stripe", fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    user = NS(stripe_customer="cus_1")
    assert m.stripe_refund_latest(user) and log == [("refund", "ch_1"), ("cancel", "sub_1")]
    log.clear()
    charge.created = time.time() - 31 * 86400
    assert not m.stripe_refund_latest(user) and log == []
    charge.created, charge.refunded = time.time(), True
    assert not m.stripe_refund_latest(user) and log == []


def test_renewal_reminders(client, mail):
    login(client)
    paid(client)
    engine = client.app.state.engine
    with Session(engine) as s:
        user = s.get(m.User, 1)
        renews = user.plan_until
    mail.clear()
    # too early (more than 45 days out): nothing
    assert m.send_renewal_reminders(engine, now=renews - timedelta(days=60)) == 0
    # inside the 30-45 day window: one reminder, never repeated for the same renewal
    assert m.send_renewal_reminders(engine, now=renews - timedelta(days=40)) == 1
    assert m.send_renewal_reminders(engine, now=renews - timedelta(days=35)) == 0
    to, subject, text = mail[0]
    assert "renews" in subject and "$20" in text and "Manage billing / cancel" in text and "30 days" in text
    # cancelled plans don't get reminded
    with Session(engine) as s:
        user = s.get(m.User, 1)
        user.reminder_for, user.cancel_at_period_end = None, True
        s.commit()
    assert m.send_renewal_reminders(engine, now=renews - timedelta(days=40)) == 0
