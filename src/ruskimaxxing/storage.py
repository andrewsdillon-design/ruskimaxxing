"""Local SQLite storage for settings, lift log and body measurements."""

import sqlite3
from datetime import date
from pathlib import Path

from ruskimaxxing.edition import EDITION
from ruskimaxxing.tracking import BodyFat, BodyWeight, LogEntry

DEFAULT_PATH = Path.home() / ".ruskimaxxing" / ("data.db" if EDITION == "standard" else f"data-{EDITION}.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL, exercise TEXT NOT NULL, weight REAL NOT NULL, reps INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'training', note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS bodyweight (week INTEGER PRIMARY KEY, date TEXT NOT NULL, weight REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bodyfat (
    month INTEGER PRIMARY KEY, date TEXT NOT NULL, percent REAL NOT NULL,
    method TEXT NOT NULL, weight REAL);
"""


class Store:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # settings
    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))

    # lifts
    def add_lift(self, entry: LogEntry) -> LogEntry:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO lifts (date, exercise, weight, reps, kind, note) VALUES (?,?,?,?,?,?)",
                (entry.date.isoformat(), entry.exercise, entry.weight, entry.reps, entry.kind, entry.note))
        return LogEntry(entry.date, entry.exercise, entry.weight, entry.reps, entry.kind, entry.note, cur.lastrowid)

    def delete_lift(self, entry_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM lifts WHERE id=?", (entry_id,))

    def lifts(self) -> list[LogEntry]:
        rows = self.db.execute("SELECT id, date, exercise, weight, reps, kind, note FROM lifts ORDER BY date, id")
        return [LogEntry(date.fromisoformat(d), ex, w, r, k, n, i) for i, d, ex, w, r, k, n in rows]

    # body - bodyweight is one value per program week, body fat one per month
    def set_bodyweight(self, bw: BodyWeight) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO bodyweight VALUES (?,?,?)",
                            (bw.week, bw.date.isoformat(), bw.weight))

    def delete_bodyweight(self, week: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM bodyweight WHERE week=?", (week,))

    def bodyweights(self) -> list[BodyWeight]:
        rows = self.db.execute("SELECT week, date, weight FROM bodyweight ORDER BY week")
        return [BodyWeight(w, date.fromisoformat(d), x) for w, d, x in rows]

    def set_bodyfat(self, bf: BodyFat) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO bodyfat VALUES (?,?,?,?,?)",
                            (bf.month, bf.date.isoformat(), bf.percent, bf.method, bf.weight))

    def delete_bodyfat(self, month: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM bodyfat WHERE month=?", (month,))

    def bodyfats(self) -> list[BodyFat]:
        rows = self.db.execute("SELECT month, date, percent, method, weight FROM bodyfat ORDER BY month")
        return [BodyFat(m, date.fromisoformat(d), p, meth, w) for m, d, p, meth, w in rows]
