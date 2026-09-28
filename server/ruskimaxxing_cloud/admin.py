"""Admin backend: /admin/* - dashboard, users, research, audit log, system, billing.

Two data-access rules (see server/README.md "Admin" for the full policy):
  1. INDIVIDUAL training data (a user's lift/bodyweight/bodyfat records) is only shown to the admin for
     users who've given explicit coaching consent (users.coaching_consent_at set). Without consent, admin
     pages show record counts/sizes/last-sync only, plus a clear notice. Every view of a consented user's
     training data is written to the audit log.
  2. RESEARCH pages show aggregate, de-identified statistics only - never per-user rows, emails or ids -
     and suppress ("<10") any aggregate computed from fewer than K distinct users.

This module is imported lazily from main.create_app() (see the comment there) specifically so it can do a
normal top-level `from .main import ...` here without a circular-import error: by the time create_app() is
actually called, main.py has finished executing top to bottom, so every name below already exists.
"""

import html
import json
import os
import secrets
import shutil
import socket
import ssl
import statistics
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Cookie, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import totp
from .main import (ACTIVE_STATUSES, AdminSession, AuditLog, EDITIONS, KINDS, LoginSession, PLAN_PRICE_PLAIN,
                   REFUND_DAYS, Record, User, billing_on, check_password, complimentary, contact_email,
                   digest, erase_user, mail_on, plan_active, public_url, request_reset, same_origin,
                   send_mail, stripe_refund_latest, utcnow)

ADMIN_COOKIE = "rmx_admin"
ADMIN_SESSION_HOURS = 12
K = 10  # research: suppress any aggregate cell computed from fewer than K distinct users
SUPPRESSED = "<10"
PAGE_SIZE = 50
CONSENT_VERSION = "v1"  # bumped if/when the consent language changes
MAIN_LIFTS = ("Squat", "Bench Press", "Deadlift", "Overhead Press")  # ruskimaxxing.exercises.POWER
WEEK_BUCKETS = (("0", 0, 0), ("1-12", 1, 12), ("13-24", 13, 24), ("25-36", 25, 36), ("37-48", 37, 48),
               ("49-52", 49, 52))


# ----- small shared helpers ----------------------------------------------------------
def is_complimentary(user: User) -> bool:
    return complimentary(user) or (user.comp_until is not None and user.comp_until > utcnow())


def storage_bytes(s: Session, user_id: int) -> int:
    return s.scalar(select(func.coalesce(func.sum(func.length(Record.data)), 0))
                    .where(Record.user_id == user_id, Record.deleted.is_(False))) or 0


def record_counts(s: Session, user_id: int) -> dict:
    rows = s.execute(select(Record.edition, Record.kind, func.count()).where(
        Record.user_id == user_id, Record.deleted.is_(False)).group_by(Record.edition, Record.kind)).all()
    out = {}
    for edition, kind, n in rows:
        out.setdefault(edition, {})[kind] = n
    return out


def active_session_count(s: Session, user_id: int) -> int:
    return s.scalar(select(func.count()).select_from(LoginSession).where(
        LoginSession.user_id == user_id, LoginSession.expires >= utcnow())) or 0


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def fmt_dt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "-"


def stripe_base() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    return "https://dashboard.stripe.com/test/" if key.startswith("sk_test_") else "https://dashboard.stripe.com/"


def stripe_customer_link(user: User) -> str:
    if not user.stripe_customer:
        return ""
    return f'{stripe_base()}customers/{esc(user.stripe_customer)}'


def e1rm(weight: float, reps: float) -> float:
    """Epley formula. reps must be >= 1 (caller filters)."""
    return weight * (1 + reps / 30)


# ----- theme / layout ------------------------------------------------------------------
_STYLE = """
* {box-sizing:border-box}
body{margin:0;font-family:system-ui,sans-serif;background:#EDE3CF;color:#2B1B24;display:flex;min-height:100vh}
h1,h2,h3{font-family:Georgia,serif;color:#4A1942}
.sidebar{width:220px;flex:0 0 220px;background:#2E0C28;min-height:100vh;padding:20px 0}
.logo{color:#C9A227;font-family:Georgia,serif;font-size:22px;font-weight:bold;padding:0 20px 20px}
.sidebar a.nav{display:block;padding:12px 20px;color:#F6EFDE;text-decoration:none;border-left:4px solid transparent}
.sidebar a.nav.active{border-left-color:#C9A227;color:#F2D675;background:rgba(201,162,39,0.12)}
.main{flex:1;min-width:0}
.topbar{background:#4A1942;color:#F6EFDE;padding:14px 24px;display:flex;justify-content:space-between;
align-items:center;flex-wrap:wrap;gap:8px}
.topbar h1{color:#F2D675;font-size:20px;margin:0}
.topbar .who{font-size:14px;color:#F6EFDE}
.content{padding:24px;max-width:1200px}
.card{background:#F6EFDE;border:1px solid #C9A227;border-radius:8px;padding:16px;margin-bottom:18px}
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:18px}
.kpi{background:#F6EFDE;border:1px solid #C9A227;border-radius:8px;padding:14px 18px;min-width:150px}
.kpi .n{font-size:26px;font-weight:bold;color:#4A1942}
.kpi .label{font-size:13px;color:#6b5a4e}
table{border-collapse:collapse;width:100%;background:#F6EFDE}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #ddd0b8;font-size:14px;vertical-align:top}
th{background:#EDE3CF;color:#4A1942}
a{color:#4A1942}
button,.btn{background:#4A1942;color:#F2D675;border:0;border-radius:6px;padding:8px 14px;font-weight:bold;
cursor:pointer;text-decoration:none;display:inline-block;font-size:14px}
button.danger{background:#8B1A1A}
button.link{background:none;color:#F6EFDE;text-decoration:underline;padding:0;font-weight:normal}
input,select{padding:8px;border:1px solid #8a7a66;border-radius:6px;font-size:14px}
.notice{background:#F6D6D6;color:#8B1A1A;padding:10px;border-radius:6px;font-weight:600;margin-bottom:14px}
.ok{background:#DCEEDB;color:#245C24}
.hidden-note{background:#EDE3CF;border:1px dashed #8a7a66;padding:10px;border-radius:6px;color:#6b5a4e}
.small{font-size:13px;color:#6b5a4e}
form.inline{display:inline}
@media (max-width:800px) {
  body{flex-direction:column}
  .sidebar{width:100%;min-height:auto;display:flex;overflow-x:auto;padding:10px 0}
  .logo{display:none}
  .sidebar a.nav{border-left:0;border-bottom:4px solid transparent;white-space:nowrap;padding:10px 14px}
  .sidebar a.nav.active{border-bottom-color:#C9A227}
}
"""

