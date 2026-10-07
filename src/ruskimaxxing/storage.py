"""Local SQLite storage for settings, lift log and body measurements.

Every record carries a stable uid and an `updated` timestamp, and deletions leave
a tombstone, so the cloud backup (sync.py) can send only what changed and resolve
edits from two devices by keeping the newest ("last write wins").
"""

import dataclasses
import json
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from ruskimaxxing.edition import EDITION
from ruskimaxxing.tracking import BodyFat, BodyWeight, LogEntry

DEFAULT_PATH = Path.home() / ".ruskimaxxing" / ("data.db" if EDITION == "standard" else f"data-{EDITION}.db")

# Settings that belong to the lifter (synced); everything else (e.g. cloud login) stays on the device
SYNCED_SETTINGS = ("name", "units", "increment", "start", "height", "bodyweight_start", "bodyfat_start",
                   "bodyfat_method", "age", "sex")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL, exercise TEXT NOT NULL, weight REAL NOT NULL, reps INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'training', note TEXT NOT NULL DEFAULT '',
    week INTEGER, day INTEGER, set_no INTEGER, rpe REAL, done INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS bodyweight (week INTEGER PRIMARY KEY, date TEXT NOT NULL, weight REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bodyfat (
    month INTEGER PRIMARY KEY, date TEXT NOT NULL, percent REAL NOT NULL,
    method TEXT NOT NULL, weight REAL);
CREATE TABLE IF NOT EXISTS tombstones (uid TEXT PRIMARY KEY, kind TEXT NOT NULL, updated TEXT NOT NULL);
"""

LIFT_FIELDS = ("date", "exercise", "weight", "reps", "kind", "note", "week", "day", "set_no", "rpe", "done")


def now() -> str:
    """UTC timestamp; ISO strings in this fixed format compare correctly as text."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def set_uid(week: int, day: int, exercise: str, set_no: int) -> str:
    """Program sets have a deterministic id, so re-saving a workout updates instead of duplicating."""
    return f"set:{week}:{day}:{exercise}:{set_no}"


class Store:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # the apps run cloud sync in a worker thread (one call at a time), so allow use off the main thread
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        """Bring databases created by older versions up to date."""
        def columns(table):
            return {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}

        with self.db:
            have = columns("lifts")
            for col, decl in (("week", "INTEGER"), ("day", "INTEGER"), ("set_no", "INTEGER"),
                              ("rpe", "REAL"), ("done", "INTEGER NOT NULL DEFAULT 1"),
                              ("uid", "TEXT"), ("updated", "TEXT")):
                if col not in have:
                    self.db.execute(f"ALTER TABLE lifts ADD COLUMN {col} {decl}")
            for table in ("bodyweight", "bodyfat", "settings"):
                if "updated" not in columns(table):
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN updated TEXT")
            # give pre-sync rows their ids and timestamps
            stamp = now()
            for row_id, week, day, exercise, set_no in self.db.execute(
                    "SELECT id, week, day, exercise, set_no FROM lifts WHERE uid IS NULL").fetchall():
                uid = set_uid(week, day, exercise, set_no) if week is not None and set_no else uuid.uuid4().hex
                self.db.execute("UPDATE lifts SET uid=?, updated=? WHERE id=?", (uid, stamp, row_id))
            for table in ("bodyweight", "bodyfat", "settings"):
                self.db.execute(f"UPDATE {table} SET updated=? WHERE updated IS NULL", (stamp,))
            self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS lifts_uid ON lifts(uid)")

    def close(self):
        self.db.close()

    def _tombstone(self, uid: str, kind: str, stamp: str | None = None):
        self.db.execute("INSERT OR REPLACE INTO tombstones VALUES (?,?,?)", (uid, kind, stamp or now()))

    def _clear_tombstone(self, uid: str):
        self.db.execute("DELETE FROM tombstones WHERE uid=?", (uid,))

    # settings
    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value, stamp: str | None = None) -> None:
        value = str(value)
        with self.db:
            if self.get(key) == value and stamp is None:
                return  # unchanged: don't mark it as a new edit
            self.db.execute("INSERT OR REPLACE INTO settings (key, value, updated) VALUES (?,?,?)",
                            (key, value, stamp or now()))

    # lifts
    _COLS = "date, exercise, weight, reps, kind, note, week, day, set_no, rpe, done"

    def _insert(self, e: LogEntry, uid: str | None = None, stamp: str | None = None) -> LogEntry:
        if uid is None:
            uid = set_uid(e.week, e.day, e.exercise, e.set_no) if e.week is not None and e.set_no else uuid.uuid4().hex
        self.db.execute("DELETE FROM lifts WHERE uid=?", (uid,))
        self._clear_tombstone(uid)
        cur = self.db.execute(
            f"INSERT INTO lifts ({self._COLS}, uid, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.date.isoformat(), e.exercise, e.weight, e.reps, e.kind, e.note,
             e.week, e.day, e.set_no, e.rpe, int(e.done), uid, stamp or now()))
        return dataclasses.replace(e, id=cur.lastrowid)

    def add_lift(self, entry: LogEntry) -> LogEntry:
        with self.db:
            return self._insert(entry)

    def delete_lift(self, entry_id: int) -> None:
        with self.db:
            row = self.db.execute("SELECT uid FROM lifts WHERE id=?", (entry_id,)).fetchone()
            self.db.execute("DELETE FROM lifts WHERE id=?", (entry_id,))
            if row and row[0]:
                self._tombstone(row[0], "lift")

    def _rows(self, where: str = "", args=()) -> list[LogEntry]:
        rows = self.db.execute(f"SELECT id, {self._COLS} FROM lifts {where} ORDER BY date, id", args)
        return [LogEntry(date.fromisoformat(d), ex, w, r, k, n, i, wk, dy, sn, rpe, bool(done))
                for i, d, ex, w, r, k, n, wk, dy, sn, rpe, done in rows]

    def lifts(self) -> list[LogEntry]:
        return self._rows()

    def workout(self, week: int, day: int) -> list[LogEntry]:
        """Every set saved for one program session, done or not."""
        return self._rows("WHERE week=? AND day=?", (week, day))

    def save_workout(self, week: int, day: int, entries: list[LogEntry]) -> list[LogEntry]:
        """Replace everything saved for one session with `entries`."""
        with self.db:
            old = {r[0] for r in self.db.execute("SELECT uid FROM lifts WHERE week=? AND day=?", (week, day))}
            self.db.execute("DELETE FROM lifts WHERE week=? AND day=?", (week, day))
            saved = [self._insert(dataclasses.replace(e, week=week, day=day)) for e in entries]
            new = {set_uid(week, day, e.exercise, e.set_no) for e in saved}
            for uid in old - new:
                if uid:
                    self._tombstone(uid, "lift")
            return saved

    # body - bodyweight is one value per program week, body fat one per month
    def set_bodyweight(self, bw: BodyWeight, stamp: str | None = None) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO bodyweight (week, date, weight, updated) VALUES (?,?,?,?)",
                            (bw.week, bw.date.isoformat(), bw.weight, stamp or now()))
            self._clear_tombstone(f"bw:{bw.week}")

    def delete_bodyweight(self, week: int) -> None:
        with self.db:
            if self.db.execute("DELETE FROM bodyweight WHERE week=?", (week,)).rowcount:
                self._tombstone(f"bw:{week}", "bodyweight")

    def bodyweights(self) -> list[BodyWeight]:
        rows = self.db.execute("SELECT week, date, weight FROM bodyweight ORDER BY week")
        return [BodyWeight(w, date.fromisoformat(d), x) for w, d, x in rows]

    def set_bodyfat(self, bf: BodyFat, stamp: str | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO bodyfat (month, date, percent, method, weight, updated) VALUES (?,?,?,?,?,?)",
                (bf.month, bf.date.isoformat(), bf.percent, bf.method, bf.weight, stamp or now()))
            self._clear_tombstone(f"bf:{bf.month}")

    def delete_bodyfat(self, month: int) -> None:
        with self.db:
            if self.db.execute("DELETE FROM bodyfat WHERE month=?", (month,)).rowcount:
                self._tombstone(f"bf:{month}", "bodyfat")

    def bodyfats(self) -> list[BodyFat]:
        rows = self.db.execute("SELECT month, date, percent, method, weight FROM bodyfat ORDER BY month")
        return [BodyFat(m, date.fromisoformat(d), p, meth, w) for m, d, p, meth, w in rows]

    # ----- sync -------------------------------------------------------------------
    def changes(self, since: str | None = None) -> list[dict]:
        """Records changed after `since` (all when None): {uid, kind, updated, deleted, data}."""
        after = since or ""
        out = []
        for row in self.db.execute(f"SELECT uid, updated, {', '.join(LIFT_FIELDS)} FROM lifts WHERE updated > ?",
                                   (after,)):
            data = dict(zip(LIFT_FIELDS, row[2:]))
            data["done"] = bool(data["done"])
            out.append({"uid": row[0], "kind": "lift", "updated": row[1], "deleted": False, "data": data})
        for week, d, weight, upd in self.db.execute(
                "SELECT week, date, weight, updated FROM bodyweight WHERE updated > ?", (after,)):
            out.append({"uid": f"bw:{week}", "kind": "bodyweight", "updated": upd, "deleted": False,
                        "data": {"week": week, "date": d, "weight": weight}})
        for m, d, pct, meth, w, upd in self.db.execute(
                "SELECT month, date, percent, method, weight, updated FROM bodyfat WHERE updated > ?", (after,)):
            out.append({"uid": f"bf:{m}", "kind": "bodyfat", "updated": upd, "deleted": False,
                        "data": {"month": m, "date": d, "percent": pct, "method": meth, "weight": w}})
        marks = ",".join("?" * len(SYNCED_SETTINGS))
        for key, value, upd in self.db.execute(
                f"SELECT key, value, updated FROM settings WHERE updated > ? AND key IN ({marks})",
                (after, *SYNCED_SETTINGS)):
            out.append({"uid": f"setting:{key}", "kind": "setting", "updated": upd, "deleted": False,
                        "data": {"key": key, "value": value}})
        for uid, kind, upd in self.db.execute("SELECT uid, kind, updated FROM tombstones WHERE updated > ?",
                                              (after,)):
            out.append({"uid": uid, "kind": kind, "updated": upd, "deleted": True, "data": None})
        return out

    def _local_updated(self, uid: str, kind: str) -> str:
        row = self.db.execute("SELECT updated FROM tombstones WHERE uid=?", (uid,)).fetchone()
        if kind == "lift":
            live = self.db.execute("SELECT updated FROM lifts WHERE uid=?", (uid,)).fetchone()
        elif kind == "bodyweight":
            live = self.db.execute("SELECT updated FROM bodyweight WHERE week=?", (int(uid[3:]),)).fetchone()
        elif kind == "bodyfat":
            live = self.db.execute("SELECT updated FROM bodyfat WHERE month=?", (int(uid[3:]),)).fetchone()
        else:
            live = self.db.execute("SELECT updated FROM settings WHERE key=?", (uid[8:],)).fetchone()
        return max((r[0] or "" for r in (row, live) if r), default="")

    def apply(self, records: list[dict]) -> int:
        """Apply records from the cloud where they are newer than ours. Returns how many changed."""
        applied = 0
        for rec in records:
            uid, kind, stamp = rec["uid"], rec["kind"], rec["updated"]
            if stamp <= self._local_updated(uid, kind):
                continue
            data = rec.get("data") or {}
            with self.db:
                if rec.get("deleted"):
                    if kind == "lift":
                        self.db.execute("DELETE FROM lifts WHERE uid=?", (uid,))
                    elif kind == "bodyweight":
                        self.db.execute("DELETE FROM bodyweight WHERE week=?", (int(uid[3:]),))
                    elif kind == "bodyfat":
                        self.db.execute("DELETE FROM bodyfat WHERE month=?", (int(uid[3:]),))
                    self._tombstone(uid, kind, stamp)
                elif kind == "lift":
                    entry = LogEntry(date.fromisoformat(data["date"]), data["exercise"], data["weight"], data["reps"],
                                     data["kind"], data["note"], None, data["week"], data["day"], data["set_no"],
                                     data["rpe"], bool(data["done"]))
                    self._insert(entry, uid=uid, stamp=stamp)
                elif kind == "bodyweight":
                    self.db.execute("INSERT OR REPLACE INTO bodyweight (week, date, weight, updated) VALUES (?,?,?,?)",
                                    (data["week"], data["date"], data["weight"], stamp))
                    self._clear_tombstone(uid)
                elif kind == "bodyfat":
                    self.db.execute("INSERT OR REPLACE INTO bodyfat (month, date, percent, method, weight, updated) "
                                    "VALUES (?,?,?,?,?,?)", (data["month"], data["date"], data["percent"],
                                                             data["method"], data["weight"], stamp))
                    self._clear_tombstone(uid)
                elif kind == "setting" and data.get("key") in SYNCED_SETTINGS:
                    self.db.execute("INSERT OR REPLACE INTO settings (key, value, updated) VALUES (?,?,?)",
                                    (data["key"], str(data["value"]), stamp))
            applied += 1
        return applied

    def dump(self) -> str:
        """Everything as JSON (used for tests and manual backups)."""
        return json.dumps(self.changes(), sort_keys=True)
