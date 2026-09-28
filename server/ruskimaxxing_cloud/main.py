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
import io
import json
import logging
import os
import secrets
import smtplib
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Cookie, Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine,
                        delete, func, inspect, select, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .streaks import compute_streak

logger = logging.getLogger(__name__)

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
TERMS_UPDATED = "September 28, 2026"
MAX_CHANGES = 5000
LINK_MINUTES = 15
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I
APP_SCHEMES = {"standard": "ruskimaxxing", "supertotal": "ruskimaxxingsupertotal"}  # phone apps' return links
ph = PasswordHasher()

# ----- program years (one-time purchases, website-only) --------------------------------
CONSENT_VERSION = "2026-09-28"        # bumped whenever the coaching-consent language changes
PROGRAM_YEAR_LOOKUP_PREFIX = "ruskimaxxing_program_year"   # + N -> Stripe Price lookup_key
STREAK_MAX_UPLOAD_BYTES = 8 * 1024 * 1024
STREAK_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}
STREAK_EXIF_TOLERANCE = timedelta(hours=2)
STREAK_PHASH_MIN_DISTANCE = 10        # Hamming distance: below this, a photo is treated as a duplicate
CALL_PRICE_PLAIN = "$99/hour"         # Phase 3 - not purchasable yet, shown as context for the discount


def program_year_prices() -> dict[int, int]:
    """Year -> price in cents, from PROGRAM_YEAR_PRICES (e.g. "2:19900,3:29900"). Years missing from the map
    aren't purchasable yet ("coming later")."""
    raw = os.environ.get("PROGRAM_YEAR_PRICES", "2:19900,3:29900")
    out: dict[int, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        year, cents = part.split(":")
        out[int(year)] = int(cents)
    return out


def format_price(cents: int) -> str:
    return f"${cents / 100:,.0f}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


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
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)  # replay protection
    coaching_consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    coaching_consent_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comp_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # admin-granted free access
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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


class AppLink(Base):
    """A pending "sign in with your browser" request from an app (like the TV-style device login)."""
    __tablename__ = "app_links"
    device_hash: Mapped[str] = mapped_column(String(64), primary_key=True)   # secret the app polls with (hashed)
    user_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # shown in the app and the page
    edition: Mapped[str] = mapped_column(String(20))
    phone: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
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


class AdminSession(Base):
    """A logged-in admin's browser session (separate cookie/table from the lifter-facing sessions)."""
    __tablename__ = "admin_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    """Every admin action that touches a user's account or data. Never store secrets/passwords/codes here."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    admin_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    target_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ProgramPurchase(Base):
    """A one-time purchase of a program year. Uniqueness of (user, year) while not refunded, and idempotency
    on stripe_session_id, are enforced in code (see owned_years / the webhook handler) rather than as DB
    constraints, since a refunded row must be able to coexist with a later repurchase of the same year."""
    __tablename__ = "program_purchases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(10), default="usd")
    stripe_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    stripe_payment_intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ConsentEvent(Base):
    """Every grant/withdrawal of coaching consent - the only way the operator gets individual data access."""
    __tablename__ = "consent_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    action: Mapped[str] = mapped_column(String(10))       # "grant" | "withdraw"
    version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(String(10))       # "purchase" | "account"


class StreakCheck(Base):
    """One accepted training-day photo check. The photo itself is never stored - only the day, when we got
    it, and a perceptual hash used to reject a duplicate photo of an earlier session."""
    __tablename__ = "streak_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    phash: Mapped[str] = mapped_column(String(16))


def make_engine(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL", "sqlite:///./ruskimaxxing_cloud.db")
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "postgresql":
        # several uvicorn workers start at once: let only one create tables / add columns at a time
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(815100)"))
            Base.metadata.create_all(conn)
            add_missing_columns(conn)
    else:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            add_missing_columns(conn)
    return engine


def add_missing_columns(conn) -> None:
    """Tiny forward-only migration: add columns introduced after a table was first created."""
    have = {c["name"] for c in inspect(conn).get_columns("users")}
    wanted = {"stripe_customer": "VARCHAR(100)", "plan_status": "VARCHAR(30) DEFAULT ''",
              "plan_until": "TIMESTAMP", "cancel_at_period_end": "BOOLEAN DEFAULT FALSE",
              "reminder_for": "TIMESTAMP", "is_admin": "BOOLEAN DEFAULT FALSE", "totp_secret": "VARCHAR(64)",
              "totp_last_step": "INTEGER", "coaching_consent_at": "TIMESTAMP",
              "coaching_consent_version": "VARCHAR(20)", "comp_until": "TIMESTAMP", "last_sync_at": "TIMESTAMP"}
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
    if user.comp_until is not None and user.comp_until > utcnow():
        return True  # admin-granted complimentary access until a date
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


# ----- program years (one-time purchases) --------------------------------------------
_PROGRAM_PRICE_ID_CACHE: dict[int, str] = {}


def owned_years(s: Session, user: "User") -> list[int]:
    """Program years this user owns, always including Year 1 (free for everyone)."""
    years = {1}
    rows = s.scalars(select(ProgramPurchase.year).where(ProgramPurchase.user_id == user.id,
                                                        ProgramPurchase.refunded_at.is_(None))).all()
    years.update(rows)
    return sorted(years)


def next_purchasable_year(owned: list[int]) -> int | None:
    """The next year the user could buy (must own every year before it), or None if it's not on sale yet."""
    candidate = max(owned) + 1
    return candidate if candidate in program_year_prices() else None


def latest_refundable_purchase(s: Session, user: "User") -> "ProgramPurchase | None":
    """Only the most recent owned (paid) year can be refunded, and only within REFUND_DAYS, to keep the
    year-ownership chain valid."""
    owned = owned_years(s, user)
    if max(owned) <= 1:
        return None
    purchase = s.scalar(select(ProgramPurchase).where(ProgramPurchase.user_id == user.id,
                                                      ProgramPurchase.year == max(owned),
                                                      ProgramPurchase.refunded_at.is_(None)))
    if not purchase or purchase.purchased_at < utcnow() - timedelta(days=REFUND_DAYS):
        return None
    return purchase


# ----- streaks (see streaks.py for the pure day-counting logic) ------------------------
def get_program_start(s: Session, user: "User") -> date | None:
    """The user's program start date, from their synced `setting:start` record (either edition, newest wins)."""
    rows = s.scalars(select(Record).where(Record.user_id == user.id, Record.uid == "setting:start",
                                          Record.kind == "setting", Record.deleted.is_(False))).all()
    best = None
    for r in rows:
        if not best or r.updated > best.updated:
            best = r
    if not best or not best.data:
        return None
    try:
        value = json.loads(best.data).get("value")
        return datetime.fromisoformat(str(value).replace("Z", "")).date() if value else None
    except (TypeError, ValueError):
        return None


def streak_summary(s: Session, user: "User") -> dict | None:
    """None unless the user owns a paid program year (Year 2+) and has a synced program start date."""
    if max(owned_years(s, user)) <= 1:
        return None
    start = get_program_start(s, user)
    if start is None:
        return None
    checks = list(s.scalars(select(StreakCheck.day).where(StreakCheck.user_id == user.id)).all())
    r = compute_streak(checks, start, utcnow().date())
    return {"streak_days": r.streak_days, "discount_pct": r.discount_pct,
           "today_is_training_day": r.today_is_training_day, "checked_today": r.checked_today,
           "next_discount_at_days": r.next_discount_at_days}


def compute_dhash(image_bytes: bytes) -> str:
    """64-bit difference hash (dHash), as a 16-char hex string. Never touches disk."""
    from PIL import Image
    with Image.open(io.BytesIO(image_bytes)) as img:
        img.load()
        small = img.convert("L").resize((9, 8), Image.LANCZOS)
        pixels = small.tobytes()  # mode "L": one byte (0-255) per pixel
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if pixels[row * 9 + col] > pixels[row * 9 + col + 1] else 0)
    return f"{bits:016x}"