_NAV = (("dashboard", "/admin", "Dashboard"), ("users", "/admin/users", "Users"),
       ("research", "/admin/research", "Research"), ("audit", "/admin/audit", "Audit log"),
       ("system", "/admin/system", "System"), ("billing", "/admin/billing", "Billing"))


def admin_page(title: str, body: str, active: str = "", admin_email: str = "", csrf: str = "") -> str:
    links = "".join(f'<a class="nav{" active" if key == active else ""}" href="{href}">{label}</a>'
                    for key, href, label in _NAV)
    logout = (f'<form class="inline" method="post" action="/admin/logout">'
             f'<input type="hidden" name="csrf" value="{esc(csrf)}"><button class="link">Log out</button></form>')
    topbar = (f'<div class="topbar"><h1>{esc(title)}</h1><div class="who">{esc(admin_email)} &middot; {logout}'
             f'</div></div>')
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(title)} - RuskiMaxxing Admin</title>
<style>{_STYLE}</style></head>
<body><div class="sidebar"><div class="logo">RuskiMaxxing</div>{links}</div>
<div class="main">{topbar}<div class="content">{body}</div></div></body></html>"""


def login_page(error: str = "") -> str:
    err = f'<p class="notice">{esc(error)}</p>' if error else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Admin log in - RuskiMaxxing</title>
<style>body{{font-family:system-ui,sans-serif;background:#EDE3CF;color:#2B1B24;max-width:420px;margin:60px auto;
padding:0 16px}}h1{{font-family:Georgia,serif;color:#4A1942}}
label{{display:block;margin:14px 0 4px;font-weight:600}}
input{{display:block;box-sizing:border-box;width:100%;padding:12px;font-size:17px;border:1px solid #8a7a66;
border-radius:6px}}
button{{width:100%;background:#4A1942;color:#F2D675;border:0;border-radius:6px;padding:14px;font-size:17px;
font-weight:bold;margin-top:16px}}
.notice{{background:#F6D6D6;color:#8B1A1A;padding:10px;border-radius:6px;font-weight:600}}</style></head>
<body><h1>RuskiMaxxing Admin</h1>{err}
<form method="post" action="/admin/login">
<label>Email<input name="email" type="email" autocomplete="username" required></label>
<label>Password<input name="password" type="password" autocomplete="current-password" required></label>
<label>Authenticator code<input name="code" inputmode="numeric" pattern="[0-9]*" maxlength="6"
  autocomplete="one-time-code" required></label>
<button>Log in</button></form></body></html>"""


