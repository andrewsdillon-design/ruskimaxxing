"""Pure logic for the training streak / call-discount calculation (see streaks.py)."""

from datetime import date, datetime, timedelta

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ruskimaxxing_cloud.streaks import FORGIVE_WINDOW_DAYS, compute_streak, is_training_day  # noqa: E402

START = date(2026, 1, 5)  # a Monday -> scheduled Mon/Wed/Fri


def d(offset_days: int) -> date:
    return START + timedelta(days=offset_days)


def test_is_training_day_mon_wed_fri():
    assert is_training_day(d(0), START)      # Monday
    assert not is_training_day(d(1), START)  # Tuesday
    assert is_training_day(d(2), START)      # Wednesday
    assert not is_training_day(d(3), START)  # Thursday
    assert is_training_day(d(4), START)      # Friday
    assert not is_training_day(d(5), START)  # Saturday
    assert not is_training_day(d(6), START)  # Sunday
    assert is_training_day(d(7), START)      # next Monday


def test_no_checks_means_no_streak():
    r = compute_streak([], START, today=d(10))
    assert r.streak_start is None and r.streak_days == 0 and r.discount_pct == 0
    assert r.misses_forgiven_in_window == 0 and r.next_discount_at_days == 90
    assert r.checked_today is False


def test_perfect_streak_all_scheduled_days_checked():
    checks = [d(0), d(2), d(4), d(7), d(9), d(11)]
    r = compute_streak(checks, START, today=d(11))
    assert r.streak_start == d(0)
    assert r.streak_days == 12  # d(0)..d(11) inclusive
    assert r.checked_today is True
    assert r.today_is_training_day is True
    assert r.misses_forgiven_in_window == 0


def test_one_forgiven_miss_keeps_streak_alive():
    # miss Wednesday d(2), but no other miss within 30 days -> forgiven, streak intact
    checks = [d(0), d(4), d(7)]
    r = compute_streak(checks, START, today=d(7))
    assert r.streak_start == d(0)
    assert r.streak_days == d(7).toordinal() - d(0).toordinal() + 1
    assert r.misses_forgiven_in_window == 1


def test_second_miss_within_30_days_resets_streak():
    # miss d(2) (forgiven), then miss d(4) only 2 days later -> second miss resets the streak.
    # Next accepted check is d(7): new streak starts there.
    checks = [d(0), d(7), d(9)]
    r = compute_streak(checks, START, today=d(9))
    assert r.streak_start == d(7)
    assert r.streak_days == d(9).toordinal() - d(7).toordinal() + 1


def test_miss_after_31_days_forgiven_again():
    # First streak start d(0). Miss d(2) forgiven. A second miss more than 30 days later is also forgiven
    # (each miss only resets the streak if *another* miss happened in the preceding 30 days).
    miss1 = d(2)
    end = 2 + 40  # comfortably more than 30 days past miss1
    while not is_training_day(d(end), START):
        end += 1
    miss2 = d(end)
    assert (miss2 - miss1).days > FORGIVE_WINDOW_DAYS

    after = end + 1
    while not is_training_day(d(after), START):
        after += 1
    today = d(after)  # a training day strictly after miss2, so miss2 has actually occurred and can be tallied

    all_training_days = [day for o in range(0, after + 1) if is_training_day(day := d(o), START)]
    checks = [day for day in all_training_days if day not in (miss1, miss2)]
    r = compute_streak(checks, START, today=today)
    assert r.streak_start == d(0)
    assert r.misses_forgiven_in_window == 1  # only the recent forgiven miss (miss1 is now outside the window)


def test_today_not_counted_as_missed_even_if_unchecked():
    checks = [d(0), d(2)]
    r = compute_streak(checks, START, today=d(4))  # d(4) is a training day, not yet checked, but it's "today"
    assert r.today_is_training_day is True
    assert r.checked_today is False
    assert r.streak_start == d(0)
    assert r.streak_days == d(4).toordinal() - d(0).toordinal() + 1