def hamming_distance(a_hex: str, b_hex: str) -> int:
    return bin(int(a_hex, 16) ^ int(b_hex, 16)).count("1")


def exif_datetime_original(image_bytes: bytes) -> datetime | None:
    """The photo's EXIF "date taken", if any. Only JPEGs typically carry this."""
    from PIL import ExifTags, Image
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            exif = img.getexif()
            if not exif:
                return None
            raw = exif.get(0x9003)  # DateTimeOriginal, sometimes present at the top level
            if not raw:
                try:
                    exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
                    raw = exif_ifd.get(0x9003)
                except Exception:
                    raw = None
            if not raw:
                return None
            return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


def program_purchase_error(s: Session, user: "User", year: int) -> str | None:
    """None if `year` is purchasable by this user right now, else a message to show them."""
    prices = program_year_prices()
    if year not in prices:
        return "That program year isn't available yet."
    owned = owned_years(s, user)
    if year in owned:
        return "You already own that program year."
    if year - 1 not in owned:
        return "Buy the previous program year first."
    return None


def _program_year_price_id(stripe, year: int) -> str:
    if year not in _PROGRAM_PRICE_ID_CACHE:
        lookup_key = f"{PROGRAM_YEAR_LOOKUP_PREFIX}{year}"
        prices = stripe.Price.list(lookup_keys=[lookup_key], active=True, limit=1).data
        if not prices:
            raise HTTPException(500, "That program year isn't set up for purchase yet.")
        _PROGRAM_PRICE_ID_CACHE[year] = prices[0].id
    return _PROGRAM_PRICE_ID_CACHE[year]


def stripe_checkout_program_year(user, base: str, year: int, consent_version: str) -> str:
    """Create a one-time-payment Stripe Checkout session for a program year."""
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    price_id = _program_year_price_id(stripe, year)
    params = {"mode": "payment", "line_items": [{"price": price_id, "quantity": 1}],
              "client_reference_id": str(user.id),
              "metadata": {"kind": "program_year", "year": str(year), "user_id": str(user.id),
                          "consent_version": consent_version},
              "success_url": f"{base}/account/program?paid={year}", "cancel_url": f"{base}/account/program"}
    if user.stripe_customer:
        params["customer"] = user.stripe_customer
    else:
        # one-time payments don't create a Customer unless asked; we want one so billing links stay together
        params["customer_email"] = user.email
        params["customer_creation"] = "always"
    return stripe.checkout.Session.create(**params).url


def stripe_refund_purchase(purchase: "ProgramPurchase") -> bool:
    """Refund a specific program-year payment in full. Returns False if there's nothing to refund."""
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    if not purchase.stripe_payment_intent:
        return False
    # current Stripe API versions have no `charges` list on a PaymentIntent - use latest_charge, and attribute
    # access (stripe-python 13+ objects aren't dicts)
    intent = stripe.PaymentIntent.retrieve(purchase.stripe_payment_intent)
    if getattr(intent, "status", None) != "succeeded":
        return False
    latest = getattr(intent, "latest_charge", None)
    if not latest:
        return False
    charge = stripe.Charge.retrieve(latest if isinstance(latest, str) else latest.id)
    if not charge.paid or charge.refunded:
        return False
    stripe.Refund.create(payment_intent=purchase.stripe_payment_intent)
    return True


def handle_program_year_checkout(s: Session, obj: dict, request: Request | None = None) -> None:
    """checkout.session.completed for a one-time program-year purchase. Idempotent on the Stripe session id."""
    session_id = obj.get("id")
    if session_id and s.scalar(select(ProgramPurchase).where(ProgramPurchase.stripe_session_id == session_id)):
        return
    metadata = obj.get("metadata") or {}
    try:
        year = int(metadata.get("year"))
    except (TypeError, ValueError):
        return
    user_id = metadata.get("user_id") or obj.get("client_reference_id")
    user = s.get(User, int(user_id)) if user_id else None
    if not user:
        return
    prices = program_year_prices()
    amount_cents = obj.get("amount_total") or prices.get(year, 0)
    if obj.get("customer"):
        user.stripe_customer = obj["customer"]
    s.add(ProgramPurchase(user_id=user.id, year=year, amount_cents=amount_cents,
                          currency=(obj.get("currency") or "usd"), stripe_session_id=session_id,
                          stripe_payment_intent=obj.get("payment_intent"), purchased_at=utcnow()))
    consent_version = metadata.get("consent_version") or CONSENT_VERSION
    if not user.coaching_consent_at:
        user.coaching_consent_at = utcnow()
        user.coaching_consent_version = consent_version
    s.add(ConsentEvent(user_id=user.id, at=utcnow(), action="grant", version=consent_version, source="purchase"))
    if mail_on():
        try:
            send_mail(user.email, f"Your RuskiMaxxing Program Year {year} purchase",
                      PROGRAM_PURCHASE_EMAIL.format(year=year, price=format_price(amount_cents),
                                                    base=public_url(request), contact=contact_email(),
                                                    days=REFUND_DAYS))
        except Exception:
            logger.exception("Failed to send program-year purchase receipt email")


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