# ----- registration --------------------------------------------------------------------
def register(app, SessionLocal, engine) -> None:
    def db():
        with SessionLocal() as s:
            yield s

    def require_admin(request: Request, rmx_admin: str | None = Cookie(default=None), s: Session = Depends(db)):
        row = s.get(AdminSession, digest(rmx_admin)) if rmx_admin else None
        user = s.get(User, row.user_id) if row and row.expires >= utcnow() else None
        if not user or not user.is_admin or not user.totp_secret:
            raise HTTPException(303, headers={"Location": "/admin/login"})
        return row, user, s

    def check_csrf(request: Request, row: AdminSession, csrf: str | None) -> None:
        same_origin(request)
        if not csrf or not hmac_eq(csrf, row.csrf_token):
            raise HTTPException(403, "Bad or missing form token - go back and try again.")

    def audit(s: Session, admin_user: User | None, action: str, request: Request | None = None,
              target_user_id: int | None = None, detail: str = "") -> None:
        ip = request.client.host if request is not None and request.client else None
        s.add(AuditLog(at=utcnow(), admin_user_id=admin_user.id if admin_user else None, action=action,
                       target_user_id=target_user_id, detail=(detail or "")[:2000], ip=ip))
        s.commit()

    # ----- login / logout ------------------------------------------------------------
    @app.get("/admin/login", response_class=HTMLResponse)
    def admin_login_page(rmx_admin: str | None = Cookie(default=None), s: Session = Depends(db)):
        row = s.get(AdminSession, digest(rmx_admin)) if rmx_admin else None
        if row and row.expires >= utcnow():
            return RedirectResponse("/admin", status_code=303)
        return login_page()

    @app.post("/admin/login")
    def admin_login_submit(request: Request, email: str = Form(...), password: str = Form(...),
                           code: str = Form(...), s: Session = Depends(db)):
        same_origin(request)
        user = check_password(s, email, password)
        step = None
        if user and user.is_admin and user.totp_secret:
            step = totp.verify(user.totp_secret, code, user.totp_last_step)
        if not user or not user.is_admin or not user.totp_secret or step is None:
            audit(s, None, "login_failed", request)
            return HTMLResponse(login_page("Wrong email, password, or code."), status_code=401)
        user.totp_last_step = step
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        s.add(AdminSession(token_hash=digest(token), user_id=user.id, csrf_token=csrf,
                           expires=utcnow() + timedelta(hours=ADMIN_SESSION_HOURS)))
        s.commit()
        audit(s, user, "login_success", request)
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie(ADMIN_COOKIE, token, max_age=ADMIN_SESSION_HOURS * 3600, httponly=True,
                        samesite="strict", secure=public_url(request).startswith("https://"), path="/admin")
        return resp

    @app.post("/admin/logout")
    def admin_logout(request: Request, csrf: str = Form(default=""),
                     rmx_admin: str | None = Cookie(default=None), dep=Depends(require_admin)):
        row, admin_user, s = dep
        check_csrf(request, row, csrf)
        s.execute(delete(AdminSession).where(AdminSession.token_hash == digest(rmx_admin)))
        s.commit()
        resp = RedirectResponse("/admin/login", status_code=303)
        resp.delete_cookie(ADMIN_COOKIE, path="/admin")
        return resp

    # ----- dashboard -------------------------------------------------------------------
    @app.get("/admin", response_class=HTMLResponse)
    def admin_dashboard(request: Request, dep=Depends(require_admin)):
        row, admin_user, s = dep
        users = s.scalars(select(User)).all()
        now = utcnow()
        total = len(users)
        comp = sum(1 for u in users if is_complimentary(u))
        active_paid = sum(1 for u in users if billing_on() and not is_complimentary(u) and plan_active(u))
        lapsed = sum(1 for u in users if billing_on() and not is_complimentary(u) and not plan_active(u)
                    and u.stripe_customer)
        signups_7 = sum(1 for u in users if u.created and u.created >= now - timedelta(days=7))
        signups_30 = sum(1 for u in users if u.created and u.created >= now - timedelta(days=30))
        synced_7 = sum(1 for u in users if u.last_sync_at and u.last_sync_at >= now - timedelta(days=7))
        total_records = s.scalar(select(func.count()).select_from(Record).where(Record.deleted.is_(False))) or 0
        total_storage = s.scalar(select(func.coalesce(func.sum(func.length(Record.data)), 0))
                                 .where(Record.deleted.is_(False))) or 0
        try:
            price = float(PLAN_PRICE_PLAIN.lstrip("$"))
        except ValueError:
            price = 0.0
        revenue = active_paid * price

        weeks = []
        for i in range(11, -1, -1):
            start = (now - timedelta(days=now.weekday())) - timedelta(weeks=i)
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
            n = sum(1 for u in users if u.created and start <= u.created < end)
            weeks.append((start.strftime("%b %d"), n))
        chart = svg_bar_chart(weeks)

        kpis = "".join(f'<div class="kpi"><div class="n">{n}</div><div class="label">{label}</div></div>' for n, label in [
            (total, "Total users"), (active_paid, "Active paid plans"), (comp, "Complimentary"),
            (lapsed, "Lapsed"), (signups_7, "Sign-ups, last 7 days"), (signups_30, "Sign-ups, last 30 days"),
            (synced_7, "Synced, last 7 days"), (total_records, "Total records"),
            (f"{total_storage / 1024:.1f} KB", "Total storage"), (f"${revenue:,.0f}", "Est. yearly revenue"),
        ])
        body = f"""<div class="kpis">{kpis}</div>
        <div class="card"><h2>Sign-ups, last 12 weeks</h2>{chart}</div>"""
        return admin_page("Dashboard", body, "dashboard", admin_user.email, row.csrf_token)

    # ----- users list --------------------------------------------------------------------
    @app.get("/admin/users", response_class=HTMLResponse)
    def admin_users(request: Request, q: str = "", plan: str = "", edition: str = "", sort: str = "joined",
                    page: int = 1, dep=Depends(require_admin)):
        row, admin_user, s = dep
        users = list(s.scalars(select(User)).all())
        if q:
            needle = q.strip().lower()
            users = [u for u in users if needle in u.email.lower()]
        if edition:
            have_edition = {uid for (uid,) in s.execute(select(Record.user_id).where(
                Record.edition == edition, Record.deleted.is_(False)).distinct())}
            users = [u for u in users if u.id in have_edition]

        def plan_bucket(u: User) -> str:
            if is_complimentary(u):
                return "complimentary"
            if not billing_on():
                return "none"
            if plan_active(u):
                return "active"
            return "lapsed" if u.stripe_customer else "none"

        if plan:
            users = [u for u in users if plan_bucket(u) == plan]

        rows = []
        for u in users:
            rows.append({"user": u, "records": s.scalar(select(func.count()).select_from(Record).where(
                            Record.user_id == u.id, Record.deleted.is_(False))) or 0,
                        "storage": storage_bytes(s, u.id), "devices": active_session_count(s, u.id),
                        "plan": plan_bucket(u)})
        keys = {"joined": lambda r: r["user"].created or datetime.min,
               "last_sync": lambda r: r["user"].last_sync_at or datetime.min,
               "storage": lambda r: r["storage"]}
        rows.sort(key=keys.get(sort, keys["joined"]), reverse=True)

        total = len(rows)
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, pages))
        page_rows = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

        trs = "".join(f"""<tr><td><a href="/admin/users/{r['user'].id}">{esc(r['user'].email)}</a></td>
            <td>{fmt_dt(r['user'].created)}</td><td>{esc(r['plan'])}{' - ' + esc(r['user'].plan_until.date()) if r['user'].plan_until else ''}</td>
            <td>{fmt_dt(r['user'].last_sync_at)}</td><td>{r['devices']}</td><td>{r['records']}</td>
            <td>{r['storage'] / 1024:.1f} KB</td><td>{'yes' if r['user'].coaching_consent_at else 'no'}</td></tr>"""
                     for r in page_rows)
        qs = f"&q={esc(q)}&plan={esc(plan)}&edition={esc(edition)}&sort={esc(sort)}"
        pager = f"""<p class="small">Page {page} of {pages} ({total} users)
            {f'<a href="/admin/users?page={page-1}{qs}">&laquo; prev</a>' if page > 1 else ''}
            {f'<a href="/admin/users?page={page+1}{qs}">next &raquo;</a>' if page < pages else ''}</p>"""
        body = f"""<form method="get" class="card">
            <label>Search email<input name="q" value="{esc(q)}"></label>
            <label>Plan<select name="plan"><option value="">Any</option>
              {"".join(f'<option value="{v}"{" selected" if plan==v else ""}>{v}</option>' for v in ("active", "lapsed", "none", "complimentary"))}
            </select></label>
            <label>Edition<select name="edition"><option value="">Any</option>
              {"".join(f'<option value="{v}"{" selected" if edition==v else ""}>{v}</option>' for v in EDITIONS)}
            </select></label>
            <label>Sort<select name="sort"><option value="joined"{" selected" if sort=="joined" else ""}>Joined</option>
              <option value="last_sync"{" selected" if sort=="last_sync" else ""}>Last sync</option>
              <option value="storage"{" selected" if sort=="storage" else ""}>Storage</option></select></label>
            <button>Filter</button></form>
            <table><tr><th>Email</th><th>Joined</th><th>Plan</th><th>Last sync</th><th>Devices</th>
            <th>Records</th><th>Storage</th><th>Consent</th></tr>{trs}</table>{pager}"""
        return admin_page("Users", body, "users", admin_user.email, row.csrf_token)

    # ----- user detail --------------------------------------------------------------------
    @app.get("/admin/users/{user_id}", response_class=HTMLResponse)
    def admin_user_detail(request: Request, user_id: int, msg: str = "", dep=Depends(require_admin)):
        row, admin_user, s = dep
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404, "No such user")
        audit(s, admin_user, "view_user", request, target_user_id=user.id)

        counts = record_counts(s, user.id)
        storage = storage_bytes(s, user.id)
        sessions = s.scalars(select(LoginSession).where(LoginSession.user_id == user.id)).all()
        sess_rows = "".join(f"""<tr><td>{fmt_dt(sess.expires)}</td>
            <td>{'expired' if sess.expires < utcnow() else 'active'}</td>
            <td><form class="inline" method="post" action="/admin/users/{user.id}/revoke-session">
            <input type="hidden" name="csrf" value="{esc(row.csrf_token)}">
            <input type="hidden" name="token_hash" value="{esc(sess.token_hash)}">
            <button class="danger">Revoke</button></form></td></tr>""" for sess in sessions)

        plan_line = "Complimentary" if is_complimentary(user) else (
            "No billing configured" if not billing_on() else
            ("Active" if plan_active(user) else "Lapsed / none"))
        stripe_link = (f'<a href="{stripe_customer_link(user)}" target="_blank">{esc(user.stripe_customer)}</a>'
                      if user.stripe_customer else "-")

        notices = {"reset_sent": ("Password reset email sent.", "ok"),
                  "reset_nomail": ("SMTP isn't configured on this server - no email was sent.", ""),
                  "refunded": ("Refunded the latest payment and ended the plan.", "ok"),
                  "norefund": ("No payment from the last days to refund.", ""),
                  "comp_granted": ("Complimentary access granted.", "ok"),
                  "comp_revoked": ("Complimentary access revoked.", "ok"),
                  "session_revoked": ("Session revoked.", "ok"),
                  "sessions_revoked": ("Signed out everywhere.", "ok"),
                  "bad_confirm": ("Type the account's email exactly to confirm deletion.", "")}
        text, cls = notices.get(msg, ("", ""))
        notice = f'<p class="notice {cls}">{esc(text)}</p>' if text else ""

        record_table = "".join(f"<tr><td>{esc(edition)}</td><td>{esc(kind)}</td><td>{n}</td></tr>"
                               for edition, kinds in counts.items() for kind, n in kinds.items())

        if user.coaching_consent_at:
            audit(s, admin_user, "data_view", request, target_user_id=user.id)
            training = training_section(s, user)
        else:
            training = ('<div class="hidden-note">Training data hidden - no coaching consent. '
                       'Record counts and storage are shown above only.</div>')

        csrf_field = f'<input type="hidden" name="csrf" value="{esc(row.csrf_token)}">'
        body = f"""{notice}
        <div class="card"><h2>{esc(user.email)}</h2>
        <p>Joined {fmt_dt(user.created)} &middot; Last sync {fmt_dt(user.last_sync_at)} &middot;
        Storage {storage / 1024:.1f} KB &middot; Coaching consent: {'yes, ' + fmt_dt(user.coaching_consent_at) if user.coaching_consent_at else 'no'}</p>
        <p>Plan: <b>{esc(plan_line)}</b>{f" until {esc(user.plan_until.date())}" if user.plan_until else ""}
        {" (cancels at period end)" if user.cancel_at_period_end else ""}
        {f" &middot; comp until {esc(user.comp_until.date())}" if user.comp_until else ""}</p>
        <p>Stripe customer: {stripe_link}</p></div>

        <div class="card"><h3>Records</h3><table><tr><th>Edition</th><th>Kind</th><th>Count</th></tr>
        {record_table or '<tr><td colspan=3>No records</td></tr>'}</table></div>

        <div class="card"><h3>Active sessions ({sum(1 for x in sessions if x.expires >= utcnow())})</h3>
        <table><tr><th>Expires</th><th>Status</th><th></th></tr>{sess_rows or '<tr><td colspan=3>None</td></tr>'}</table>
        <form method="post" action="/admin/users/{user.id}/revoke-all">{csrf_field}
        <button class="danger">Sign out everywhere</button></form></div>

        <div class="card"><h3>Actions</h3>
        <form class="inline" method="post" action="/admin/users/{user.id}/reset-password">{csrf_field}
        <button>Send password-reset email</button></form>

        <form class="inline" method="post" action="/admin/users/{user.id}/comp"
          onsubmit="return confirm('Grant complimentary access?')">{csrf_field}
        <input type="hidden" name="action" value="grant">
        <label>Comp until <input type="date" name="until" required></label>
        <button>Grant complimentary</button></form>

        <form class="inline" method="post" action="/admin/users/{user.id}/comp"
          onsubmit="return confirm('Revoke complimentary access?')">{csrf_field}
        <input type="hidden" name="action" value="revoke"><button>Revoke complimentary</button></form>

        <form class="inline" method="post" action="/admin/users/{user.id}/refund"
          onsubmit="return confirm('Refund the latest payment in full and end the plan now?')">{csrf_field}
        <button>Refund latest payment</button></form>

        <p><a class="btn" href="/admin/users/{user.id}/export">Export user data (JSON)</a></p>

        <form method="post" action="/admin/users/{user.id}/delete"
          onsubmit="return confirm('Permanently delete this account and all its data?')">{csrf_field}
        <label>Type the account's email to confirm<input name="confirm_email" required></label>
        <button class="danger">Delete account</button></form>
        </div>
        {training}"""
        return admin_page(f"User: {user.email}", body, "users", admin_user.email, row.csrf_token)

    def training_section(s: Session, user: User) -> str:
        recs = s.scalars(select(Record).where(Record.user_id == user.id, Record.deleted.is_(False),
                                              Record.kind.in_(("lift", "bodyweight", "bodyfat")))
                         .order_by(Record.updated.desc())).all()
        lifts = [r for r in recs if r.kind == "lift"][:100]
        bw = [r for r in recs if r.kind == "bodyweight"][:50]
        bf = [r for r in recs if r.kind == "bodyfat"][:50]

        best = {}
        for r in recs:
            if r.kind != "lift" or not r.data:
                continue
            d = json.loads(r.data)
            if d.get("done") is False:
                continue
            ex, weight, reps = d.get("exercise"), d.get("weight"), d.get("reps")
            if not ex or weight is None or reps is None or reps < 1:
                continue
            val = e1rm(float(weight), float(reps))
            if ex not in best or val > best[ex]:
                best[ex] = val
        best_rows = "".join(f"<tr><td>{esc(ex)}</td><td>{val:.0f}</td></tr>" for ex, val in sorted(best.items()))

        def lift_row(r):
            d = json.loads(r.data) if r.data else {}
            return (f"<tr><td>{esc(d.get('date'))}</td><td>{esc(d.get('exercise'))}</td>"
                   f"<td>{esc(d.get('weight'))}</td><td>{esc(d.get('reps'))}</td>"
                   f"<td>{esc(d.get('rpe'))}</td><td>{esc(d.get('note'))}</td></tr>")

        def bw_row(r):
            d = json.loads(r.data) if r.data else {}
            return f"<tr><td>{esc(d.get('date'))}</td><td>{esc(d.get('weight'))}</td></tr>"

        def bf_row(r):
            d = json.loads(r.data) if r.data else {}
            return f"<tr><td>{esc(d.get('date'))}</td><td>{esc(d.get('percent'))}</td><td>{esc(d.get('method'))}</td></tr>"

        return f"""<div class="card"><h3>Training data</h3><p class="small">Consented view - this page load
        was recorded in the audit log.</p>
        <h4>Best e1RM by exercise (Epley, done sets only)</h4>
        <table><tr><th>Exercise</th><th>Best e1RM</th></tr>{best_rows or '<tr><td colspan=2>None yet</td></tr>'}</table>
        <h4>Recent sets (last 100)</h4>
        <table><tr><th>Date</th><th>Exercise</th><th>Weight</th><th>Reps</th><th>RPE</th><th>Note</th></tr>
        {''.join(lift_row(r) for r in lifts) or '<tr><td colspan=6>None</td></tr>'}</table>
        <h4>Bodyweight</h4><table><tr><th>Date</th><th>Weight</th></tr>
        {''.join(bw_row(r) for r in bw) or '<tr><td colspan=2>None</td></tr>'}</table>
        <h4>Body fat</h4><table><tr><th>Date</th><th>Percent</th><th>Method</th></tr>
        {''.join(bf_row(r) for r in bf) or '<tr><td colspan=3>None</td></tr>'}</table></div>"""

    @app.post("/admin/users/{user_id}/reset-password")
    def admin_reset_password(request: Request, user_id: int, csrf: str = Form(...), dep=Depends(require_admin)):
        row, admin_user, s = dep
        check_csrf(request, row, csrf)
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404)
        if not mail_on():
            audit(s, admin_user, "reset_email_failed", request, user.id, "SMTP not configured")
            return RedirectResponse(f"/admin/users/{user.id}?msg=reset_nomail", status_code=303)
        request_reset(s, user.email)
        audit(s, admin_user, "reset_email_sent", request, user.id)
        return RedirectResponse(f"/admin/users/{user.id}?msg=reset_sent", status_code=303)

    @app.post("/admin/users/{user_id}/comp")
    def admin_comp(request: Request, user_id: int, csrf: str = Form(...), action: str = Form(...),
                   until: str = Form(default=""), dep=Depends(require_admin)):
        row, admin_user, s = dep
        check_csrf(request, row, csrf)
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404)
        if action == "grant" and until:
            user.comp_until = datetime.fromisoformat(until) + timedelta(days=1)
            s.commit()
            audit(s, admin_user, "comp_granted", request, user.id, f"until {until}")
            return RedirectResponse(f"/admin/users/{user.id}?msg=comp_granted", status_code=303)
        user.comp_until = None
        s.commit()
        audit(s, admin_user, "comp_revoked", request, user.id)
        return RedirectResponse(f"/admin/users/{user.id}?msg=comp_revoked", status_code=303)

    @app.post("/admin/users/{user_id}/refund")
    def admin_refund(request: Request, user_id: int, csrf: str = Form(...), dep=Depends(require_admin)):
        row, admin_user, s = dep
        check_csrf(request, row, csrf)
        user = s.get(User, user_id)
        if not user or not user.stripe_customer or not billing_on():
            return RedirectResponse(f"/admin/users/{user_id}?msg=norefund", status_code=303)
        ok = stripe_refund_latest(user)
        if not ok:
            return RedirectResponse(f"/admin/users/{user.id}?msg=norefund", status_code=303)
        user.plan_status, user.plan_until, user.cancel_at_period_end = "canceled", utcnow(), False
        s.commit()
        audit(s, admin_user, "refund", request, user.id)
        return RedirectResponse(f"/admin/users/{user.id}?msg=refunded", status_code=303)

    @app.get("/admin/users/{user_id}/export")
    def admin_export(request: Request, user_id: int, dep=Depends(require_admin)):
        row, admin_user, s = dep
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404)
        recs = s.scalars(select(Record).where(Record.user_id == user.id)).all()
        payload = {
            "email": user.email, "created": user.created.isoformat() if user.created else None,
            "plan_status": user.plan_status, "plan_until": user.plan_until.isoformat() if user.plan_until else None,
            "cancel_at_period_end": user.cancel_at_period_end,
            "comp_until": user.comp_until.isoformat() if user.comp_until else None,
            "coaching_consent_at": user.coaching_consent_at.isoformat() if user.coaching_consent_at else None,
            "coaching_consent_version": user.coaching_consent_version,
            "last_sync_at": user.last_sync_at.isoformat() if user.last_sync_at else None,
            "records": [{"edition": r.edition, "uid": r.uid, "kind": r.kind, "updated": r.updated,
                        "deleted": r.deleted, "data": json.loads(r.data) if r.data else None} for r in recs],
        }
        audit(s, admin_user, "export", request, user.id)
        body = json.dumps(payload, indent=2)
        fname = f"ruskimaxxing-{user.email.replace('@', '_')}.json"
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    @app.post("/admin/users/{user_id}/delete")
    def admin_delete_user(request: Request, user_id: int, csrf: str = Form(...), confirm_email: str = Form(...),
                          dep=Depends(require_admin)):
        row, admin_user, s = dep
        check_csrf(request, row, csrf)
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404)
        if confirm_email.strip().lower() != user.email.lower():
            return RedirectResponse(f"/admin/users/{user.id}?msg=bad_confirm", status_code=303)
        audit(s, admin_user, "delete_account", request, user.id, user.email)
        erase_user(s, user)
        return RedirectResponse("/admin/users", status_code=303)

    @app.post("/admin/users/{user_id}/revoke-session")
    def admin_revoke_session(request: Request, user_id: int, csrf: str = Form(...), token_hash: str = Form(...),
                             dep=Depends(require_admin)):
        row, admin_user, s = dep
        check_csrf(request, row, csrf)
        s.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash, LoginSession.user_id == user_id))
        s.commit()
        audit(s, admin_user, "session_revoked", request, user_id)
        return RedirectResponse(f"/admin/users/{user_id}?msg=session_revoked", status_code=303)

    @app.post("/admin/users/{user_id}/revoke-all")
    def admin_revoke_all(request: Request, user_id: int, csrf: str = Form(...), dep=Depends(require_admin)):
        row, admin_user, s = dep
        check_csrf(request, row, csrf)
        s.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
        s.commit()
        audit(s, admin_user, "sessions_revoked", request, user_id)
        return RedirectResponse(f"/admin/users/{user_id}?msg=sessions_revoked", status_code=303)

    # ----- research (aggregate, de-identified) ------------------------------------------
    @app.get("/admin/research", response_class=HTMLResponse)
    def admin_research(request: Request, dep=Depends(require_admin)):
        row, admin_user, s = dep
        agg = build_research(s)
        body = research_html(agg)
        return admin_page("Research", body, "research", admin_user.email, row.csrf_token)

    @app.get("/admin/research.csv")
    def admin_research_csv(request: Request, dep=Depends(require_admin)):
        row, admin_user, s = dep
        agg = build_research(s)
        return Response(research_csv(agg), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="research.csv"'})

    # ----- audit log ---------------------------------------------------------------------
    @app.get("/admin/audit", response_class=HTMLResponse)
    def admin_audit(request: Request, action: str = "", page: int = 1, dep=Depends(require_admin)):
        row, admin_user, s = dep
        q = select(AuditLog).order_by(AuditLog.at.desc())
        if action:
            q = q.where(AuditLog.action == action)
        all_rows = s.scalars(q).all()
        total = len(all_rows)
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, pages))
        page_rows = all_rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        admins = {u.id: u.email for u in s.scalars(select(User)).all()}
        trs = "".join(f"""<tr><td>{fmt_dt(r.at)}</td><td>{esc(admins.get(r.admin_user_id, '-'))}</td>
            <td>{esc(r.action)}</td>
            <td>{f'<a href="/admin/users/{r.target_user_id}">{r.target_user_id}</a>' if r.target_user_id else '-'}</td>
            <td>{esc(r.detail)}</td><td>{esc(r.ip)}</td></tr>""" for r in page_rows)
        pager = (f'<p class="small">Page {page} of {pages} ({total} entries) '
                f'{f"<a href=\"/admin/audit?page={page-1}&action={esc(action)}\">&laquo; prev</a>" if page > 1 else ""} '
                f'{f"<a href=\"/admin/audit?page={page+1}&action={esc(action)}\">next &raquo;</a>" if page < pages else ""}</p>')
        body = f"""<form method="get" class="card"><label>Action<input name="action" value="{esc(action)}"></label>
        <button>Filter</button></form>
        <table><tr><th>When</th><th>Admin</th><th>Action</th><th>Target user</th><th>Detail</th><th>IP</th></tr>
        {trs or '<tr><td colspan=6>No entries</td></tr>'}</table>{pager}"""
        return admin_page("Audit log", body, "audit", admin_user.email, row.csrf_token)

    # ----- system ---------------------------------------------------------------------
    @app.get("/admin/system", response_class=HTMLResponse)
    def admin_system(request: Request, dep=Depends(require_admin)):
        row, admin_user, s = dep
        body = system_html(engine)
        return admin_page("System", body, "system", admin_user.email, row.csrf_token)

    # ----- billing ---------------------------------------------------------------------
    @app.get("/admin/billing", response_class=HTMLResponse)
    def admin_billing(request: Request, dep=Depends(require_admin)):
        row, admin_user, s = dep
        users = s.scalars(select(User)).all()
        by_status = {}
        for u in users:
            key = u.plan_status or "(none)"
            by_status[key] = by_status.get(key, 0) + 1
        status_rows = "".join(f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in sorted(by_status.items()))

        soon = [u for u in users if u.plan_until and utcnow() <= u.plan_until <= utcnow() + timedelta(days=30)
               and not u.cancel_at_period_end and u.plan_status in ACTIVE_STATUSES]
        soon_rows = "".join(f"<tr><td>{esc(u.email)}</td><td>{esc(u.plan_until.date())}</td></tr>" for u in soon)

        cancelling = [u for u in users if u.cancel_at_period_end]
        cancel_rows = "".join(f"<tr><td>{esc(u.email)}</td><td>{esc(u.plan_until.date()) if u.plan_until else '-'}</td></tr>"
                              for u in cancelling)

        refunds = s.scalars(select(AuditLog).where(AuditLog.action == "refund").order_by(AuditLog.at.desc())).all()
        admins = {u.id: u.email for u in users}
        refund_rows = "".join(f"<tr><td>{fmt_dt(r.at)}</td><td>{esc(admins.get(r.target_user_id, r.target_user_id))}</td>"
                              f"<td>{esc(admins.get(r.admin_user_id, '-'))}</td></tr>" for r in refunds)

        body = f"""<div class="card"><h3>Plans by status</h3><table><tr><th>Status</th><th>Users</th></tr>
        {status_rows or '<tr><td colspan=2>None</td></tr>'}</table></div>
        <div class="card"><h3>Renewing in the next 30 days</h3><table><tr><th>Email</th><th>Renews</th></tr>
        {soon_rows or '<tr><td colspan=2>None</td></tr>'}</table></div>
        <div class="card"><h3>Cancellations pending</h3><table><tr><th>Email</th><th>Ends</th></tr>
        {cancel_rows or '<tr><td colspan=2>None</td></tr>'}</table></div>
        <div class="card"><h3>Refunds issued</h3><table><tr><th>When</th><th>User</th><th>By</th></tr>
        {refund_rows or '<tr><td colspan=3>None</td></tr>'}</table></div>
        <p><a href="{stripe_base()}" target="_blank">Open Stripe dashboard</a></p>"""
        return admin_page("Billing", body, "billing", admin_user.email, row.csrf_token)