def test_discount_thresholds():
    def days_streak(n):
        # a streak with no misses at all: checks only every training day for n days is unnecessary;
        # we can simulate a streak_start n-1 days before today with zero misses by only checking start+today
        # and disabling checks in between is invalid (misses would occur). Instead directly test discount math
        # via a fully-checked run - use a small helper that always checks every scheduled day.
        start = date(2020, 1, 6)  # Monday
        today = start + timedelta(days=n - 1)
        checks = []
        day = start
        while day <= today:
            if is_training_day(day, start):
                checks.append(day)
            day += timedelta(days=1)
        return compute_streak(checks, start, today)

    assert days_streak(89).discount_pct == 0
    assert days_streak(90).discount_pct == 10
    assert days_streak(450).discount_pct == 50
    assert days_streak(900).discount_pct == 50


def test_next_discount_at_days_caps_at_max():
    start = date(2020, 1, 6)
    today = start + timedelta(days=449)
    checks = []
    day = start
    while day <= today:
        if is_training_day(day, start):
            checks.append(day)
        day += timedelta(days=1)
    r = compute_streak(checks, start, today)
    assert r.discount_pct == 50
    assert r.next_discount_at_days is None


# ----- /api/streak endpoint (image handling, validation, in-memory-only processing) --------

import hashlib
import hmac
import io
import json as _json
import os
import sys
import time
from pathlib import Path as _Path

import pytest as _pytest

_pytest.importorskip("fastapi")
_pytest.importorskip("PIL")
os.environ["RUSKIMAXXING_CLOUD_AUTOSTART"] = "0"
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

import ruskimaxxing_cloud.main as m  # noqa: E402

FIXED_NOW = datetime(2026, 3, 2, 12, 0, 0)  # a Monday
START_DATE = "2026-03-02"


