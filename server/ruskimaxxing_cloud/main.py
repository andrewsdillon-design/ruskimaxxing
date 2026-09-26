"""RuskiMaxxing Cloud: account + backup/sync server for the RuskiMaxxing and
RuskiMaxxing Supertotal apps.

The apps keep working offline on their own local database; when online they push
what changed and pull what other devices changed. The server stores each record
as JSON keyed by (user, edition, uid) and keeps the newest edit ("last write wins").

Configuration (environment variables, see deploy/env.example):
  DATABASE_URL   postgresql+psycopg://user:pass@localhost/ruskimaxxing   (default: local SQLite)
  PUBLIC_URL     https://api.example.com      used in password-reset emails
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM   for password-reset emails
  CONTACT_EMAIL  shown on the privacy and terms pages (refund requests, questions)
  OPERATOR_NAME  your name or business name, shown in the Terms of Service
  GOVERNING_STATE  U.S. state whose law governs the Terms (e.g. Texas)
  STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID   paid backups ($20/year) - see deploy/setup_stripe.py
  STRIPE_PORTAL_CONFIG   optional customer-portal configuration id
  COMPLIMENTARY_EMAILS   comma-separated emails that get free backups (you, friends, testers)

Billing: with STRIPE_SECRET_KEY set, *backing up* needs an active plan. Restoring what is
already saved always works, and nothing is deleted when a plan lapses. Without Stripe
keys the server is free for everyone.

Consumer protections (U.S. automatic-renewal laws - FTC ROSCA, California and other state ARLs):
clear renewal terms and a required consent checkbox before checkout, a confirmation email after
purchase, a reminder email 30-45 days before each yearly renewal (python -m ruskimaxxing_cloud.reminders,
run daily by cron), cancel online at any time, and a full refund of any charge within 30 days.
"""

import hashlib
import html
import json
import os
import secrets
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Cookie, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine,
                        delete, func, inspect, select, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

EDITIONS = ("standard", "supertotal")
KINDS = ("lift", "bodyweight", "bodyfat", "setting")
SESSION_DAYS = 180
WEB_SESSION_DAYS = 30
PLAN_PRICE = "$20/year"
PLAN_PRICE_PLAIN = "$20"
PLAN_GRACE = timedelta(days=3)          # renewals can take a day or two to go through
ACTIVE_STATUSES = ("active", "trialing", "past_due")
COOKIE = "rmx_session"
REFUND_DAYS = 30                        # full refund of any charge (first year or renewal) within 30 days
REMINDER_WINDOW = (30, 45)              # renewal reminder goes out 30-45 days before each yearly renewal
TERMS_UPDATED = "September 26, 2026"
MAX_CHANGES = 5000
ph = PasswordHasher()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(token: str) -> str:
    """Tokens are stored hashed: a leaked database can't be used to log in."""
    return hashlib.sha256(token.encode()).hexdigest()


# ----- database ---------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    stripe_customer: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    plan_status: Mapped[str] = mapped_column(String(30), default="")
    plan_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # renewal date last reminded


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires: Mapped[datetime] = mapped_column(DateTime)