# ----- research aggregation (module-level, no Depends - reused by page + CSV) -----------
def hmac_eq(a: str, b: str) -> bool:
    import hmac as _hmac
    return _hmac.compare_digest(a or "", b or "")


def svg_bar_chart(weeks: list[tuple[str, int]]) -> str:
    if not weeks:
        return "<p>No data yet.</p>"
    w, h, gap = 60, 120, 8
    maxn = max(1, max(n for _, n in weeks))
    bars = []
    for i, (label, n) in enumerate(weeks):
        bar_h = int((n / maxn) * (h - 24))
        x = i * (w + gap)
        bars.append(f'<rect x="{x}" y="{h - bar_h - 20}" width="{w}" height="{bar_h}" fill="#4A1942"/>'
                    f'<text x="{x + w/2}" y="{h - 6}" font-size="9" text-anchor="middle" fill="#2B1B24">{esc(label)}</text>'
                    f'<text x="{x + w/2}" y="{h - bar_h - 24}" font-size="10" text-anchor="middle" fill="#4A1942">{n}</text>')
    width = len(weeks) * (w + gap)
    return f'<svg width="{width}" height="{h}" viewBox="0 0 {width} {h}">{"".join(bars)}</svg>'


def week_bucket(weeks_since_start: int) -> str:
    weeks_since_start = max(0, min(52, weeks_since_start))
    for label, lo, hi in WEEK_BUCKETS:
        if lo <= weeks_since_start <= hi:
            return label
    return WEEK_BUCKETS[-1][0]