def random_jpeg_bytes(seed: int = 0, exif_dt: datetime | None = None) -> bytes:
    import random
    rng = random.Random(seed)
    img = Image.new("RGB", (64, 64))
    img.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(64 * 64)])
    buf = io.BytesIO()
    if exif_dt is not None:
        exif = Image.Exif()
        exif[0x9003] = exif_dt.strftime("%Y:%m:%d %H:%M:%S")
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def app(tmp_path, monkeypatch):
    for k in ("STRIPE_SECRET_KEY", "SMTP_HOST"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PUBLIC_URL", "https://testserver")
    return m.create_app(f"sqlite:///{tmp_path}/cloud.db")


@pytest.fixture
def client(app):
    return TestClient(app, base_url="https://testserver")


class Clock:
    def __init__(self, dt):
        self.dt = dt

    def __call__(self):
        return self.dt


def register_with_program_year(client, app, monkeypatch, start_date=START_DATE):
    r = client.post("/api/register", json={"email": "lifter@example.com", "password": "squat-heavy"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    with m.Session(app.state.engine) as s:
        user_id = s.scalar(select(m.User.id).where(m.User.email == "lifter@example.com"))
        s.add(m.ProgramPurchase(user_id=user_id, year=2, amount_cents=19900, currency="usd",
                                purchased_at=m.utcnow()))
        s.commit()
    sync = {"edition": "standard", "since": 0, "changes": [
        {"uid": "setting:start", "kind": "setting", "updated": "2026-01-01T00:00:00.000000Z", "deleted": False,
         "data": {"key": "start", "value": start_date}}]}
    r = client.post("/api/sync", headers=headers, json=sync)
    assert r.status_code == 200
    return headers, user_id


def test_streak_rejects_without_a_paid_program_year(client, monkeypatch):
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    r = client.post("/api/register", json={"email": "free@example.com", "password": "squat-heavy"})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    photo = random_jpeg_bytes()
    r = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-02", "utc_offset_minutes": "0"},
                    files={"photo": ("a.jpg", photo, "image/jpeg")})
    assert r.status_code == 400 and "program year" in r.json()["detail"].lower()


def test_streak_accepts_a_fresh_photo_on_a_training_day(client, app, monkeypatch):
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, user_id = register_with_program_year(client, app, monkeypatch)
    photo = random_jpeg_bytes(seed=1)
    r = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-02", "utc_offset_minutes": "0"},
                    files={"photo": ("a.jpg", photo, "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["streak"]["streak_days"] == 1
    assert body["streak"]["checked_today"] is True
    assert body["streak"]["today_is_training_day"] is True

    with m.Session(app.state.engine) as s:
        rows = s.scalars(select(m.StreakCheck).where(m.StreakCheck.user_id == user_id)).all()
        assert len(rows) == 1
        assert rows[0].day.isoformat() == "2026-03-02"
        assert len(rows[0].phash) == 16  # only day/received_at/phash are kept - never the image bytes


def test_streak_rejects_non_training_day(client, app, monkeypatch):
    clock = Clock(datetime(2026, 3, 3, 12, 0, 0))  # Tuesday - not scheduled (Mon/Wed/Fri)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, _ = register_with_program_year(client, app, monkeypatch)
    photo = random_jpeg_bytes(seed=2)
    r = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-03", "utc_offset_minutes": "0"},
                    files={"photo": ("a.jpg", photo, "image/jpeg")})
    assert r.status_code == 400 and "training day" in r.json()["detail"].lower()


def test_streak_rejects_wrong_local_date(client, app, monkeypatch):
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, _ = register_with_program_year(client, app, monkeypatch)
    photo = random_jpeg_bytes(seed=3)
    # claims a local date that doesn't match server-now shifted by the given offset
    r = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-05", "utc_offset_minutes": "0"},
                    files={"photo": ("a.jpg", photo, "image/jpeg")})
    assert r.status_code == 400


def test_streak_rejects_second_check_same_day(client, app, monkeypatch):
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, _ = register_with_program_year(client, app, monkeypatch)
    data = {"local_date": "2026-03-02", "utc_offset_minutes": "0"}
    r1 = client.post("/api/streak", headers=headers, data=data,
                     files={"photo": ("a.jpg", random_jpeg_bytes(seed=4), "image/jpeg")})
    assert r1.status_code == 200
    r2 = client.post("/api/streak", headers=headers, data=data,
                     files={"photo": ("b.jpg", random_jpeg_bytes(seed=5), "image/jpeg")})
    assert r2.status_code == 400 and "already checked in" in r2.json()["detail"].lower()


def test_streak_rejects_duplicate_photo_on_a_later_day(client, app, monkeypatch):
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, _ = register_with_program_year(client, app, monkeypatch)
    photo = random_jpeg_bytes(seed=6)
    r1 = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-02", "utc_offset_minutes": "0"},
                     files={"photo": ("a.jpg", photo, "image/jpeg")})
    assert r1.status_code == 200

    clock.dt = datetime(2026, 3, 4, 12, 0, 0)  # next scheduled day: Wednesday
    r2 = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-04", "utc_offset_minutes": "0"},
                     files={"photo": ("a.jpg", photo, "image/jpeg")})
    assert r2.status_code == 400 and "already used" in r2.json()["detail"].lower()


def test_streak_rejects_non_image_upload(client, app, monkeypatch):
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, _ = register_with_program_year(client, app, monkeypatch)
    r = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-02", "utc_offset_minutes": "0"},
                    files={"photo": ("a.txt", b"not an image", "text/plain")})
    assert r.status_code == 400


def test_streak_rejects_offset_outside_valid_range(client, app, monkeypatch):
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, _ = register_with_program_year(client, app, monkeypatch)
    for bad_offset in (-721, 841):
        r = client.post("/api/streak", headers=headers,
                        data={"local_date": "2026-03-02", "utc_offset_minutes": str(bad_offset)},
                        files={"photo": ("a.jpg", random_jpeg_bytes(seed=20), "image/jpeg")})
        assert r.status_code == 400 and "invalid time zone" in r.json()["detail"].lower()


