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
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine,
                        delete, func, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

EDITIONS = ("standard", "supertotal")
KINDS = ("lift", "bodyweight", "bodyfat", "setting")
SESSION_DAYS = 180
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
    return engine


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
        return {"token": token, "email": email}

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
        return {"token": token, "email": user.email}

    @app.post("/api/logout")
    def logout(authorization: str = Header(default=""), s: Session = Depends(db)):
        s.execute(delete(LoginSession).where(LoginSession.token_hash == digest(authorization.removeprefix("Bearer ").strip())))
        s.commit()
        return {"ok": True}

    @app.get("/api/me")
    def me(user: User = Depends(current_user), s: Session = Depends(db)):
        counts = {e: s.scalar(select(func.count()).select_from(Record).where(
            Record.user_id == user.id, Record.edition == e, Record.deleted.is_(False))) for e in EDITIONS}
        return {"email": user.email, "records": counts}

    @app.post("/api/sync")
    def sync(body: SyncRequest, user: User = Depends(current_user), s: Session = Depends(db)):
        if body.edition not in EDITIONS:
            raise HTTPException(400, "Unknown edition")
        if len(body.changes) > MAX_CHANGES:
            raise HTTPException(413, f"Send at most {MAX_CHANGES} changes at a time")
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
        return {"changes": out, "seq": max([body.since] + [r.seq for r in rows])}

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
RuskiMaxxing apps so you can restore it on another device.</p>
<h2>What we store</h2>
<ul><li>Your email address and a one-way hash of your password (never the password itself).</li>
<li>Your training log (sets, weights, reps, RPE, notes), bodyweight, body fat measurements and program settings
such as height and start date.</li></ul>
<h2>What we don't do</h2>
<ul><li>We don't sell or share your data, show ads, or use trackers.</li></ul>
<h2>Your control</h2>
<ul><li>Delete your account and all synced data at any time from the app (Setup / Start - Cloud backup -
Delete account). Deletion is immediate and permanent.</li>
<li>Your data also stays on your own device; the app works without an account.</li></ul>
<p>Questions: {contact}.</p>
"""

app = create_app() if os.environ.get("RUSKIMAXXING_CLOUD_AUTOSTART", "1") == "1" else None