class LinkStart(BaseModel):
    edition: str = "standard"
    phone: bool = False


class LinkPoll(BaseModel):
    device_code: str


class SyncRequest(BaseModel):
    edition: str
    since: int = 0
    changes: list[Change] = []


def same_origin(request: Request):
    """Forms only accept posts from this site (plus SameSite cookies) - basic CSRF protection."""
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != public_url(request):
        raise HTTPException(403, "Bad origin")


def create_user(s: Session, email: str, password: str) -> "User":
    email = email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 320:
        raise HTTPException(400, "Enter a valid email address")
    if len(password) < 8:
        raise HTTPException(400, "Use a password of at least 8 characters")
    if s.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "That email already has an account - log in instead")
    user = User(email=email, password_hash=ph.hash(password))
    s.add(user)
    s.flush()
    return user


def erase_user(s: Session, user: "User") -> None:
    for model in (Record, LoginSession, ResetToken, AppLink, AdminSession, ProgramPurchase, ConsentEvent,
                 StreakCheck):
        s.execute(delete(model).where(model.user_id == user.id))
    s.delete(user)
    s.commit()


DUMMY_HASH = ph.hash(secrets.token_urlsafe(16))


def check_password(s: Session, email: str, password: str) -> "User | None":
    user = s.scalar(select(User).where(User.email == email.strip().lower()))
    try:
        # verify against a dummy hash for unknown emails too, so response time doesn't reveal which accounts exist
        ok = ph.verify(user.password_hash if user else DUMMY_HASH, password) and bool(user)
    except (VerifyMismatchError, InvalidHashError):
        ok = False
    if ok and ph.check_needs_rehash(user.password_hash):
        user.password_hash = ph.hash(password)
    return user if ok else None


def request_reset(s: Session, email: str) -> None:
    user = s.scalar(select(User).where(User.email == email.strip().lower()))
    if user and mail_on():
        token = secrets.token_urlsafe(32)
        s.add(ResetToken(token_hash=digest(token), user_id=user.id, expires=utcnow() + timedelta(hours=1)))
        s.commit()
        link = f"{public_url()}/reset?token={token}"
        send_mail(user.email, "Reset your RuskiMaxxing password",
                  f"Reset your password within 1 hour:\n\n{link}\n\nIf you didn't ask for this, ignore it.")