def suppress(n: int, value):
    return value if n >= K else SUPPRESSED


def build_research(s: Session) -> dict:
    users = s.scalars(select(User)).all()
    by_edition = {}
    for e in EDITIONS:
        by_edition[e] = len({uid for (uid,) in s.execute(select(Record.user_id).where(
            Record.edition == e, Record.deleted.is_(False)).distinct())})

    # each user's current program-week bucket, from their "start" setting record (if any)
    buckets: dict[int, str] = {}
    e1rm_by_user_exercise: dict[int, dict[str, list[tuple[int, float]]]] = {}  # uid -> exercise -> [(week, e1rm)]
    done_flags_seen = False
    sessions: dict[tuple[int, int, int], bool] = {}  # (user, week, day) -> any done

    recs = s.scalars(select(Record).where(Record.deleted.is_(False),
                                          Record.kind.in_(("setting", "lift")))).all()
    for r in recs:
        if not r.data:
            continue
        try:
            d = json.loads(r.data)
        except (TypeError, ValueError):
            continue
        if r.kind == "setting" and d.get("key") == "start" and d.get("value"):
            try:
                start = datetime.fromisoformat(str(d["value"]).replace("Z", ""))
            except ValueError:
                continue
            weeks_since = (utcnow() - start).days // 7 + 1
            buckets[r.user_id] = week_bucket(weeks_since)
        elif r.kind == "lift":
            if "done" in d:
                done_flags_seen = True
            ex, weight, reps, week, day = d.get("exercise"), d.get("weight"), d.get("reps"), d.get("week"), d.get("day")
            if week is not None and day is not None:
                key = (r.user_id, week, day)
                sessions[key] = sessions.get(key, False) or bool(d.get("done"))
            if ex in MAIN_LIFTS and weight is not None and reps not in (None, 0) and reps >= 1 and week is not None:
                if d.get("done") is False:
                    continue
                val = e1rm(float(weight), float(reps))
                e1rm_by_user_exercise.setdefault(r.user_id, {}).setdefault(ex, []).append((week, val))

    week_dist: dict[str, set[int]] = {label: set() for label, _, _ in WEEK_BUCKETS}
    for uid, b in buckets.items():
        week_dist[b].add(uid)

    adherence = None
    if done_flags_seen and sessions:
        per_bucket: dict[str, list[bool]] = {label: [] for label, _, _ in WEEK_BUCKETS}
        for (uid, week, day), done in sessions.items():
            b = buckets.get(uid)
            if b:
                per_bucket[b].append(done)
        adherence = {}
        for label, vals in per_bucket.items():
            n_users = len({uid for (uid, week, day) in sessions if buckets.get(uid) == label})
            share = (sum(vals) / len(vals)) if vals else None
            adherence[label] = (n_users, share)

    lift_progress: dict[str, dict[str, tuple[int, float | None]]] = {}
    for ex in MAIN_LIFTS:
        lift_progress[ex] = {}
        per_bucket: dict[str, list[float]] = {label: [] for label, _, _ in WEEK_BUCKETS}
        for uid, by_ex in e1rm_by_user_exercise.items():
            points = by_ex.get(ex)
            if not points or len(points) < 2:
                continue
            points.sort(key=lambda p: p[0])
            first_week_val = points[0][1]
            best_last = max(v for w, v in points if w == points[-1][0])
            best_first = max(v for w, v in points if w == points[0][0])
            delta = best_last - best_first
            b = buckets.get(uid)
            if b:
                per_bucket[b].append(delta)
        for label, vals in per_bucket.items():
            n_users = len(vals)
            lift_progress[ex][label] = (n_users, statistics.median(vals) if vals else None)

    return {"by_edition": by_edition, "week_dist": week_dist, "adherence": adherence,
           "lift_progress": lift_progress, "total_users": len(users)}


