"""Regenerate the README screenshots with demo data.

Needs a display. On a headless Linux box:
    xvfb-run -a -s "-screen 0 1300x900x24" python packaging/screenshots.py
Set RUSKIMAXXING_EDITION=supertotal for the supertotal edition.
"""

import sys
import tempfile
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path

from PIL import ImageGrab

import ruskimaxxing.gui as g
from ruskimaxxing.exercises import MAIN
from ruskimaxxing.storage import Store
from ruskimaxxing.tracking import BodyFat, BodyWeight, LogEntry

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
W, H = 1180, 820
START = date(2026, 1, 5)
STARTING = {"Squat": 225, "Bench Press": 165, "Deadlift": 275, "Overhead Press": 105, "Snatch": 95,
            "Clean & Jerk": 125}


def demo_store(path: Path) -> Store:
    st = Store(path)
    for k, v in dict(units="lb", increment="5", start=START.isoformat(), height="70", bodyweight_start="175",
                     bodyfat_start="20", bodyfat_method="Bod Pod").items():
        st.set(k, v)
    pre = START - timedelta(weeks=1)
    for lift in MAIN:
        st.add_lift(LogEntry(pre, lift, STARTING[lift], 5 if STARTING[lift] > 125 else 3, "baseline"))
    for ex, w in (("Box Jump", 20), ("Broad Jump", 84), ("Vertical Jump", 16)):
        st.add_lift(LogEntry(pre, ex, w, 1, "baseline"))
    for c in range(1, 4):  # three tested cycles of progress
        d = START + timedelta(weeks=12 * c - 1)
        for i, lift in enumerate(MAIN):
            st.add_lift(LogEntry(d, lift, round(STARTING[lift] * (1.1 + 0.07 * c) / 5) * 5, 1, "test"))
        for ex, base, step in (("Box Jump", 22, 5), ("Broad Jump", 86, 3), ("Vertical Jump", 17, 2)):
            st.add_lift(LogEntry(d + timedelta(days=2), ex, base + step * c, 1, "test"))
    for wk in range(0, 37):
        st.set_bodyweight(BodyWeight(wk, START + timedelta(weeks=wk - 1), round(175 + wk * 0.35, 1)))
    for m in range(1, 10):
        st.set_bodyfat(BodyFat(m, START + timedelta(weeks=(m - 1) * 4), round(20 - m * 0.3, 1), "Bod Pod",
                               round(175 + m * 1.4, 1)))
    return st


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    root = tk.Tk()
    g.apply_theme(root)
    root.geometry(f"{W}x{H}+0+0")
    app = g.App(root, demo_store(tmp / "demo.db"))
    # a half-logged workout for the Program shot
    app.week.set(app.week_labels[1])
    app.day_var.set(0)
    app.refresh()
    for b in app.wo_blocks[:2]:
        for v in b["vars"][: max(1, len(b["vars"]) - 1)]:
            v["done"].set(True)
    app.wo_blocks[1]["vars"][0]["rpe"].set("7.5")
    app.wo_blocks[1]["note_var"].set("Moved well - add 5 lb next week")
    app._save_workout(quiet=True)

    shots = [("start", 0), ("program", 1), ("progress", 2)]

    def shoot(i=0):
        if i == len(shots):
            root.destroy()
            return
        name, tab = shots[i]
        app.tabs.select(tab)
        root.update()
        root.after(500, lambda: (ImageGrab.grab(bbox=(0, 0, W, H)).save(OUT / f"{name}.png"), shoot(i + 1)))

    root.after(600, shoot)
    root.mainloop()
    print(f"wrote {', '.join(n for n, _ in shots)} to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