class ResetToken(Base):
    __tablename__ = "reset_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires: Mapped[datetime] = mapped_column(DateTime)


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (UniqueConstraint("user_id", "edition", "uid"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    edition: Mapped[str] = mapped_column(String(20))
    uid: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    updated: Mapped[str] = mapped_column(String(40))     # client timestamp (ISO, UTC) - newest wins
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[str | None] = mapped_column(Text, nullable=True)
    seq: Mapped[int] = mapped_column(Integer, index=True)  # per-user change counter for incremental pulls


def make_engine(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL", "sqlite:///./ruskimaxxing_cloud.db")
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    add_missing_columns(engine)
    return engine


def add_missing_columns(engine) -> None:
    """Tiny forward-only migration: add columns introduced after a table was first created."""
    have = {c["name"] for c in inspect(engine).get_columns("users")}
    wanted = {"stripe_customer": "VARCHAR(100)", "plan_status": "VARCHAR(30) DEFAULT ''",
              "plan_until": "TIMESTAMP", "cancel_at_period_end": "BOOLEAN DEFAULT FALSE",
              "reminder_for": "TIMESTAMP"}
    with engine.begin() as conn:
        for name, decl in wanted.items():
            if name not in have:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {decl}"))


# ----- billing ----------------------------------------------------------------------
def billing_on() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def complimentary(user) -> bool:
    free = {e.strip().lower() for e in os.environ.get("COMPLIMENTARY_EMAILS", "").split(",") if e.strip()}
    return user.email in free


def plan_active(user) -> bool:
    if not billing_on() or complimentary(user):
        return True
    return (user.plan_status in ACTIVE_STATUSES and user.plan_until is not None
            and user.plan_until + PLAN_GRACE > utcnow())


def plan_info(user) -> dict:
    return {"active": plan_active(user), "billing": billing_on(), "complimentary": complimentary(user),
            "status": user.plan_status or "", "until": user.plan_until.date().isoformat() if user.plan_until else None,
            "price": PLAN_PRICE}


def public_url(request: Request | None = None) -> str:
    url = os.environ.get("PUBLIC_URL", "").rstrip("/")
    if not url and request is not None:
        url = str(request.base_url).rstrip("/")
    return url


def stripe_checkout(user, base: str) -> str:
    """Create a Stripe Checkout session for the yearly plan; returns the URL to send the lifter to."""
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    params = {"mode": "subscription", "line_items": [{"price": os.environ["STRIPE_PRICE_ID"], "quantity": 1}],
              "client_reference_id": str(user.id), "subscription_data": {"metadata": {"user_id": str(user.id)}},
              "success_url": f"{base}/account?paid=1", "cancel_url": f"{base}/account",
              "custom_text": {"submit": {"message": RENEWAL_TERMS.format(base=base)}}}
    if user.stripe_customer:
        params["customer"] = user.stripe_customer
    else:
        params["customer_email"] = user.email
    return stripe.checkout.Session.create(**params).url


def stripe_portal(user, base: str) -> str:
    """Stripe's hosted page for cancelling, changing cards and downloading receipts."""
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    params = {"customer": user.stripe_customer, "return_url": f"{base}/account"}
    if os.environ.get("STRIPE_PORTAL_CONFIG"):
        params["configuration"] = os.environ["STRIPE_PORTAL_CONFIG"]
    return stripe.billing_portal.Session.create(**params).url


def stripe_refund_latest(user) -> bool:
    """Refund the latest charge in full if it's within REFUND_DAYS, and end the plan now.

    Returns False (and changes nothing) when there's no charge from the last REFUND_DAYS to refund."""
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    charges = stripe.Charge.list(customer=user.stripe_customer, limit=1).data
    if not charges:
        return False
    charge = charges[0]
    if not charge.paid or charge.refunded or charge.created < time.time() - REFUND_DAYS * 86400:
        return False
    stripe.Refund.create(charge=charge.id)
    for sub in stripe.Subscription.list(customer=user.stripe_customer, status="all", limit=10).data:
        if sub.status not in ("canceled", "incomplete_expired"):
            stripe.Subscription.cancel(sub.id)
    return True


def stripe_event(payload: bytes, signature: str) -> dict:
    """Verify a webhook really came from Stripe (raises ValueError if not)."""
    import stripe
    try:
        stripe.Webhook.construct_event(payload, signature, os.environ["STRIPE_WEBHOOK_SECRET"])
    except stripe.error.SignatureVerificationError as e:
        raise ValueError(str(e)) from e
    # verified - read it as plain JSON (newer stripe SDKs return objects without dict methods)
    return json.loads(payload)


def period_end(sub) -> datetime | None:
    """Subscription period end (older Stripe API versions put it on the subscription, newer on the item)."""
    end = sub.get("current_period_end")
    if not end:
        items = (sub.get("items") or {}).get("data") or []
        end = items[0].get("current_period_end") if items else None
    return datetime.fromtimestamp(end, timezone.utc).replace(tzinfo=None) if end else None


# ----- API models -------------------------------------------------------------------
class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class Password(BaseModel):
    password: str = Field(max_length=200)


class ResetRequest(BaseModel):
    email: str = Field(max_length=320)


class Change(BaseModel):
    uid: str = Field(max_length=200)
    kind: str
    updated: str = Field(max_length=40)
    deleted: bool = False
    data: dict | None = None


class SyncRequest(BaseModel):
    edition: str
    since: int = 0
    changes: list[Change] = []


# ----- app --------------------------------------------------------------------------
def create_app(database_url: str | None = None) -> FastAPI:
    engine = make_engine(database_url)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)
    app = FastAPI(title="RuskiMaxxing Cloud", docs_url=None, redoc_url=None)

    def db():
        with SessionLocal() as s:
            yield s

    def current_user(authorization: str = Header(default=""), s: Session = Depends(db)) -> User:
        token = authorization.removeprefix("Bearer ").strip()
        row = s.get(LoginSession, digest(token)) if token else None
        if not row or row.expires < utcnow():
            raise HTTPException(401, "Please log in again")
        return s.get(User, row.user_id)

    def new_session(s: Session, user: User) -> str:
        token = secrets.token_urlsafe(32)
        s.add(LoginSession(token_hash=digest(token), user_id=user.id, expires=utcnow() + timedelta(days=SESSION_DAYS)))
        return token

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/api/register")
    def register(body: Credentials, s: Session = Depends(db)):
        email = body.email.strip().lower()
        if "@" not in email:
            raise HTTPException(400, "Enter a valid email address")
        if s.scalar(select(User).where(User.email == email)):
            raise HTTPException(409, "That email already has an account - log in instead")
        user = User(email=email, password_hash=ph.hash(body.password))
        s.add(user)
        s.flush()
        token = new_session(s, user)
        s.commit()
        return {"token": token, "email": email, "plan": plan_info(user)}

    @app.post("/api/login")
    def login(body: Credentials, s: Session = Depends(db)):
        user = s.scalar(select(User).where(User.email == body.email.strip().lower()))
        try:
            ok = bool(user) and ph.verify(user.password_hash, body.password)
        except (VerifyMismatchError, InvalidHashError):
            ok = False
        if not ok:
            raise HTTPException(401, "Wrong email or password")
        if ph.check_needs_rehash(user.password_hash):
            user.password_hash = ph.hash(body.password)
        token = new_session(s, user)
        s.commit()
        return {"token": token, "email": user.email, "plan": plan_info(user)}

    @app.post("/api/logout")
    def logout(authorization: str = Header(default=""), s: Session = Depends(db)):
        s.execute(delete(LoginSession).where(LoginSession.token_hash == digest(authorization.removeprefix("Bearer ").strip())))
        s.commit()
        return {"ok": True}

    @app.get("/api/me")
    def me(user: User = Depends(current_user), s: Session = Depends(db)):
        counts = {e: s.scalar(select(func.count()).select_from(Record).where(
            Record.user_id == user.id, Record.edition == e, Record.deleted.is_(False))) for e in EDITIONS}
        return {"email": user.email, "records": counts, "plan": plan_info(user)}

    @app.post("/api/sync")
    def sync(body: SyncRequest, user: User = Depends(current_user), s: Session = Depends(db)):
        if body.edition not in EDITIONS:
            raise HTTPException(400, "Unknown edition")
        if len(body.changes) > MAX_CHANGES:
            raise HTTPException(413, f"Send at most {MAX_CHANGES} changes at a time")
        if body.changes and not plan_active(user):
            # neutral wording on purpose: the apps never advertise the paid plan (the website does)
            raise HTTPException(402, "Cloud backup isn't active for this account. Your saved data can still "
                                     "be restored.")
        seq = s.scalar(select(func.max(Record.seq)).where(Record.user_id == user.id)) or 0
        for c in body.changes:
            if c.kind not in KINDS:
                continue
            rec = s.scalar(select(Record).where(Record.user_id == user.id, Record.edition == body.edition,
                                                Record.uid == c.uid))
            if rec and c.updated <= rec.updated:
                continue  # we already have a newer (or the same) version
            seq += 1
            if not rec:
                rec = Record(user_id=user.id, edition=body.edition, uid=c.uid)
                s.add(rec)
            rec.kind, rec.updated, rec.deleted, rec.seq = c.kind, c.updated, c.deleted, seq
            rec.data = None if c.deleted else json.dumps(c.data)
        s.commit()
        rows = s.scalars(select(Record).where(Record.user_id == user.id, Record.edition == body.edition,
                                              Record.seq > body.since).order_by(Record.seq)).all()
        out = [{"uid": r.uid, "kind": r.kind, "updated": r.updated, "deleted": r.deleted,
                "data": json.loads(r.data) if r.data else None} for r in rows]
        return {"changes": out, "seq": max([body.since] + [r.seq for r in rows]), "plan": plan_info(user)}

    @app.delete("/api/account")
    def delete_account(body: Password, user: User = Depends(current_user), s: Session = Depends(db)):
        try:
            ph.verify(user.password_hash, body.password)
        except (VerifyMismatchError, InvalidHashError):
            raise HTTPException(401, "Wrong password") from None
        for model in (Record, LoginSession, ResetToken):
            s.execute(delete(model).where(model.user_id == user.id))
        s.delete(user)
        s.commit()
        return {"deleted": True}

    # ----- web account page: plan status, subscribe, manage billing --------------------
    def web_user(s: Session, token: str | None):
        row = s.get(LoginSession, digest(token)) if token else None
        return s.get(User, row.user_id) if row and row.expires >= utcnow() else None

    def same_origin(request: Request):
        """Forms only accept posts from this site (plus SameSite cookies) - basic CSRF protection."""
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != public_url(request):
            raise HTTPException(403, "Bad origin")

    @app.get("/account", response_class=HTMLResponse)
    def account(request: Request, paid: int = 0, msg: str = "", error: int = 0, rmx_session: str | None = Cookie(default=None),
                s: Session = Depends(db)):
        user = web_user(s, rmx_session)
        if not user:
            return page("Your RuskiMaxxing account", """
                <p>Log in with the email and password you use in the app.
                (No account yet? Create one in the app under Cloud backup.)</p>
                <form method="post" action="/account/login">
                  <p><label>Email<br><input name="email" type="email" required></label></p>
                  <p><label>Password<br><input name="password" type="password" required></label></p>
                  <p><button>Log in</button></p>
                </form>""")
        info = plan_info(user)
        if info["complimentary"] or not info["billing"]:
            status = "<p><b>Cloud backup is free for your account.</b></p>"
            actions = ""
        elif info["active"]:
            if user.cancel_at_period_end:
                status = (f"<p><b>Plan active - cancelled.</b> It won't renew. Backups stay on until "
                          f"{info['until']}.</p>")
            else:
                status = (f"<p><b>Plan active.</b> Renews automatically on {info['until']} for {PLAN_PRICE_PLAIN} "
                          f"unless you cancel before then.</p>")
            actions = ('<form method="post" action="/account/manage"><button>Manage billing / cancel</button>'
                       '</form>' if user.stripe_customer else "")
        else:
            status = (f"<p><b>No active plan.</b> Backups are paused; your saved data is safe and can still be "
                      f"restored in the app.</p><p>Cloud backup: <b>{PLAN_PRICE}</b>.</p>")
            actions = subscribe_form(public_url(request), error)
            if user.stripe_customer:
                actions += '<form method="post" action="/account/manage"><p><button>Billing history</button></p></form>'
        if info["billing"] and not info["complimentary"] and user.stripe_customer:
            actions += (f'<form method="post" action="/account/refund" onsubmit="return confirm(\'Refund your latest '
                        f'payment in full and end your plan now?\')"><p><button>Request a full refund</button><br>'
                        f'<small>Any payment made in the last {REFUND_DAYS} days, first year or renewal.</small></p>'
                        f'</form>')
        thanks = "<p><b>Thanks! Your payment went through.</b> It can take a minute to show here.</p>" if paid else ""
        notes = {"refunded": f"<p><b>Refund issued.</b> It goes back to your original payment method, usually "
                             f"within 5-10 business days. Your plan has ended; your saved data is still here.</p>",
                 "norefund": f"<p><b>No payment from the last {REFUND_DAYS} days to refund.</b> Questions about "
                             f"a charge? Email {html.escape(contact_email())}.</p>"}
        return page("Your RuskiMaxxing account", f"""
            <p>Signed in as {html.escape(user.email)}</p>{thanks}{notes.get(msg, "")}{status}{actions}
            <form method="post" action="/account/logout"><p><button>Log out</button></p></form>""")

    @app.post("/account/login")
    def account_login(request: Request, email: str = Form(...), password: str = Form(...),
                      s: Session = Depends(db)):
        same_origin(request)
        user = s.scalar(select(User).where(User.email == email.strip().lower()))
        try:
            ok = bool(user) and ph.verify(user.password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            ok = False
        if not ok:
            return HTMLResponse(page("Log in", '<p>Wrong email or password. <a href="/account">Try again</a>.</p>'),
                                status_code=401)
        token = secrets.token_urlsafe(32)
        s.add(LoginSession(token_hash=digest(token), user_id=user.id,
                           expires=utcnow() + timedelta(days=WEB_SESSION_DAYS)))
        s.commit()
        resp = RedirectResponse("/account", status_code=303)
        resp.set_cookie(COOKIE, token, max_age=WEB_SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=public_url(request).startswith("https://"))
        return resp

    @app.post("/account/logout")
    def account_logout(request: Request, rmx_session: str | None = Cookie(default=None), s: Session = Depends(db)):
        same_origin(request)
        if rmx_session:
            s.execute(delete(LoginSession).where(LoginSession.token_hash == digest(rmx_session)))
            s.commit()
        resp = RedirectResponse("/account", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    @app.post("/account/subscribe")
    def account_subscribe(request: Request, agree: str = Form(default=""),
                          rmx_session: str | None = Cookie(default=None), s: Session = Depends(db)):
        same_origin(request)
        user = web_user(s, rmx_session)
        if not user:
            return RedirectResponse("/account", status_code=303)
        if not billing_on() or plan_active(user):
            return RedirectResponse("/account", status_code=303)
        if agree != "yes":  # express consent to the automatic-renewal terms is required before charging
            return RedirectResponse("/account?error=1", status_code=303)
        return RedirectResponse(stripe_checkout(user, public_url(request)), status_code=303)

    @app.post("/account/refund")
    def account_refund(request: Request, rmx_session: str | None = Cookie(default=None), s: Session = Depends(db)):
        same_origin(request)
        user = web_user(s, rmx_session)
        if not user or not user.stripe_customer or not billing_on():
            return RedirectResponse("/account", status_code=303)
        if not stripe_refund_latest(user):
            return RedirectResponse("/account?msg=norefund", status_code=303)
        user.plan_status, user.plan_until, user.cancel_at_period_end = "canceled", utcnow(), False
        s.commit()
        if mail_on():
            send_mail(user.email, "Your RuskiMaxxing Cloud refund",
                      f"We've refunded your latest RuskiMaxxing Cloud Backup payment in full. It goes back to your "
                      f"original payment method, usually within 5-10 business days.\n\nYour plan has ended and "
                      f"won't renew. Your saved data is still there and can be restored in the app.\n\n"
                      f"Questions: {contact_email()}")
        return RedirectResponse("/account?msg=refunded", status_code=303)

    @app.post("/account/manage")
    def account_manage(request: Request, rmx_session: str | None = Cookie(default=None), s: Session = Depends(db)):
        same_origin(request)
        user = web_user(s, rmx_session)
        if not user or not user.stripe_customer or not billing_on():
            return RedirectResponse("/account", status_code=303)
        return RedirectResponse(stripe_portal(user, public_url(request)), status_code=303)

    @app.post("/stripe/webhook")
    async def stripe_webhook(request: Request, stripe_signature: str = Header(default=""),
                             s: Session = Depends(db)):
        payload = await request.body()
        try:
            event = stripe_event(payload, stripe_signature)
        except (ValueError, KeyError):
            raise HTTPException(400, "Bad signature") from None
        kind, obj = event["type"], event["data"]["object"]
        if kind == "checkout.session.completed":
            user = s.get(User, int(obj.get("client_reference_id") or 0))
            if user and obj.get("customer"):
                user.stripe_customer = obj["customer"]
                if mail_on():
                    send_mail(user.email, "Your RuskiMaxxing Cloud Backup plan",
                              PURCHASE_EMAIL.format(base=public_url(request), contact=contact_email(),
                                                    days=REFUND_DAYS))
        elif kind in ("customer.subscription.created", "customer.subscription.updated",
                      "customer.subscription.deleted"):
            user_id = ((obj.get("metadata") or {}).get("user_id"))
            user = s.get(User, int(user_id)) if user_id else None
            if not user and obj.get("customer"):
                user = s.scalar(select(User).where(User.stripe_customer == obj["customer"]))
            if user:
                user.stripe_customer = user.stripe_customer or obj.get("customer")
                user.plan_status = "canceled" if kind.endswith("deleted") else obj.get("status", "")
                user.plan_until = period_end(obj) or user.plan_until
                user.cancel_at_period_end = bool(obj.get("cancel_at_period_end") or obj.get("cancel_at"))
        s.commit()
        return {"received": True}

    # ----- password reset -----------------------------------------------------------
    @app.post("/api/password-reset")
    def password_reset(body: ResetRequest, s: Session = Depends(db)):
        user = s.scalar(select(User).where(User.email == body.email.strip().lower()))
        if user and mail_on():
            token = secrets.token_urlsafe(32)
            s.add(ResetToken(token_hash=digest(token), user_id=user.id, expires=utcnow() + timedelta(hours=1)))
            s.commit()
            link = f"{os.environ.get('PUBLIC_URL', '').rstrip('/')}/reset?token={token}"
            send_mail(user.email, "Reset your RuskiMaxxing password",
                      f"Reset your password within 1 hour:\n\n{link}\n\nIf you didn't ask for this, ignore it.")
        # same answer either way, so this can't be used to discover who has an account
        return {"ok": True, "message": "If that email has an account, a reset link is on its way."}

    @app.get("/reset", response_class=HTMLResponse)
    def reset_form(token: str = ""):
        return page("Reset password", f"""
            <form method="post" action="/reset">
              <input type="hidden" name="token" value="{html.escape(token)}">
              <label>New password (8+ characters)<br><input type="password" name="password" minlength="8" required></label>
              <p><button>Set new password</button></p>
            </form>""")

    @app.post("/reset", response_class=HTMLResponse)
    def reset_submit(token: str = Form(...), password: str = Form(...), s: Session = Depends(db)):
        row = s.get(ResetToken, digest(token))
        if not row or row.expires < utcnow():
            return page("Link expired", "<p>This reset link is invalid or expired. Request a new one in the app.</p>")
        if len(password) < 8:
            return page("Too short", "<p>Use at least 8 characters. Go back and try again.</p>")
        user = s.get(User, row.user_id)
        user.password_hash = ph.hash(password)
        s.execute(delete(ResetToken).where(ResetToken.user_id == user.id))
        s.execute(delete(LoginSession).where(LoginSession.user_id == user.id))  # log out everywhere
        s.commit()
        return page("Password changed", "<p>Done. Log in again in the app with your new password.</p>")

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        contact = html.escape(contact_email())
        return page("Privacy policy", PRIVACY.format(contact=contact, host=html.escape(request.url.hostname or "")))

    @app.get("/terms", response_class=HTMLResponse)
    def terms(request: Request):
        return page("Terms of Service", terms_html(public_url(request)))

    app.state.engine = engine
    return app


def contact_email() -> str:
    return os.environ.get("CONTACT_EMAIL", "") or "the site owner"


def mail_on() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def send_renewal_reminders(engine, now: datetime | None = None) -> int:
    """Email everyone whose plan renews in 30-45 days (once per renewal). Run daily; returns emails sent.

    Several U.S. states require a notice like this before an automatic yearly renewal."""
    now = now or utcnow()
    early, late = now + timedelta(days=REMINDER_WINDOW[1]), now
    sent = 0
    with Session(engine) as s:
        users = s.scalars(select(User).where(User.plan_status == "active", User.plan_until.is_not(None),
                                             User.plan_until <= early, User.plan_until > late)).all()
        for user in users:
            if user.cancel_at_period_end or complimentary(user) or user.reminder_for == user.plan_until:
                continue
            send_mail(user.email, "Your RuskiMaxxing Cloud Backup plan renews soon",
                      REMINDER_EMAIL.format(date=user.plan_until.strftime("%B %d, %Y").replace(" 0", " "),
                                            price=PLAN_PRICE_PLAIN, base=public_url(), contact=contact_email(),
                                            days=REFUND_DAYS))
            user.reminder_for = user.plan_until
            s.commit()
            sent += 1
    return sent


def subscribe_form(base: str, error: int = 0) -> str:
    """Subscribe button with the renewal terms right next to it and a required consent checkbox."""
    warn = "<p style='color:#8B1A1A'><b>Please tick the box to agree to the renewal terms.</b></p>" if error else ""
    return f"""<form method="post" action="/account/subscribe">
      <div style="border:2px solid #4A1942;padding:10px 14px;background:#F6EEDC">
      <p><b>Cloud Backup: {PLAN_PRICE_PLAIN} per year, renews automatically.</b></p>
      <ul><li>You're charged {PLAN_PRICE_PLAIN} (plus any sales tax) today, then {PLAN_PRICE_PLAIN} every year on
      the same date <b>until you cancel</b>.</li>
      <li>We email you 30-45 days before each renewal.</li>
      <li>Cancel anytime on this page (Manage billing / cancel). Backups stay on until the end of the year you paid for.</li>
      <li><b>Full refund of any payment within {REFUND_DAYS} days</b>, first year or renewal. No questions asked.</li></ul>
      {warn}<p><label><input type="checkbox" name="agree" value="yes" required style="width:auto">
      I agree to the automatic yearly renewal and the <a href="/terms">Terms of Service</a>.</label></p>
      <p><button>Subscribe - {PLAN_PRICE}</button></p></div></form>"""


def terms_html(base: str) -> str:
    operator = html.escape(os.environ.get("OPERATOR_NAME", "") or "the operator of this site")
    state = html.escape(os.environ.get("GOVERNING_STATE", "") or "the U.S. state where the operator is located")
    return TERMS.format(operator=operator, state=state, contact=html.escape(contact_email()), base=base,
                        price=PLAN_PRICE_PLAIN, days=REFUND_DAYS, updated=TERMS_UPDATED)


def send_mail(to: str, subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["From"] = os.environ.get("MAIL_FROM", os.environ.get("SMTP_USER", ""))
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(text)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=20) as smtp:
        smtp.starttls()
        if os.environ.get("SMTP_USER"):
            smtp.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        smtp.send_message(msg)


def page(title: str, body: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} - RuskiMaxxing</title>
<style>body{{font-family:system-ui,sans-serif;background:#EDE3CF;color:#2B1B24;max-width:640px;margin:40px auto;
padding:0 16px}}h1{{color:#4A1942}}button{{background:#4A1942;color:#F2D675;border:0;padding:10px 18px;
font-weight:bold}}input{{padding:8px;width:100%;max-width:320px}}</style></head>
<body><h1>{title}</h1>{body}
<p style="margin-top:40px;font-size:90%"><a href="/account">Account</a> &middot; <a href="/terms">Terms</a>
&middot; <a href="/privacy">Privacy</a></p></body></html>"""


PRIVACY = """
<p>RuskiMaxxing Cloud ({host}) stores a backup of the training data you choose to sync from the
RuskiMaxxing apps so you can restore it on another device. The apps are free; cloud backup is a paid
yearly plan. Payments are handled by Stripe - we never see or store your card number.</p>
<h2>What we store</h2>
<ul><li>Your email address and a one-way hash of your password (never the password itself).</li>
<li>Your Stripe customer id and plan status (active / ended and the renewal date).</li>
<li>Your training log (sets, weights, reps, RPE, notes), bodyweight, body fat measurements and program settings
such as height and start date.</li></ul>
<h2>How we use it</h2>
<ul><li>To back up and restore your data, and to run your account and plan.</li>
<li>To improve the training programs, including building future years (such as Year 2). For this we only look at
training results combined across many users and stripped of anything that identifies you: never your email,
and never one person's log on its own.</li></ul>
<h2>What we don't do</h2>
<ul><li>We don't sell or share your data, show ads, or use trackers.</li>
<li>We don't publish or share anyone's individual data, including in program research.</li></ul>
<h2>Your control</h2>
<ul><li>Delete your account and all synced data at any time from the app (Setup / Start - Cloud backup -
Delete account). Deletion is immediate and permanent.</li>
<li>Your data also stays on your own device; the app works without an account.</li>
<li>If your plan ends, backups pause but nothing is deleted - you can still restore, or delete it yourself.</li></ul>
<p>See also the <a href="/terms">Terms of Service</a>. Questions: {contact}.</p>
"""

TERMS = """
<p><i>Last updated {updated}</i></p>
<p>These Terms cover the RuskiMaxxing Cloud service at {base} ("the Service"), run by {operator} ("we", "us").
The RuskiMaxxing apps and spreadsheets are free. Accounts are free. The only paid part is the optional
<b>Cloud Backup</b> plan described below. The Service is offered to people in the United States. By creating an
account or subscribing you agree to these Terms and to our <a href="/privacy">Privacy Policy</a>.</p>

<h2>1. Who can use it</h2>
<p>You must be at least 13 years old. If you're under 18, a parent or guardian must agree to these Terms for you
and approve any purchase. We don't knowingly collect data from children under 13; if you believe we have, email
{contact} and we'll delete it.</p>

<h2>2. Training and health</h2>
<p>RuskiMaxxing is general strength-training information, <b>not medical advice</b>. Lifting, maximal testing and
plyometrics carry a real risk of injury. Check with a doctor before starting, especially if you have any medical
condition or injury. Use proper technique, spotters and safety equipment, and stop if you feel pain, dizziness or
chest discomfort. You train at your own risk and are responsible for your own health decisions.</p>

<h2>3. Your account</h2>
<p>Keep your password private; you're responsible for activity on your account. Use a real email address you
check: it's how you reset your password and how we send billing notices.</p>

<h2>4. Cloud Backup plan: price and automatic renewal</h2>
<ul>
<li><b>Price:</b> {price} per year, plus any sales tax that applies where you live.</li>
<li><b>Automatic renewal:</b> your plan <b>renews automatically every year</b> on the date you subscribed, and we
charge the payment method on file {price} (plus tax) each year <b>until you cancel</b>. By subscribing, you
authorize these recurring yearly charges.</li>
<li><b>No free trial.</b> You're charged when you subscribe.</li>
<li><b>Reminder:</b> we email you 30 to 45 days before each renewal with the date, the amount and how to cancel.</li>
<li><b>Price changes:</b> we'll email you at least 30 days before a new price applies to your renewal, so you can
cancel first.</li>
<li>Payments are processed by Stripe. We never see or store your full card number.</li>
</ul>

<h2>5. Cancel anytime, online</h2>
<p>Log in at <a href="/account">{base}/account</a> and choose <b>Manage billing / cancel</b>. No phone call, no
form to mail. You can also email {contact}. Cancelling stops all future renewals. Your backups stay on until the
end of the year you've already paid for, and then pause.</p>

<h2>6. Refunds: 30-day money-back guarantee</h2>
<ul>
<li><b>Full refund of any payment within {days} days</b> of that payment: your first payment <i>or</i> any
yearly renewal. No reason needed.</li>
<li>To get one, use <b>Request a full refund</b> at <a href="/account">{base}/account</a> (instant), or email
{contact} from your account's email address.</li>
<li>Refunds go back to the original payment method, usually within 5-10 business days depending on your bank.
When a payment is refunded, that plan year ends and the plan won't renew.</li>
<li>After {days} days, payments aren't refundable and unused time isn't prorated, except: (a) if we shut down the
Service, or close your account when you haven't broken these Terms, we'll refund the unused part of your year; and
(b) any refund the law requires.</li>
<li>If you think you were charged by mistake, email {contact} and we'll fix it.</li>
</ul>

<h2>7. When a plan ends</h2>
<p>Backups pause, but <b>nothing is deleted</b>: you can still restore your saved data in the app at any time. If
we ever decide to remove data from accounts that have been inactive for a long time, we'll email you at least 60
days first. You can delete your account and all your data yourself at any time in the app (Cloud backup &rarr;
Delete account).</p>

<h2>8. Your data</h2>
<p>Your training data is yours. You let us store and process it only to run the Service, as described in the
<a href="/privacy">Privacy Policy</a> (including the combined, de-identified use it explains). We don't sell it.</p>

<h2>9. Acceptable use</h2>
<p>Don't access other people's accounts, try to break or overload the Service, use it to store anything other than
your own training data, or use it for anything illegal. We may suspend accounts that do.</p>

<h2>10. Availability and backups</h2>
<p>We work to keep the Service running and back up its database every night, but it may sometimes be down for
maintenance or problems outside our control. The apps keep a full copy of your data on your device, so you can
keep training while offline.</p>

<h2>11. Open-source software</h2>
<p>The RuskiMaxxing apps and this server's code are free, open-source software under the MIT License. These Terms
cover the hosted Service we run, not your use of the code. The RuskiMaxxing name and eagle logo aren't licensed
for others to use as their own brand.</p>

<h2>12. Disclaimer</h2>
<p>To the extent the law allows, the Service is provided "as is" and "as available", without warranties of any
kind, including merchantability, fitness for a particular purpose and non-infringement.</p>

<h2>13. Limit of liability</h2>
<p>To the extent the law allows, we aren't liable for indirect, incidental, special or consequential damages,
or for lost data or profits, and our total liability for any claim about the Service is limited to the amount
you paid us in the 12 months before the claim. Some states don't allow some of these limits, so they may not
apply to you.</p>

<h2>14. Ending the agreement</h2>
<p>You can stop using the Service and delete your account at any time. We may suspend or close accounts that
break these Terms. If we close your account without you having broken them, we'll refund the unused part of your
plan year.</p>

<h2>15. Changes to these Terms</h2>
<p>If we make a material change, we'll email account holders at least 30 days before it takes effect and update
the date above. If you don't agree, you can cancel, and the 30-day refund in section 6 still applies to your
latest payment.</p>

<h2>16. Law and disputes</h2>
<p>These Terms are governed by the laws of {state} and applicable U.S. federal law. Please email {contact} first
so we can try to sort out any problem informally. Either of us may bring a claim in small-claims court if it
qualifies. Nothing in these Terms takes away rights you have under consumer-protection laws that can't be waived.</p>

<h2>17. Contact</h2>
<p>{contact}</p>
"""

RENEWAL_TERMS = ("Your plan renews automatically every year at $20 until you cancel. Cancel anytime at "
                 "{base}/account. Full refund of any payment within 30 days.")

PURCHASE_EMAIL = """Thanks for subscribing to RuskiMaxxing Cloud Backup.

Your plan: $20 per year (plus any sales tax), renewing automatically every year on the date you
subscribed until you cancel. We'll email you 30-45 days before each renewal.

How to cancel: log in at {base}/account and choose "Manage billing / cancel". Cancelling stops
future renewals; backups stay on until the end of the year you've paid for.

Refunds: you can get a full refund of any payment within {days} days of that payment, no questions
asked. Use "Request a full refund" at {base}/account or email {contact}.

Terms of Service: {base}/terms
"""

REMINDER_EMAIL = """Your RuskiMaxxing Cloud Backup plan renews automatically on {date} for {price}
(plus any sales tax) on the card you have on file.

Nothing to do if you want to keep backing up.

To cancel before then: log in at {base}/account and choose "Manage billing / cancel". Your backups stay
on until {date} and your saved data is never deleted when a plan ends.

If you forget and are charged, you can still get a full refund within {days} days of the renewal:
"Request a full refund" at {base}/account, or email {contact}.

Terms of Service: {base}/terms
"""

app = create_app() if os.environ.get("RUSKIMAXXING_CLOUD_AUTOSTART", "1") == "1" else None
