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
                       payment_intent="pi_1", event_type="checkout.session.completed", payment_status="paid"):
    return {"id": session_id, "object": "event", "type": event_type,
           "data": {"object": {"id": session_id, "object": "checkout.session", "mode": "payment",
                               "payment_status": payment_status,
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


def test_webhook_unpaid_checkout_grants_nothing_until_async_payment_succeeds(client, app):
    """checkout.session.completed with payment_status "unpaid" (an async payment method still pending) must
    not grant the program year or consent. Only checkout.session.async_payment_succeeded (same session,
    now paid) grants it - once."""
    cookies = register_and_login(client)
    with m.Session(app.state.engine) as s:
        user_id = s.scalar(select(m.User.id).where(m.User.email == "lifter@example.com"))

    r = webhook(client, program_year_event(user_id, 2, payment_status="unpaid"))
    assert r.status_code == 200
    with m.Session(app.state.engine) as s:
        assert s.scalar(select(m.ProgramPurchase).where(m.ProgramPurchase.user_id == user_id)) is None
        user = s.get(m.User, user_id)
        assert user.coaching_consent_at is None

    r = webhook(client, program_year_event(user_id, 2, event_type="checkout.session.async_payment_succeeded"))
    assert r.status_code == 200
    with m.Session(app.state.engine) as s:
        purchases = s.scalars(select(m.ProgramPurchase).where(m.ProgramPurchase.user_id == user_id)).all()
        assert len(purchases) == 1 and purchases[0].year == 2
        user = s.get(m.User, user_id)
        assert user.coaching_consent_at is not None

    # a duplicate delivery of the async-succeeded event (or a replayed completed event) must not double-grant
    webhook(client, program_year_event(user_id, 2, event_type="checkout.session.async_payment_succeeded"))
    webhook(client, program_year_event(user_id, 2, payment_status="paid"))
    with m.Session(app.state.engine) as s:
        purchases = s.scalars(select(m.ProgramPurchase).where(m.ProgramPurchase.user_id == user_id)).all()
        assert len(purchases) == 1


def test_webhook_async_payment_failed_grants_nothing(client, app):
    cookies = register_and_login(client)
    with m.Session(app.state.engine) as s:
        user_id = s.scalar(select(m.User.id).where(m.User.email == "lifter@example.com"))

    webhook(client, program_year_event(user_id, 2, payment_status="unpaid"))
    r = webhook(client, program_year_event(user_id, 2, event_type="checkout.session.async_payment_failed",
                                           payment_status="unpaid"))
    assert r.status_code == 200
    with m.Session(app.state.engine) as s:
        assert s.scalar(select(m.ProgramPurchase).where(m.ProgramPurchase.user_id == user_id)) is None
        user = s.get(m.User, user_id)
        assert user.coaching_consent_at is None


def test_subscription_checkout_completed_still_works_without_payment_status(client, app):
    """The subscription flow's checkout.session.completed payload has no payment_status/mode=program_year -
    it must keep working exactly as before (see test_billing.py::test_webhook_activates_and_lapses_plan)."""
    cookies = register_and_login(client)
    with m.Session(app.state.engine) as s:
        user_id = s.scalar(select(m.User.id).where(m.User.email == "lifter@example.com"))
    r = webhook(client, {"id": "evt_sub", "object": "event", "type": "checkout.session.completed",
                         "data": {"object": {"client_reference_id": str(user_id), "customer": "cus_sub"}}})
    assert r.status_code == 200
    with m.Session(app.state.engine) as s:
        user = s.get(m.User, user_id)
        assert user.stripe_customer == "cus_sub"


def test_concurrent_duplicate_webhook_delivery_is_idempotent_via_db_constraint(client, app, monkeypatch):
    """Simulate two deliveries racing past the in-code existence check at the same time: the DB unique
    constraint on stripe_session_id must stop the second insert from creating a duplicate row, and the code
    must catch that IntegrityError and treat it as "already recorded" rather than raising."""
    cookies = register_and_login(client)
    with m.Session(app.state.engine) as s:
        user_id = s.scalar(select(m.User.id).where(m.User.email == "lifter@example.com"))
    obj = program_year_event(user_id, 2)["data"]["object"]

    with m.Session(app.state.engine) as s:
        m.handle_program_year_checkout(s, obj)
        s.commit()

    # force the pre-insert existence check to miss, as if a concurrent request's row wasn't visible yet -
    # the only thing left to prevent a duplicate is the DB unique constraint + the IntegrityError handling
    orig_scalar = m.Session.scalar

    def racy_scalar(self, stmt, *a, **kw):
        if "program_purchases" in str(stmt).lower():
            return None
        return orig_scalar(self, stmt, *a, **kw)

    monkeypatch.setattr(m.Session, "scalar", racy_scalar)
    with m.Session(app.state.engine) as s:
        m.handle_program_year_checkout(s, obj)  # must not raise - the IntegrityError is caught internally
    monkeypatch.undo()

    with m.Session(app.state.engine) as s:
        purchases = s.scalars(select(m.ProgramPurchase).where(m.ProgramPurchase.user_id == user_id)).all()
        assert len(purchases) == 1


def test_setup_stripe_updates_enabled_events_on_existing_webhook(monkeypatch):
    """setup_stripe.py must update (not just create) a pre-existing webhook's enabled_events when the event
    list this server sends has changed since the webhook was first set up."""
    import importlib.util
    from types import SimpleNamespace as NS
    spec = importlib.util.spec_from_file_location("setup_stripe", Path(__file__).parent.parent / "deploy" /
                                                  "setup_stripe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    hook = NS(id="we_old", url="https://api.x.com/stripe/webhook",
             enabled_events=["checkout.session.completed", "customer.subscription.created",
                             "customer.subscription.updated", "customer.subscription.deleted"])
    modify_calls = []

    def modify(id, **kw):
        modify_calls.append((id, kw))
        hook.enabled_events = kw["enabled_events"]
        return hook

    fake = NS(Price=NS(list=lambda **kw: NS(data=[NS(id="price_1", unit_amount=2000)])),
             Product=NS(create=lambda **kw: NS(id="prod_1")),
             WebhookEndpoint=NS(list=lambda **kw: NS(data=[hook]), create=lambda **kw: (_ for _ in ()).throw(
                 AssertionError("should not create a new webhook when one already exists")), modify=modify),
             billing_portal=NS(Configuration=NS(list=lambda **kw: NS(data=[NS(id="bpc_1")]))))

    env = mod.setup(fake, "https://api.x.com")
    assert modify_calls and modify_calls[0][0] == "we_old"
    assert set(modify_calls[0][1]["enabled_events"]) == set(mod.EVENTS)
    assert "STRIPE_WEBHOOK_SECRET" not in env  # secret unchanged - only enabled_events was updated

    # idempotent: running it again with events now matching must not call modify again
    modify_calls.clear()
    mod.setup(fake, "https://api.x.com")
    assert modify_calls == []


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


def test_setup_stripe_creates_one_price_per_program_year(tmp_path, monkeypatch):
    """setup_stripe.py creates a distinct one-time price per configured program year, and reuses them."""
    import importlib.util
    from types import SimpleNamespace as NS
    monkeypatch.setenv("PROGRAM_YEAR_PRICES", "2:19900,3:29900")
    spec = importlib.util.spec_from_file_location("setup_stripe", Path(__file__).parent.parent / "deploy" /
                                                  "setup_stripe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    prices_by_lookup_key: dict[str, object] = {}
    counter = {"n": 0}

    class PriceAPI:
        def list(self, lookup_keys=None, **kw):
            key = (lookup_keys or [None])[0]
            existing = prices_by_lookup_key.get(key)
            return NS(data=[existing] if existing else [])

        def create(self, **kw):
            counter["n"] += 1
            price = NS(id=f"price_{counter['n']}", **kw)
            prices_by_lookup_key[kw.get("lookup_key")] = price
            return price

    fake = NS(Price=PriceAPI(), Product=NS(create=lambda **kw: NS(id=f"prod_{counter['n']}")),
             WebhookEndpoint=NS(list=lambda **kw: NS(data=[]),
                                create=lambda **kw: NS(id="we_1", secret="whsec_1", url=kw["url"])),
             billing_portal=NS(Configuration=NS(list=lambda **kw: NS(data=[]), create=lambda **kw: NS(id="bpc_1"))))

    mod.setup(fake, "https://api.x.com")
    assert "ruskimaxxing_cloud_yearly" in prices_by_lookup_key
    assert "ruskimaxxing_program_year2" in prices_by_lookup_key
    assert "ruskimaxxing_program_year3" in prices_by_lookup_key
    assert prices_by_lookup_key["ruskimaxxing_program_year2"].unit_amount == 19900
    assert prices_by_lookup_key["ruskimaxxing_program_year3"].unit_amount == 29900
    assert "recurring" not in prices_by_lookup_key["ruskimaxxing_program_year2"].__dict__  # one-time, not subscription

    made_after_first_run = dict(prices_by_lookup_key)
    mod.setup(fake, "https://api.x.com")  # second run: everything already exists, nothing new created
    assert prices_by_lookup_key == made_after_first_run


# ----- the real refund helper against a fake Stripe (current API shape: latest_charge, non-dict objects) ---------
class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fake_stripe(monkeypatch, intent_status="succeeded", paid=True, refunded=False, latest="ch_1"):
    import stripe
    calls = []
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve",
                        staticmethod(lambda pi: _Obj(status=intent_status, latest_charge=latest)))
    monkeypatch.setattr(stripe.Charge, "retrieve", staticmethod(lambda cid: _Obj(id=cid, paid=paid, refunded=refunded)))
    monkeypatch.setattr(stripe.Refund, "create", staticmethod(lambda **kw: calls.append(kw)))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    return calls


def test_refund_purchase_uses_latest_charge(monkeypatch):
    calls = _fake_stripe(monkeypatch)
    assert m.stripe_refund_purchase(_Obj(stripe_payment_intent="pi_1")) is True
    assert calls == [{"payment_intent": "pi_1"}]


def test_refund_purchase_skips_unpaid_refunded_or_missing(monkeypatch):
    for kw in ({"intent_status": "processing"}, {"refunded": True}, {"paid": False}, {"latest": None}):
        calls = _fake_stripe(monkeypatch, **kw)
        assert m.stripe_refund_purchase(_Obj(stripe_payment_intent="pi_1")) is False
        assert calls == []
    assert m.stripe_refund_purchase(_Obj(stripe_payment_intent=None)) is False