# ----- app --------------------------------------------------------------------------
def create_app(database_url: str | None = None) -> FastAPI:
    from . import admin  # deferred import: admin.py imports names from this module at its own import time

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
        user = create_user(s, body.email, body.password)
        token = new_session(s, user)
        s.commit()
        return {"token": token, "email": user.email, "plan": plan_info(user)}

    # ----- "sign in with your browser" for the apps ------------------------------------
    @app.post("/api/link/start")
    def link_start(body: LinkStart, request: Request, s: Session = Depends(db)):
        if body.edition not in EDITIONS:
            raise HTTPException(400, "Unknown edition")
        s.execute(delete(AppLink).where(AppLink.expires < utcnow()))
        device_code = secrets.token_urlsafe(32)
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        s.add(AppLink(device_hash=digest(device_code), user_code=code, edition=body.edition, phone=body.phone,
                      expires=utcnow() + timedelta(minutes=LINK_MINUTES)))
        s.commit()
        return {"device_code": device_code, "code": f"{code[:4]}-{code[4:]}",
                "url": f"{public_url(request)}/link?code={code}", "interval": 2, "expires_in": LINK_MINUTES * 60}

    @app.post("/api/link/poll")
    def link_poll(body: LinkPoll, response: Response, s: Session = Depends(db)):
        row = s.get(AppLink, digest(body.device_code))
        if not row or row.expires < utcnow():
            raise HTTPException(410, "That sign-in expired. Tap Sign in again.")
        if not row.user_id:
            response.status_code = 202
            return {"pending": True}
        user = s.get(User, row.user_id)
        s.delete(row)
        token = new_session(s, user)
        s.commit()
        return {"token": token, "email": user.email, "plan": plan_info(user)}

    @app.post("/api/login")
    def login(body: Credentials, s: Session = Depends(db)):
        user = check_password(s, body.email, body.password)
        if not user:
            raise HTTPException(401, "Wrong email or password")
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
        out = {"email": user.email, "records": counts, "plan": plan_info(user),
              "program_years": owned_years(s, user)}
        summary = streak_summary(s, user)
        if summary is not None:
            out["streak"] = summary
        return out

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
        user.last_sync_at = utcnow()
        s.commit()
        rows = s.scalars(select(Record).where(Record.user_id == user.id, Record.edition == body.edition,
                                              Record.seq > body.since).order_by(Record.seq)).all()
        out = [{"uid": r.uid, "kind": r.kind, "updated": r.updated, "deleted": r.deleted,
                "data": json.loads(r.data) if r.data else None} for r in rows]
        return {"changes": out, "seq": max([body.since] + [r.seq for r in rows]), "plan": plan_info(user)}

    @app.post("/api/streak")
    async def api_streak(request: Request, photo: UploadFile = File(...), local_date: str = Form(...),
                         utc_offset_minutes: int = Form(...), user: User = Depends(current_user),
                         s: Session = Depends(db)):
        if max(owned_years(s, user)) <= 1:
            raise HTTPException(400, "Streaks are part of a paid program year.")
        start = get_program_start(s, user)
        if start is None:
            raise HTTPException(400, "Set your program start date in the app first.")
        try:
            client_date = date.fromisoformat(local_date)
        except ValueError:
            raise HTTPException(400, "Bad date") from None
        server_local_date = (utcnow() + timedelta(minutes=utc_offset_minutes)).date()
        if client_date != server_local_date:
            raise HTTPException(400, "That doesn't match the current time - check your device's clock.")
        from .streaks import is_training_day
        if not is_training_day(client_date, start):
            raise HTTPException(400, "Today isn't a scheduled training day.")
        if s.scalar(select(StreakCheck).where(StreakCheck.user_id == user.id, StreakCheck.day == client_date)):
            raise HTTPException(400, "You already checked in today.")
        if photo.content_type not in STREAK_ALLOWED_CONTENT_TYPES:
            raise HTTPException(400, "Upload a JPEG or PNG photo.")
        body = await photo.read()
        if len(body) > STREAK_MAX_UPLOAD_BYTES:
            raise HTTPException(400, "That photo is too large (8 MB max).")
        try:
            phash = compute_dhash(body)
        except Exception:
            raise HTTPException(400, "That doesn't look like a photo.") from None
        client_local_now = utcnow() + timedelta(minutes=utc_offset_minutes)
        exif_at = exif_datetime_original(body)
        if exif_at is not None and abs(exif_at - client_local_now) > STREAK_EXIF_TOLERANCE:
            raise HTTPException(400, "That photo wasn't just taken.")
        previous = s.scalars(select(StreakCheck.phash).where(StreakCheck.user_id == user.id)).all()
        if any(hamming_distance(phash, prev) < STREAK_PHASH_MIN_DISTANCE for prev in previous):
            raise HTTPException(400, "That looks like a photo you've already used - take a fresh one.")
        s.add(StreakCheck(user_id=user.id, day=client_date, received_at=utcnow(), phash=phash))
        s.commit()
        del body  # never persisted - kept in memory only for the checks above
        checks = list(s.scalars(select(StreakCheck.day).where(StreakCheck.user_id == user.id)).all())
        result = compute_streak(checks, start, utcnow().date())
        return {"ok": True, "streak": {"streak_days": result.streak_days, "discount_pct": result.discount_pct,
                                       "today_is_training_day": result.today_is_training_day,
                                       "checked_today": result.checked_today,
                                       "next_discount_at_days": result.next_discount_at_days}}

    @app.delete("/api/account")
    def delete_account(body: Password, user: User = Depends(current_user), s: Session = Depends(db)):
        try:
            ph.verify(user.password_hash, body.password)
        except (VerifyMismatchError, InvalidHashError):
            raise HTTPException(401, "Wrong password") from None
        erase_user(s, user)
        return {"deleted": True}

    # ----- web account page: plan status, subscribe, manage billing --------------------
    def web_user(s: Session, token: str | None):
        row = s.get(LoginSession, digest(token)) if token else None
        return s.get(User, row.user_id) if row and row.expires >= utcnow() else None

    @app.get("/account", response_class=HTMLResponse)
    def account(request: Request, paid: int = 0, msg: str = "", error: int = 0, next: str = "/account",
                rmx_session: str | None = Cookie(default=None), s: Session = Depends(db)):
        user = web_user(s, rmx_session)
        if not user:
            return page("Log in", login_form(next))
        if safe_next(next) != "/account":
            return RedirectResponse(safe_next(next), status_code=303)
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
            <p><a href="/account/program">Program years &amp; streak</a></p>
            <form method="post" action="/account/logout"><p><button>Log out</button></p></form>
            <p><a href="/account/delete">Delete account</a></p>""")

    def signed_in(request: Request, s: Session, user: User, nxt: str) -> RedirectResponse:
        token = secrets.token_urlsafe(32)
        s.add(LoginSession(token_hash=digest(token), user_id=user.id,
                           expires=utcnow() + timedelta(days=WEB_SESSION_DAYS)))
        s.commit()
        resp = RedirectResponse(safe_next(nxt), status_code=303)
        resp.set_cookie(COOKIE, token, max_age=WEB_SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=public_url(request).startswith("https://"))
        return resp

    @app.post("/account/login")
    def account_login(request: Request, email: str = Form(...), password: str = Form(...),
                      next: str = Form(default="/account"), s: Session = Depends(db)):
        same_origin(request)
        user = check_password(s, email, password)
        if not user:
            return HTMLResponse(page("Log in", login_form(next, "Wrong email or password.", email)), status_code=401)
        return signed_in(request, s, user, next)

    @app.get("/signup", response_class=HTMLResponse)
    def signup_page(next: str = "/account"):
        return page("Create your account", signup_form(next))

    @app.post("/account/register")
    def account_register(request: Request, email: str = Form(...), password: str = Form(...),
                         password2: str = Form(...), next: str = Form(default="/account"),
                         s: Session = Depends(db)):
        same_origin(request)
        if password != password2:
            return HTMLResponse(page("Create your account", signup_form(next, "The passwords don't match.", email)),
                                status_code=400)
        try:
            user = create_user(s, email, password)
        except HTTPException as e:
            return HTMLResponse(page("Create your account", signup_form(next, e.detail, email)),
                                status_code=e.status_code)
        return signed_in(request, s, user, next)

    @app.get("/account/forgot", response_class=HTMLResponse)
    def forgot_page():
        return page("Forgot password", """
            <p>Enter your account's email and we'll send a link to set a new password.</p>
            <form method="post" action="/account/forgot">
              <label>Email<input name="email" type="email" autocomplete="email" required></label>
              <button>Send reset link</button></form>
            <p><a href="/account">Back to log in</a></p>""")

    @app.post("/account/forgot", response_class=HTMLResponse)
    def forgot_submit(request: Request, email: str = Form(...), s: Session = Depends(db)):
        same_origin(request)
        request_reset(s, email)
        return page("Check your email", "<p>If that email has an account, a reset link is on its way. It works "
                                        "for 1 hour.</p><p><a href=\"/account\">Back to log in</a></p>")

    @app.get("/account/delete", response_class=HTMLResponse)
    def delete_page(rmx_session: str | None = Cookie(default=None), s: Session = Depends(db)):
        user = web_user(s, rmx_session)
        if not user:
            return page("Log in", login_form("/account/delete", "Log in to delete your account."))
        return page("Delete account", f"""
            <p>This permanently deletes <b>{html.escape(user.email)}</b> and every cloud backup for both apps. It can't
            be undone. Your data on your own devices stays. If you have a paid plan, cancel it first under
            <a href="/account">Manage billing / cancel</a>.</p>
            <form method="post" action="/account/delete">
              <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
              <button style="background:#8B1A1A">Delete my account</button></form>""")

    @app.post("/account/delete", response_class=HTMLResponse)
    def delete_submit(request: Request, password: str = Form(...), rmx_session: str | None = Cookie(default=None),
                      s: Session = Depends(db)):
        same_origin(request)
        user = web_user(s, rmx_session)
        if not user:
            return RedirectResponse("/account", status_code=303)
        if not check_password(s, user.email, password):
            return HTMLResponse(page("Delete account", '<p>Wrong password. <a href="/account/delete">Try again</a>.'
                                                       '</p>'), status_code=401)
        erase_user(s, user)
        resp = HTMLResponse(page("Account deleted", "<p>Your account and all cloud backups are deleted. Log out in "
                                                    "the app (Cloud backup) to finish on each device.</p>"))
        resp.delete_cookie(COOKIE)
        return resp

    # ----- the page an app opens to sign in ----------------------------------------
    def live_link(s: Session, code: str) -> AppLink | None:
        row = s.scalar(select(AppLink).where(AppLink.user_code == code.replace("-", "").strip().upper()))
        return row if row and row.expires >= utcnow() else None

    @app.get("/link", response_class=HTMLResponse)
    def link_page(code: str = "", rmx_session: str | None = Cookie(default=None), s: Session = Depends(db)):
        row = live_link(s, code)
        if not row:
            return page("Link expired", "<p>This sign-in link expired or was already used. Go back to the app and "
                                        "tap <b>Sign in</b> again.</p>")
        here = f"/link?code={row.user_code}"
        user = web_user(s, rmx_session)
        if not user:
            return page("Sign in to RuskiMaxxing", login_form(here))
        return page("Connect the app", f"""
            <p>Signed in as <b>{html.escape(user.email)}</b>.</p>
            <p>Connect your RuskiMaxxing app to this account? (Only if you just tapped the link in your own app.)</p>
            <form method="post" action="/link"><input type="hidden" name="code" value="{row.user_code}">
              <button>Connect this app</button></form>
            <form method="post" action="/account/logout"><input type="hidden" name="next" value="{here}">
              <p><button class="link">Not you? Use a different account</button></p></form>""")

    @app.post("/link", response_class=HTMLResponse)
    def link_approve(request: Request, code: str = Form(...), rmx_session: str | None = Cookie(default=None),
                     s: Session = Depends(db)):
        same_origin(request)
        row, user = live_link(s, code), web_user(s, rmx_session)
        if not row or not user:
            return RedirectResponse(f"/link?code={html.escape(code)}", status_code=303)
        row.user_id = user.id
        s.commit()
        back = (f'<p><a class="btn" href="{APP_SCHEMES[row.edition]}://signed-in">Return to the app</a></p>'
                if row.phone else "")
        return page("You're signed in", f"""
            <p><b>Done - your app is connected to {html.escape(user.email)}.</b></p>
            <p>Go back to the RuskiMaxxing app. It finishes signing in by itself in a few seconds.</p>{back}""")

    @app.post("/account/logout")
    def account_logout(request: Request, next: str = Form(default="/account"),
                       rmx_session: str | None = Cookie(default=None), s: Session = Depends(db)):
        same_origin(request)
        if rmx_session:
            s.execute(delete(LoginSession).where(LoginSession.token_hash == digest(rmx_session)))
            s.commit()
        resp = RedirectResponse(safe_next(next), status_code=303)
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

    # ----- web account page: program years, coaching consent, streak ------------------
    def consent_checkboxes(warn: bool = False) -> str:
        warning = ('<p style="color:#8B1A1A"><b>Please tick both boxes to continue.</b></p>' if warn else "")
        return f"""{warning}
          <p><label><input type="checkbox" name="consent" value="yes" required style="width:auto">
          I agree that the operator can view and use my synced training data (workouts, bodyweight, body fat
          and settings) to personalize my program and coach me. I can withdraw this any time on this page.</label></p>
          <p><label><input type="checkbox" name="terms" value="yes" required style="width:auto">
          I agree to the <a href="/terms">Terms of Service</a>.</label></p>"""

    def consent_only_checkbox() -> str:
        return """<p><label><input type="checkbox" name="consent" value="yes" required style="width:auto">
          I agree that the operator can view and use my synced training data (workouts, bodyweight, body fat
          and settings) to personalize my program and coach me. I can withdraw this any time on this page.</label></p>"""

    def program_page_html(request: Request, user: User, s: Session, error: str = "", msg: str = "") -> str:
        owned = owned_years(s, user)
        prices = program_year_prices()
        base = public_url(request)
        next_year = next_purchasable_year(owned)

        purchases = s.scalars(select(ProgramPurchase).where(ProgramPurchase.user_id == user.id)
                              .order_by(ProgramPurchase.purchased_at.desc())).all()
        owned_rows = "".join(f"<li>Year {y}{' (free)' if y == 1 else ''}</li>" for y in owned)

        if user.coaching_consent_at:
            consent_html = (f"<p><b>Coaching consent: granted</b> ({user.coaching_consent_at.date()}). The "
                            f"operator can view your synced training data to personalize your program and coach "
                            f"you.</p><form method='post' action='/account/consent/withdraw' "
                            f"onsubmit=\"return confirm('Withdraw consent? The operator will no longer be able to "
                            f"view your training data. Your program years keep working.')\">"
                            f"<button>Withdraw consent</button></form>")
        else:
            regrant = ('<form method="post" action="/account/consent/grant">' + consent_only_checkbox() +
                      '<p><button>Re-grant consent</button></p></form>') if max(owned) > 1 else ""
            consent_html = (f"<p><b>Coaching consent: not granted.</b> The operator can't see your training "
                            f"data.</p>{regrant}")

        if error == "consent":
            error_banner = "<p style='color:#8B1A1A'><b>Please tick both boxes to continue.</b></p>"
        elif error:
            error_banner = f"<p style='color:#8B1A1A'><b>{html.escape(error)}</b></p>"
        else:
            error_banner = ""

        if next_year is None:
            buy_html = "<p>No further program years are for sale yet - check back later.</p>"
        else:
            price = format_price(prices[next_year])
            buy_html = f"""<div style="border:2px solid #4A1942;padding:10px 14px;background:#F6EEDC">
            <p><b>Program Year {next_year}: {price}, one-time purchase.</b></p>
            <form method="post" action="/account/program/{next_year}/checkout">
            {consent_checkboxes()}
            <p><button>Buy Year {next_year} - {price}</button></p></form></div>"""

        refundable = latest_refundable_purchase(s, user)
        refund_html = ""
        if refundable:
            refund_html = (f"<form method='post' action='/account/program/{refundable.year}/refund' "
                           f"onsubmit=\"return confirm('Refund Year {refundable.year} in full? This removes that "
                           f"program year.')\"><p><button>Refund Year {refundable.year} "
                           f"({format_price(refundable.amount_cents)})</button><br>"
                           f"<small>Within {REFUND_DAYS} days of purchase.</small></p></form>")

        streak_html = ""
        summary = streak_summary(s, user)
        if summary is not None:
            streak_html = f"""<div class="card"><h3>Streak</h3>
            <p>Current streak: <b>{summary['streak_days']} days</b>{" (checked in today)" if summary['checked_today'] else ""}.
            Coaching-call discount: <b>{summary['discount_pct']}%</b> off {CALL_PRICE_PLAIN}
            {f" (next discount at {summary['next_discount_at_days']} days)" if summary['next_discount_at_days'] else " (max discount reached)"}.</p>
            <p class="small">Coaching calls aren't bookable here yet - this discount will apply when they are.</p></div>"""
        elif max(owned) > 1:
            streak_html = ('<div class="card"><h3>Streak</h3><p class="small">Set your program start date in the '
                          'app to start your streak.</p></div>')

        note = {"refunded": "<p><b>Refund issued.</b> That program year has been removed.</p>",
               "norefund": "<p><b>Nothing to refund.</b> Only the most recent purchase, within "
                          f"{REFUND_DAYS} days, can be refunded.</p>"}.get(msg, "")
        thanks = "<p><b>Thanks - your purchase went through.</b> It can take a minute to show here.</p>" if \
            request.query_params.get("paid") else ""

        return page("Program years", f"""
            {thanks}{note}{error_banner}
            <div class="card"><h3>Program years you own</h3><ul>{owned_rows}</ul>{refund_html}</div>
            {streak_html}
            <div class="card"><h3>Coaching consent</h3>{consent_html}</div>
            <div class="card"><h3>Buy the next program year</h3>{buy_html}</div>
            <p><a href="/account">Back to account</a></p>""")

    @app.get("/account/program", response_class=HTMLResponse)
    def account_program(request: Request, msg: str = "", rmx_session: str | None = Cookie(default=None),
                        s: Session = Depends(db)):
        user = web_user(s, rmx_session)
        if not user:
            return page("Log in", login_form("/account/program"))
        return program_page_html(request, user, s, msg=msg)

    @app.post("/account/program/{year}/checkout", response_class=HTMLResponse)
    def account_program_checkout(request: Request, year: int, consent: str = Form(default=""),
                                 terms: str = Form(default=""), rmx_session: str | None = Cookie(default=None),
                                 s: Session = Depends(db)):
        same_origin(request)
        user = web_user(s, rmx_session)
        if not user:
            return RedirectResponse("/account/program", status_code=303)
        if not billing_on():
            return HTMLResponse(page("Not available", "<p>Program-year purchases aren't set up on this server."
                                                       "</p>"), status_code=400)
        err = program_purchase_error(s, user, year)
        if err:
            return HTMLResponse(program_page_html(request, user, s, error=err), status_code=400)
        if consent != "yes" or terms != "yes":
            return HTMLResponse(program_page_html(request, user, s, error="consent"), status_code=400)
        return RedirectResponse(stripe_checkout_program_year(user, public_url(request), year, CONSENT_VERSION),
                                status_code=303)

    @app.post("/account/program/{year}/refund")
    def account_program_refund(request: Request, year: int, rmx_session: str | None = Cookie(default=None),
                               s: Session = Depends(db)):
        same_origin(request)
        user = web_user(s, rmx_session)
        if not user:
            return RedirectResponse("/account/program", status_code=303)
        purchase = latest_refundable_purchase(s, user)
        if not purchase or purchase.year != year or not billing_on():
            return RedirectResponse("/account/program?msg=norefund", status_code=303)
        if not stripe_refund_purchase(purchase):
            return RedirectResponse("/account/program?msg=norefund", status_code=303)
        purchase.refunded_at = utcnow()
        s.commit()
        if mail_on():
            try:
                send_mail(user.email, "Your RuskiMaxxing program-year refund",
                          f"We've refunded your Year {purchase.year} purchase in full. It goes back to your "
                          f"original payment method, usually within 5-10 business days.\n\nQuestions: "
                          f"{contact_email()}")
            except Exception:
                logger.exception("Failed to send program-year refund email")
        return RedirectResponse("/account/program?msg=refunded", status_code=303)

    @app.post("/account/consent/withdraw")
    def account_consent_withdraw(request: Request, rmx_session: str | None = Cookie(default=None),
                                 s: Session = Depends(db)):
        same_origin(request)
        user = web_user(s, rmx_session)
        if not user:
            return RedirectResponse("/account/program", status_code=303)
        user.coaching_consent_at = None
        s.add(ConsentEvent(user_id=user.id, at=utcnow(), action="withdraw",
                           version=user.coaching_consent_version, source="account"))
        s.commit()
        return RedirectResponse("/account/program", status_code=303)

    @app.post("/account/consent/grant", response_class=HTMLResponse)
    def account_consent_grant(request: Request, consent: str = Form(default=""), terms: str = Form(default=""),
                              rmx_session: str | None = Cookie(default=None), s: Session = Depends(db)):
        same_origin(request)
        user = web_user(s, rmx_session)
        if not user:
            return RedirectResponse("/account/program", status_code=303)
        if max(owned_years(s, user)) <= 1:
            return HTMLResponse(program_page_html(request, user, s, error="Buy a program year first."),
                                status_code=400)
        if consent != "yes":
            return HTMLResponse(program_page_html(request, user, s, error="consent"), status_code=400)
        user.coaching_consent_at = utcnow()
        user.coaching_consent_version = CONSENT_VERSION
        s.add(ConsentEvent(user_id=user.id, at=utcnow(), action="grant", version=CONSENT_VERSION, source="account"))
        s.commit()
        return RedirectResponse("/account/program", status_code=303)

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
            metadata = obj.get("metadata") or {}
            if obj.get("mode") == "payment" and metadata.get("kind") == "program_year":
                handle_program_year_checkout(s, obj, request)
            else:
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
        request_reset(s, body.email)
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
            return page("Link expired", '<p>This reset link is invalid or expired. '
                                        '<a href="/account/forgot">Send a new one</a>.</p>')
        if len(password) < 8:
            return page("Too short", "<p>Use at least 8 characters. Go back and try again.</p>")
        user = s.get(User, row.user_id)
        user.password_hash = ph.hash(password)
        s.execute(delete(ResetToken).where(ResetToken.user_id == user.id))
        s.execute(delete(LoginSession).where(LoginSession.user_id == user.id))  # log out everywhere
        s.commit()
        return page("Password changed", '<p>Done. <a href="/account">Log in</a> with your new password.</p>')

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        contact = html.escape(contact_email())
        return page("Privacy policy", PRIVACY.format(contact=contact, host=html.escape(request.url.hostname or ""),
                                                      updated=TERMS_UPDATED))

    @app.get("/terms", response_class=HTMLResponse)
    def terms(request: Request):
        return page("Terms of Service", terms_html(public_url(request)))

    admin.register(app, SessionLocal, engine)
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


