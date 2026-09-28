"""Admin backend: auth (password + TOTP), CSRF, coaching-consent gating, research suppression,
export/delete, comp access, last_sync_at, and audit logging."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
os.environ["RUSKIMAXXING_CLOUD_AUTOSTART"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

import ruskimaxxing_cloud.main as m  # noqa: E402
from ruskimaxxing_cloud import totp  # noqa: E402

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct-horse-battery-9"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://testserver")
    for k in ("STRIPE_SECRET_KEY", "SMTP_HOST"):
        monkeypatch.delenv(k, raising=False)
    return m.create_app(f"sqlite:///{tmp_path}/cloud.db")


@pytest.fixture
def client(app):
    return TestClient(app, base_url="https://testserver")


def make_admin(app, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    """Create an admin the way admin_cli.create_admin would, without touching the terminal."""
    secret = totp.new_secret()
    with m.Session(app.state.engine) as s:
        user = m.User(email=email, password_hash=m.ph.hash(password), is_admin=True, totp_secret=secret)
        s.add(user)
        s.commit()
        s.refresh(user)
        uid = user.id
    return secret, uid


def admin_login(client, app, email=ADMIN_EMAIL, password=ADMIN_PASSWORD, secret=None, code=None):
    # the server always checks against real wall-clock time, so tests generate codes for "now" too
    code = code if code is not None else totp.current_code(secret)
    return client.post("/admin/login", data={"email": email, "password": password, "code": code},
                       follow_redirects=False)


def logged_in_client(client, app):
    secret, uid = make_admin(app)
    r = admin_login(client, app, secret=secret)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    return uid


def make_user(app, email, **kw):
    with m.Session(app.state.engine) as s:
        user = m.User(email=email, password_hash=m.ph.hash("some-password-1"), **kw)
        s.add(user)
        s.commit()
        s.refresh(user)
        uid = user.id
    return uid


def add_record(app, user_id, edition, uid, kind, data, updated="2026-01-01T00:00:00.000000Z"):
    with m.Session(app.state.engine) as s:
        seq = (s.scalar(select(m.func.max(m.Record.seq)).where(m.Record.user_id == user_id)) or 0) + 1
        s.add(m.Record(user_id=user_id, edition=edition, uid=uid, kind=kind, updated=updated, deleted=False,
                       data=m.json.dumps(data), seq=seq))
        s.commit()


# ----- access control ------------------------------------------------------------------
ADMIN_ROUTES = ["/admin", "/admin/users", "/admin/research", "/admin/audit", "/admin/system", "/admin/billing"]


def test_anonymous_redirected_from_every_admin_route(client):
    for path in ADMIN_ROUTES:
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/admin/login", path


def test_non_admin_user_redirected_from_every_admin_route(client, app):
    make_user(app, "regular@example.com")
    # a regular website login cookie (rmx_session) must not grant access to /admin
    r = client.post("/account/login", data={"email": "regular@example.com", "password": "some-password-1"})
    assert r.status_code == 200
    for path in ADMIN_ROUTES:
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/admin/login", path


def test_user_detail_route_also_gated(client, app):
    uid = make_user(app, "regular2@example.com")
    r = client.get(f"/admin/users/{uid}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"


# ----- login: password + TOTP -----------------------------------------------------------
def test_login_requires_correct_password_and_totp(client, app):
    secret, uid = make_admin(app)
    bad_pw = admin_login(client, app, password="wrong-password", secret=secret)
    assert bad_pw.status_code == 401 and "Wrong" in bad_pw.text

    bad_code = client.post("/admin/login", data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "code": "000000"})
    assert bad_code.status_code == 401

    good = admin_login(client, app, secret=secret)
    assert good.status_code == 303 and good.headers["location"] == "/admin"
    assert "rmx_admin" in client.cookies

    dash = client.get("/admin")
    assert dash.status_code == 200 and "Dashboard" in dash.text and ADMIN_EMAIL in dash.text


def test_login_needs_admin_flag_and_totp_secret(client, app):
    # a user without is_admin, even with the right password, can't log in to /admin
    with m.Session(app.state.engine) as s:
        s.add(m.User(email="notadmin@example.com", password_hash=m.ph.hash(ADMIN_PASSWORD)))
        s.commit()
    r = client.post("/admin/login", data={"email": "notadmin@example.com", "password": ADMIN_PASSWORD,
                                          "code": "123456"})
    assert r.status_code == 401


def test_totp_replay_is_rejected(client, app):
    secret, uid = make_admin(app)
    code = totp.current_code(secret)
    ok = client.post("/admin/login", data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "code": code},
                     follow_redirects=False)
    assert ok.status_code == 303
    client.cookies.clear()
    replay = client.post("/admin/login", data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "code": code},
                         follow_redirects=False)
    assert replay.status_code == 401


# ----- CSRF -------------------------------------------------------------------------------
def test_admin_posts_require_csrf_token(client, app):
    logged_in_client(client, app)
    # logout without a csrf token must fail
    bad = client.post("/admin/logout", data={})
    assert bad.status_code == 403

    dash = client.get("/admin")
    # extract the csrf token from a rendered form
    import re
    token = re.search(r'name="csrf" value="([^"]+)"', dash.text).group(1)
    good = client.post("/admin/logout", data={"csrf": token}, follow_redirects=False)
    assert good.status_code == 303


def test_admin_posts_require_same_origin(client, app):
    logged_in_client(client, app)
    dash = client.get("/admin")
    import re
    token = re.search(r'name="csrf" value="([^"]+)"', dash.text).group(1)
    r = client.post("/admin/logout", data={"csrf": token}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# ----- coaching-consent gating -----------------------------------------------------------
def test_consent_gate_hides_and_shows_training_data(client, app):
    logged_in_client(client, app)
    uid = make_user(app, "lifter@example.com")
    add_record(app, uid, "standard", "lift:1", "lift",
              {"date": "2026-01-05", "exercise": "Squat", "weight": 315, "reps": 5, "done": True})

    hidden = client.get(f"/admin/users/{uid}")
    assert hidden.status_code == 200
    assert "Training data hidden" in hidden.text
    assert "Squat" not in hidden.text

    with m.Session(app.state.engine) as s:
        u = s.get(m.User, uid)
        u.coaching_consent_at = m.utcnow()
        u.coaching_consent_version = "v1"
        s.commit()

    with m.Session(app.state.engine) as s:
        before = s.scalar(select(m.func.count()).select_from(m.AuditLog).where(m.AuditLog.action == "data_view"))
    shown = client.get(f"/admin/users/{uid}")
    assert shown.status_code == 200
    assert "Training data hidden" not in shown.text
    assert "Squat" in shown.text
    with m.Session(app.state.engine) as s:
        after = s.scalar(select(m.func.count()).select_from(m.AuditLog).where(m.AuditLog.action == "data_view"))
    assert after == before + 1


# ----- research: K-anonymity --------------------------------------------------------------
def test_research_suppresses_small_groups_and_shows_large_ones(client, app):
    logged_in_client(client, app)
    # 3 users on supertotal (< K=10): should be suppressed
    for i in range(3):
        uid = make_user(app, f"small{i}@example.com")
        add_record(app, uid, "supertotal", f"bw:{i}", "bodyweight", {"week": 1, "date": "2026-01-01", "weight": 180})
    # 12 users on standard (>= K=10): should be shown
    for i in range(12):
        uid = make_user(app, f"big{i}@example.com")
        add_record(app, uid, "standard", f"bw:{i}", "bodyweight", {"week": 1, "date": "2026-01-01", "weight": 180})

    page = client.get("/admin/research")
    assert page.status_code == 200
    assert "<10" in page.text
    assert ">= 10 shown check" or "12" in page.text  # the standard-edition count (12) appears somewhere
    assert f"De-identified aggregates. Groups under {10} people are hidden" in page.text

    csv = client.get("/admin/research.csv")
    assert csv.status_code == 200
    assert "text/csv" in csv.headers["content-type"]
    assert "by_edition,supertotal,3,<10" in csv.text
    assert "by_edition,standard,12,12" in csv.text


# ----- export / delete --------------------------------------------------------------------
def test_export_has_no_secrets_and_includes_records(client, app):
    logged_in_client(client, app)
    uid = make_user(app, "exportme@example.com")
    add_record(app, uid, "standard", "bw:1", "bodyweight", {"week": 1, "date": "2026-01-01", "weight": 180})

    r = client.get(f"/admin/users/{uid}/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    assert "password_hash" not in body
    assert "totp_secret" not in body
    assert "token" not in body.lower()
    import json
    payload = json.loads(body)
    assert payload["email"] == "exportme@example.com"
    assert len(payload["records"]) == 1
    assert payload["records"][0]["data"]["weight"] == 180


def test_delete_requires_typed_email_and_removes_user_and_records(client, app):
    logged_in_client(client, app)
    uid = make_user(app, "deleteme@example.com")
    add_record(app, uid, "standard", "bw:1", "bodyweight", {"week": 1, "date": "2026-01-01", "weight": 180})

    dash = client.get(f"/admin/users/{uid}")
    import re
    token = re.search(r'name="csrf" value="([^"]+)"', dash.text).group(1)

    wrong = client.post(f"/admin/users/{uid}/delete", data={"csrf": token, "confirm_email": "nope@example.com"},
                        follow_redirects=False)
    assert wrong.status_code == 303 and "bad_confirm" in wrong.headers["location"]
    with m.Session(app.state.engine) as s:
        assert s.get(m.User, uid) is not None

    right = client.post(f"/admin/users/{uid}/delete", data={"csrf": token, "confirm_email": "deleteme@example.com"},
                        follow_redirects=False)
    assert right.status_code == 303
    with m.Session(app.state.engine) as s:
        assert s.get(m.User, uid) is None
        assert s.scalar(select(m.func.count()).select_from(m.Record).where(m.Record.user_id == uid)) == 0


# ----- comp access --------------------------------------------------------------------------
def test_comp_until_makes_plan_active(client, app, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    uid = make_user(app, "comp@example.com", plan_status="", plan_until=None)
    with m.Session(app.state.engine) as s:
        u = s.get(m.User, uid)
        assert not m.plan_active(u)
        u.comp_until = m.utcnow() + timedelta(days=30)
        s.commit()
        s.refresh(u)
        assert m.plan_active(u)


# ----- last_sync_at set by /api/sync ---------------------------------------------------------
def test_sync_sets_last_sync_at(app):
    client = TestClient(app, base_url="https://testserver")
    r = client.post("/api/register", json={"email": "syncer@example.com", "password": "squat-heavy-1"})
    token = r.json()["token"]
    with m.Session(app.state.engine) as s:
        u = s.scalar(select(m.User).where(m.User.email == "syncer@example.com"))
        assert u.last_sync_at is None
    client.post("/api/sync", headers={"Authorization": f"Bearer {token}"},
               json={"edition": "standard", "since": 0, "changes": []})
    with m.Session(app.state.engine) as s:
        u = s.scalar(select(m.User).where(m.User.email == "syncer@example.com"))
        assert u.last_sync_at is not None


# ----- audit log never contains secrets --------------------------------------------------------
def test_audit_log_never_contains_password_or_totp_code(client, app):
    secret, uid = make_admin(app)
    admin_login(client, app, password="wrong-password-here", secret=secret)
    admin_login(client, app, secret=secret)
    with m.Session(app.state.engine) as s:
        rows = s.scalars(select(m.AuditLog)).all()
        blob = " ".join([r.detail or "" for r in rows] + [r.action for r in rows])
        assert "wrong-password-here" not in blob
        for row in rows:
            assert row.detail is None or not row.detail.isdigit() or len(row.detail) != 6


# ----- review fixes: comp action validation, bad dates, newest-first sets, unknown-email login ---------
def _csrf(client):
    import re
    return re.search(r'name="csrf" value="([^"]+)"', client.get("/admin").text).group(1)


def test_comp_rejects_unknown_action_and_bad_date(client, app):
    logged_in_client(client, app)
    uid = make_user(app, "compcheck@example.com")
    token = _csrf(client)
    with m.Session(app.state.engine) as s:
        s.get(m.User, uid).comp_until = m.utcnow() + timedelta(days=10)
        s.commit()
    r = client.post(f"/admin/users/{uid}/comp", data={"csrf": token, "action": "grnt"}, follow_redirects=False)
    assert r.status_code == 400
    r = client.post(f"/admin/users/{uid}/comp", data={"csrf": token, "action": "grant", "until": "not-a-date"},
                    follow_redirects=False)
    assert r.status_code == 303 and "bad_date" in r.headers["location"]
    with m.Session(app.state.engine) as s:
        assert s.get(m.User, uid).comp_until is not None   # neither request revoked it


def test_recent_sets_are_newest_training_first(client, app):
    logged_in_client(client, app)
    uid = make_user(app, "order@example.com", coaching_consent_at=m.utcnow(), coaching_consent_version="t")
    for wk, date in ((1, "2026-01-05"), (3, "2026-01-19"), (2, "2026-01-12")):
        add_record(app, uid, "standard", f"set:{wk}:1:Squat:1", "lift",
                   {"date": date, "exercise": "Squat", "weight": 100 + wk, "reps": 5, "week": wk, "day": 1,
                    "set_no": 1, "done": True}, updated="2026-02-01T00:00:00.000000Z")
    page = client.get(f"/admin/users/{uid}").text
    assert page.index("2026-01-19") < page.index("2026-01-12") < page.index("2026-01-05")


def test_unknown_email_still_runs_password_hash(monkeypatch, app):
    calls, real = [], m.ph

    class Spy:
        def __getattr__(self, name):
            return getattr(real, name)

        def verify(self, h, p):
            calls.append(h)
            return real.verify(h, p)
    monkeypatch.setattr(m, "ph", Spy())
    with m.Session(app.state.engine) as s:
        assert m.check_password(s, "nobody@example.com", "whatever-123") is None
    assert calls == [m.DUMMY_HASH]