def test_streak_rejects_local_date_more_than_a_day_off_regardless_of_offset(client, app, monkeypatch):
    clock = Clock(FIXED_NOW)  # server UTC date is 2026-03-02
    monkeypatch.setattr(m, "utcnow", clock)
    headers, _ = register_with_program_year(client, app, monkeypatch)
    # claim a local_date 2 days away, paired with an offset engineered to satisfy the naive equality check
    r = client.post("/api/streak", headers=headers,
                    data={"local_date": "2026-03-04", "utc_offset_minutes": "840"},
                    files={"photo": ("a.jpg", random_jpeg_bytes(seed=21), "image/jpeg")})
    assert r.status_code == 400 and "invalid time zone" in r.json()["detail"].lower()


def test_streak_rejects_oversized_upload_without_reading_it_all(client, app, monkeypatch):
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, _ = register_with_program_year(client, app, monkeypatch)
    oversized = b"\xff" * (m.STREAK_MAX_UPLOAD_BYTES + 1024)
    r = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-02", "utc_offset_minutes": "0"},
                    files={"photo": ("a.jpg", oversized, "image/jpeg")})
    assert r.status_code == 400 and "too large" in r.json()["detail"].lower()


def test_streak_rejects_huge_dimension_image(client, app, monkeypatch):
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, _ = register_with_program_year(client, app, monkeypatch)
    # monkeypatch the pixel limit low so a small, cheap-to-generate image still trips the decompression-bomb
    # guard - this exercises the same code path a real 8000x8000 photo would (400, never 500)
    monkeypatch.setattr(m, "STREAK_MAX_PIXELS", 10)
    photo = random_jpeg_bytes(seed=22)
    r = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-02", "utc_offset_minutes": "0"},
                    files={"photo": ("a.jpg", photo, "image/jpeg")})
    assert r.status_code == 400


def test_streak_duplicate_via_unique_constraint_is_treated_as_already_checked_in(client, app, monkeypatch):
    """Simulate a race: a StreakCheck for today already exists (as if a concurrent request just inserted it),
    bypassing the earlier existence check - the DB unique constraint + IntegrityError handling must still
    produce the normal "already checked in today" 400, not a 500."""
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, user_id = register_with_program_year(client, app, monkeypatch)
    with m.Session(app.state.engine) as s:
        s.add(m.StreakCheck(user_id=user_id, day=date(2026, 3, 2), received_at=m.utcnow(), phash="0" * 16))
        s.commit()

    # force the earlier explicit existence check to miss, as if the concurrent insert weren't visible yet
    orig_scalar = m.Session.scalar

    def racy_scalar(self, stmt, *a, **kw):
        if "streak_checks" in str(stmt).lower():
            return None
        return orig_scalar(self, stmt, *a, **kw)

    monkeypatch.setattr(m.Session, "scalar", racy_scalar)
    photo = random_jpeg_bytes(seed=23)
    r = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-02", "utc_offset_minutes": "0"},
                    files={"photo": ("a.jpg", photo, "image/jpeg")})
    assert r.status_code == 400 and "already checked in" in r.json()["detail"].lower()

    with m.Session(app.state.engine) as s:
        rows = s.scalars(select(m.StreakCheck).where(m.StreakCheck.user_id == user_id)).all()
        assert len(rows) == 1  # no duplicate row was created


def test_streak_never_persists_the_photo_bytes(client, app, monkeypatch):
    """No column exists to store the photo, and the handler only ever keeps day/received_at/phash."""
    clock = Clock(FIXED_NOW)
    monkeypatch.setattr(m, "utcnow", clock)
    headers, user_id = register_with_program_year(client, app, monkeypatch)
    photo = random_jpeg_bytes(seed=7)
    r = client.post("/api/streak", headers=headers, data={"local_date": "2026-03-02", "utc_offset_minutes": "0"},
                    files={"photo": ("a.jpg", photo, "image/jpeg")})
    assert r.status_code == 200
    with m.Session(app.state.engine) as s:
        row = s.scalar(select(m.StreakCheck).where(m.StreakCheck.user_id == user_id))
        stored_columns = {c.name for c in m.StreakCheck.__table__.columns}
        assert stored_columns == {"id", "user_id", "day", "received_at", "phash"}
        for col in stored_columns:
            value = getattr(row, col)
            assert value is None or photo not in str(value).encode("utf-8", errors="ignore")