def research_html(agg: dict) -> str:
    ed_rows = "".join(f"<tr><td>{esc(e)}</td><td>{suppress(n, n)}</td></tr>" for e, n in agg["by_edition"].items())
    wd_rows = "".join(f"<tr><td>{label}</td><td>{suppress(len(uids), len(uids))}</td></tr>"
                      for label, uids in agg["week_dist"].items())
    if agg["adherence"] is None:
        adherence_html = ('<p class="hidden-note">Adherence isn\'t derivable from the synced data on this '
                          'server yet (no lift records include a "done" flag).</p>')
    else:
        adherence_html = "<table><tr><th>Program week</th><th>Adherence</th></tr>" + "".join(
            f"<tr><td>{label}</td><td>{suppress(n, f'{share*100:.0f}%') if share is not None else '-'}</td></tr>"
            for label, (n, share) in agg["adherence"].items()) + "</table>"
    lift_html = ""
    for ex, buckets in agg["lift_progress"].items():
        rows = "".join(f"<tr><td>{label}</td><td>{suppress(n, f'{med:+.1f}') if med is not None else '-'}</td></tr>"
                       for label, (n, med) in buckets.items())
        lift_html += f"<h4>{esc(ex)}</h4><table><tr><th>Program week</th><th>Median e1RM change</th></tr>{rows}</table>"
    return f"""<p class="hidden-note">De-identified aggregates. Groups under {K} people are hidden ("{SUPPRESSED}").</p>
    <div class="card"><h3>Users by edition</h3><table><tr><th>Edition</th><th>Users</th></tr>{ed_rows}</table></div>
    <div class="card"><h3>Users by current program week</h3><table><tr><th>Program week</th><th>Users</th></tr>{wd_rows}</table></div>
    <div class="card"><h3>Adherence (share of logged sessions with a done set)</h3>{adherence_html}</div>
    <div class="card"><h3>Main-lift progress: median best-e1RM change, first logged week to latest</h3>{lift_html}</div>
    <p><a class="btn" href="/admin/research.csv">Download CSV</a></p>"""