def safe_next(nxt: str) -> str:
    """Only redirect within this site after logging in (no open redirects)."""
    return nxt if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt else "/account"


def login_form(nxt: str, error: str = "", email: str = "") -> str:
    nxt = html.escape(safe_next(nxt))
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f"""{err}<form method="post" action="/account/login"><input type="hidden" name="next" value="{nxt}">
      <label>Email<input name="email" type="email" autocomplete="email" value="{html.escape(email)}" required></label>
      <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
      <button>Log in</button></form>
      <p><a href="/account/forgot">Forgot password?</a></p>
      <hr><p><b>New here?</b> Accounts are free.</p>
      <p><a class="btn alt" href="/signup?next={nxt}">Create an account</a></p>"""


def signup_form(nxt: str, error: str = "", email: str = "") -> str:
    nxt = html.escape(safe_next(nxt))
    err = f'<p class="err">{html.escape(str(error))}</p>' if error else ""
    return f"""{err}<form method="post" action="/account/register"><input type="hidden" name="next" value="{nxt}">
      <label>Email<input name="email" type="email" autocomplete="email" value="{html.escape(email)}" required></label>
      <label>Password (8+ characters)<input name="password" type="password" autocomplete="new-password"
        minlength="8" required></label>
      <label>Password again<input name="password2" type="password" autocomplete="new-password" minlength="8"
        required></label>
      <p class="small">By creating an account you agree to the <a href="/terms">Terms</a> and
      <a href="/privacy">Privacy Policy</a>.</p>
      <button>Create account</button></form>
      <p>Already have an account? <a href="/account?next={nxt}">Log in</a></p>"""


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


