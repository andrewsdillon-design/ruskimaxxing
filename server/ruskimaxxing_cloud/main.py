"""RuskiMaxxing Cloud: account + backup/sync server for the RuskiMaxxing and
RuskiMaxxing Supertotal apps.

The apps keep working offline on their own local database; when online they push
what changed and pull what other devices changed. The server stores each record
as JSON keyed by (user, edition, uid) and keeps the newest edit ("last write wins").

Configuration (environment variables, see deploy/env.example):
  DATABASE_URL   postgresql+psycopg://user:pass@localhost/ruskimaxxing   (default: local SQLite)
  PUBLIC_URL     https://api.example.com      used in password-reset emails
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM   for password-reset emails
  CONTACT_EMAIL  shown on the privacy page
  STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID   paid backups ($20/year) - see deploy/setup_stripe.py
  STRIPE_PORTAL_CONFIG   optional customer-portal configuration id
  COMPLIMENTARY_EMAILS   comma-separated emails that get free backups (you, friends, testers)

Billing: with STRIPE_SECRET_KEY set, *backing up* needs an active plan. Restoring what is
already saved always works, and nothing is deleted when a plan lapses. Without Stripe
keys the server is free for everyone.
"""

import hashlib
import html
import json
import os
import secrets
import smtplib
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
PLAN_GRACE = timedelta(days=3)          # renewals can take a day or two to go through
ACTIVE_STATUSES = ("active", "trialing", "past_due")
COOKIE = "rmx_session"
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
              "plan_until": "TIMESTAMP"}
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
              "success_url": f"{base}/account?paid=1", "cancel_url": f"{base}/account"}
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
    def account(request: Request, paid: int = 0, rmx_session: str | None = Cookie(default=None),
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
            status = f"<p><b>Plan active</b> - renews or ends {info['until']}.</p>"
            actions = ('<form method="post" action="/account/manage"><button>Manage billing / cancel</button>'
                       '</form>' if user.stripe_customer else "")
        else:
            status = (f"<p><b>No active plan.</b> Backups are paused; your saved data is safe and can still be "
                      f"restored in the app.</p><p>Cloud backup: <b>{PLAN_PRICE}</b>.</p>")
            actions = f'<form method="post" action="/account/subscribe"><button>Subscribe - {PLAN_PRICE}</button></form>'
            if user.stripe_customer:
                actions += '<form method="post" action="/account/manage"><p><button>Billing history</button></p></form>'
        thanks = "<p><b>Thanks! Your payment went through.</b> It can take a minute to show here.</p>" if paid else ""
        return page("Your RuskiMaxxing account", f"""
            <p>Signed in as {html.escape(user.email)}</p>{thanks}{status}{actions}
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
    def account_subscribe(request: Request, rmx_session: str | None = Cookie(default=None),
                          s: Session = Depends(db)):
        same_origin(request)
        user = web_user(s, rmx_session)
        if not user:
            return RedirectResponse("/account", status_code=303)
        if not billing_on() or plan_active(user):
            return RedirectResponse("/account", status_code=303)
        return RedirectResponse(stripe_checkout(user, public_url(request)), status_code=303)

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
        s.commit()
        return {"received": True}

    # ----- password reset -----------------------------------------------------------
    @app.post("/api/password-reset")
    def password_reset(body: ResetRequest, s: Session = Depends(db)):
        user = s.scalar(select(User).where(User.email == body.email.strip().lower()))
        if user and os.environ.get("SMTP_HOST"):
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
        contact = html.escape(os.environ.get("CONTACT_EMAIL", "the site owner"))
        return page("Privacy policy", PRIVACY.format(contact=contact, host=html.escape(request.url.hostname or "")))

    app.state.engine = engine
    return app


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
<body><h1>{title}</h1>{body}</body></html>"""


PRIVACY = """
<p><b>Review and edit this page before launch - it is a starting template, not legal advice.</b></p>
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
<p>Questions: {contact}.</p>
"""

app = create_app() if os.environ.get("RUSKIMAXXING_CLOUD_AUTOSTART", "1") == "1" else None