def research_csv(agg: dict) -> str:
    lines = ["section,key,users,value"]
    for e, n in agg["by_edition"].items():
        lines.append(f"by_edition,{e},{n},{suppress(n, n)}")
    for label, uids in agg["week_dist"].items():
        lines.append(f"week_dist,{label},{len(uids)},{suppress(len(uids), len(uids))}")
    if agg["adherence"] is not None:
        for label, (n, share) in agg["adherence"].items():
            v = f"{share*100:.1f}%" if share is not None else ""
            lines.append(f"adherence,{label},{n},{suppress(n, v)}")
    for ex, buckets in agg["lift_progress"].items():
        for label, (n, med) in buckets.items():
            v = f"{med:.1f}" if med is not None else ""
            lines.append(f"lift_progress_{ex.replace(' ', '_')},{label},{n},{suppress(n, v)}")
    return "\n".join(lines) + "\n"


def system_html(engine) -> str:
    app_root = Path(__file__).resolve().parents[2]
    version = "unknown"
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=app_root, capture_output=True,
                             text=True, timeout=3)
        if out.returncode == 0:
            version = out.stdout.strip()
    except Exception:
        pass

    url = str(engine.url)
    if url.startswith("postgresql"):
        try:
            with engine.connect() as conn:
                size = conn.exec_driver_sql("SELECT pg_database_size(current_database())").scalar()
            db_line = f"PostgreSQL, {size / 1024 / 1024:.1f} MB"
        except Exception as e:
            db_line = f"PostgreSQL (size not readable: {e})"
    else:
        try:
            dbfile = engine.url.database
            size = Path(dbfile).stat().st_size if dbfile and dbfile != ":memory:" else 0
            db_line = f"SQLite, {size / 1024:.1f} KB"
        except Exception as e:
            db_line = f"SQLite (size not readable: {e})"

    try:
        usage = shutil.disk_usage(os.path.abspath(os.sep))
        disk_line = f"{usage.used / usage.total * 100:.0f}% used ({usage.free / 1024**3:.1f} GB free)"
    except Exception:
        disk_line = "not available"

    backup_dir = Path(os.environ.get("BACKUP_DIR", "/var/backups/ruskimaxxing"))
    try:
        files = sorted(backup_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        backup_line = (f"{files[0].name}, {datetime.fromtimestamp(files[0].stat().st_mtime):%Y-%m-%d %H:%M}, "
                       f"{files[0].stat().st_size / 1024:.0f} KB") if files else "no backups found"
    except Exception:
        backup_line = "not readable"

    host = None
    public = public_url()
    if public:
        host = public.split("//", 1)[-1].split("/", 1)[0].split(":")[0]
    tls_line = "not available"
    if host:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=3) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert()
            not_after = cert.get("notAfter")
            tls_line = f"expires {not_after}" if not_after else "no certificate info"
        except Exception as e:
            tls_line = f"not available ({type(e).__name__})"

    smtp_line = "configured" if mail_on() else "not configured"
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    stripe_line = "test" if key.startswith("sk_test_") else ("live" if key.startswith("sk_live_") else "off")

    reminders_log = Path(os.environ.get("REMINDERS_LOG", "/var/log/ruskimaxxing-reminders.log"))
    try:
        lines = reminders_log.read_text(errors="replace").splitlines()[-20:]
        reminders_block = "\n".join(lines) or "(empty)"
    except Exception:
        reminders_block = "not readable"

    return f"""<div class="card"><h3>App</h3><p>Version (git): {esc(version)}</p></div>
    <div class="card"><h3>Database</h3><p>{esc(db_line)}</p></div>
    <div class="card"><h3>Disk (/)</h3><p>{esc(disk_line)}</p></div>
    <div class="card"><h3>Latest backup</h3><p>{esc(backup_line)}</p></div>
    <div class="card"><h3>TLS certificate</h3><p>Host: {esc(host or '-')} &middot; {esc(tls_line)}</p></div>
    <div class="card"><h3>SMTP</h3><p>{esc(smtp_line)}</p></div>
    <div class="card"><h3>Stripe</h3><p>Mode: {esc(stripe_line)}</p></div>
    <div class="card"><h3>Reminders log (last 20 lines)</h3><pre style="white-space:pre-wrap;font-size:12px">{esc(reminders_block)}</pre></div>"""