def program_years_terms_list() -> str:
    items = "".join(f"<li>Year {year}: {format_price(cents)}, plus any sales tax that applies where you live.</li>"
                    for year, cents in sorted(program_year_prices().items()))
    return items or "<li>No further program years are on sale yet.</li>"


def terms_html(base: str) -> str:
    operator = html.escape(os.environ.get("OPERATOR_NAME", "") or "the operator of this site")
    state = html.escape(os.environ.get("GOVERNING_STATE", "") or "the U.S. state where the operator is located")
    return TERMS.format(operator=operator, state=state, contact=html.escape(contact_email()), base=base,
                        price=PLAN_PRICE_PLAIN, days=REFUND_DAYS, updated=TERMS_UPDATED,
                        program_years_list=program_years_terms_list(), call_price=CALL_PRICE_PLAIN)


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
<style>body{{font-family:system-ui,sans-serif;background:#EDE3CF;color:#2B1B24;max-width:520px;margin:24px auto;
padding:0 16px;font-size:17px;line-height:1.45}}h1{{color:#4A1942;font-size:26px}}
label{{display:block;margin:14px 0 4px;font-weight:600}}
input:not([type=checkbox]){{display:block;box-sizing:border-box;width:100%;padding:12px;font-size:17px;margin-top:4px;
border:1px solid #8a7a66;border-radius:6px;background:#fff}}
button,.btn{{display:inline-block;box-sizing:border-box;background:#4A1942;color:#F2D675;border:0;border-radius:6px;
padding:14px 20px;font-size:17px;font-weight:bold;margin-top:12px;text-decoration:none;text-align:center}}
form>button,.btn{{width:100%}}.btn.alt{{background:#C9A227;color:#2B1B24}}
button.link{{background:none;color:#4A1942;text-decoration:underline;padding:0;width:auto;font-weight:normal}}
.err{{background:#F6D6D6;color:#8B1A1A;padding:10px;border-radius:6px;font-weight:600}}.small{{font-size:14px}}
a{{color:#4A1942}}</style></head>
<body><h1>{title}</h1>{body}
<p style="margin-top:40px;font-size:90%"><a href="/account">Account</a> &middot; <a href="/terms">Terms</a>
&middot; <a href="/privacy">Privacy</a></p></body></html>"""


PRIVACY = """
<p><i>Last updated {updated}</i></p>
<p>RuskiMaxxing Cloud ({host}) stores a backup of the training data you choose to sync from the
RuskiMaxxing apps so you can restore it on another device. The apps are free; cloud backup is a paid
yearly plan, and further program years are optional one-time purchases. Payments are handled by Stripe -
we never see or store your card number.</p>
<h2>What we store</h2>
<ul><li>Your email address and a one-way hash of your password (never the password itself).</li>
<li>Your Stripe customer id, plan status (active / ended and the renewal date), and program-year purchase
records (year, amount, date, and whether it was refunded).</li>
<li>Your training log (sets, weights, reps, RPE, notes), bodyweight, body fat measurements and program settings
such as height and start date.</li>
<li>If you check in for a streak: the date, the time we received your check-in, and a fingerprint of the photo
(never the photo itself - see "Streak photos" below).</li>
<li>Whether you've granted coaching consent, when, under which version of that consent, and a history of
grants/withdrawals.</li></ul>
<h2>How we use it</h2>
<ul><li>To back up and restore your data, and to run your account, plan and program-year purchases.</li>
<li>To improve the training programs, including building future years. For this we only look at training
results combined across many users and stripped of anything that identifies you: never your email, and never
one person's log on its own.</li>
<li><b>Coaching consent:</b> if - and only if - you've checked the coaching-consent box (required before buying
a program year, withdrawable and re-grantable any time at <a href="/account/program">/account/program</a>), we
can also view your individual synced training log, bodyweight, body fat and settings, in order to personalize
your program and coach you directly. Every time we (a human operator, via the admin tools) look at a consented
user's individual data, that view is logged. Without your consent, we can't see your individual data at all -
only aggregate counts.</li></ul>
<h2>Streak photos</h2>
<p>If you use the streak feature, your barbell photo is processed entirely in memory on our server at the moment
you submit it, to compute a perceptual fingerprint (so we can reject an obviously reused photo) and, if present,
read the photo's EXIF timestamp. <b>The photo itself is never written to disk, a database, or a log, and we
discard it immediately after processing.</b> We keep only the date, when we received it, and that fingerprint.</p>
<h2>What we don't do</h2>
<ul><li>We don't sell or share your data, show ads, or use trackers.</li>
<li>We don't publish or share anyone's individual data, including in program research.</li>
<li>We don't store streak photos, and we don't verify what's actually in them.</li></ul>
<h2>Your control</h2>
<ul><li>Delete your account and all synced data at any time from the app (Setup / Start - Cloud backup -
Delete account). Deletion is immediate and permanent.</li>
<li>Your data also stays on your own device; the app works without an account.</li>
<li>If your plan ends, backups pause but nothing is deleted - you can still restore, or delete it yourself.</li>
<li>Withdraw coaching consent at any time at <a href="/account/program">/account/program</a>; we immediately lose
access to your individual training data. Your purchased program years keep working either way.</li></ul>
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

<h2>8. Program years (one-time purchases)</h2>
<ul>
{program_years_list}
<li>Program years beyond the free Year 1 built into the app are sold <b>only on this website</b>, as
<b>one-time purchases</b> - not subscriptions, and not covered by the automatic-renewal rules in Section 4. The
apps themselves never sell or advertise a program year.</li>
<li>You must already own the program year before the one you're buying (for example, Year 3 requires already
owning Year 2).</li>
<li>Buying a program year unlocks that year's personalized program in the app, built from your own synced
training data, plus light coaching from us - which requires the coaching consent described in Section 9.</li>
<li><b>Full refund within {days} days</b> of that purchase, same window as Section 6. Only your <b>most recently
purchased year</b> can be refunded, so the year-to-year ownership chain stays valid. Use "Refund" at
<a href="/account/program">{base}/account/program</a> or email {contact}.</li>
</ul>

<h2>9. Coaching consent</h2>
<p>Before you can buy a program year, you must separately check a box agreeing that we can view and use your
synced training data (workouts, bodyweight, body fat and settings) to personalize your program and coach you.
This consent is the <b>only</b> way we get access to your individual data - see the
<a href="/privacy">Privacy Policy</a>. You can withdraw it at any time at
<a href="/account/program">{base}/account/program</a>; your purchased program years keep working either way. If
you later want individual coaching again, you can re-grant consent the same way, as long as you own at least one
paid program year.</p>

<h2>10. Streaks and the coaching-call discount</h2>
<p>If you own a paid program year, the app can track a training "streak": on each of your 3 scheduled training
days a week, you submit a photo of a loaded barbell. <b>We don't verify that a barbell is actually in the
photo</b> - the streak is an honor-system habit tool, not a graded assessment. Streak photos are processed only in
memory on our server and are <b>never saved</b> to disk, a database, or a log; we keep only the date, the time we
received it, and a fingerprint used to reject an obviously reused photo (see the Privacy Policy). A long streak
reduces the price of a coaching call ({call_price}: 10% off per full 90-day streak, capped at 50%). Coaching calls
themselves aren't bookable through the Service yet; when they are, any discount you've built will apply.</p>

<h2>11. Your data</h2>
<p>Your training data is yours. You let us store and process it only to run the Service, as described in the
<a href="/privacy">Privacy Policy</a> (including the combined, de-identified use it explains). We don't sell it.</p>

<h2>12. Acceptable use</h2>
<p>Don't access other people's accounts, try to break or overload the Service, use it to store anything other than
your own training data, or use it for anything illegal. We may suspend accounts that do.</p>

<h2>13. Availability and backups</h2>
<p>We work to keep the Service running and back up its database every night, but it may sometimes be down for
maintenance or problems outside our control. The apps keep a full copy of your data on your device, so you can
keep training while offline.</p>

<h2>14. Open-source software</h2>
<p>The RuskiMaxxing apps and this server's code are free, open-source software under the MIT License. These Terms
cover the hosted Service we run, not your use of the code. The RuskiMaxxing name and eagle logo aren't licensed
for others to use as their own brand.</p>

<h2>15. Disclaimer</h2>
<p>To the extent the law allows, the Service is provided "as is" and "as available", without warranties of any
kind, including merchantability, fitness for a particular purpose and non-infringement.</p>

<h2>16. Limit of liability</h2>
<p>To the extent the law allows, we aren't liable for indirect, incidental, special or consequential damages,
or for lost data or profits, and our total liability for any claim about the Service is limited to the amount
you paid us in the 12 months before the claim. Some states don't allow some of these limits, so they may not
apply to you.</p>

<h2>17. Ending the agreement</h2>
<p>You can stop using the Service and delete your account at any time. We may suspend or close accounts that
break these Terms. If we close your account without you having broken them, we'll refund the unused part of your
plan year.</p>

<h2>18. Changes to these Terms</h2>
<p>If we make a material change, we'll email account holders at least 30 days before it takes effect and update
the date above. If you don't agree, you can cancel, and the 30-day refund in Section 6 (or Section 8 for a
program year) still applies to your latest payment.</p>

<h2>19. Law and disputes</h2>
<p>These Terms are governed by the laws of {state} and applicable U.S. federal law. Please email {contact} first
so we can try to sort out any problem informally. Either of us may bring a claim in small-claims court if it
qualifies. Nothing in these Terms takes away rights you have under consumer-protection laws that can't be waived.</p>

<h2>20. Contact</h2>
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

PROGRAM_PURCHASE_EMAIL = """Thanks for buying RuskiMaxxing Program Year {year} ({price}, one-time).

This unlocks the Year {year} program in the app, built from your own training data, plus light
coaching from the operator - which requires the coaching-consent you agreed to at checkout. You
can withdraw that consent any time at {base}/account/program; your program years keep working
either way.

Refunds: you can get a full refund within {days} days of this purchase. Use "Refund" at
{base}/account/program or email {contact}.

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
