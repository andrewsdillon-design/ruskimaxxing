"""Regenerate the phone screenshots: runs the phone UI on GTK in a phone-sized window.

    pip install toga-gtk~=0.5.6    (Linux; needs GTK - see README)
    xvfb-run -a -s "-screen 0 1000x900x24" python packaging/phone_screenshots.py docs/screenshots
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packaging"))
from PIL import ImageGrab
import ruskimaxxing_mobile.app as m
from screenshots import demo_store

out = Path(sys.argv[1]); tmp = Path(tempfile.mkdtemp())
demo_store(tmp / "data.db").db.close()

os.environ["RUSKIMAXXING_DATA_DIR"] = str(tmp)

class App(m.RuskiMaxxing):
    def startup(self):
        super().startup()
        self.main_window.size = (400, 820)
        self.main_window.position = (0, 0)
        self.week = 1; self.render_workout()
        self.loop.call_later(2.5, self.shoot, 0)
    def shoot(self, i):
        names = ["workout", "progress", "prs", "body", "setup"]
        if i:
            ImageGrab.grab(bbox=(0, 24, 400, 820)).save(out / f"phone_{names[i-1]}.png")  # skip GTK menu bar
        if i == len(names):
            self.request_exit(); os._exit(0)
        self.tabs.current_tab = i
        self.loop.call_later(1.5, self.shoot, i + 1)

App("RuskiMaxxing", "io.github.andrewsdillondesign.ruskimaxxing_mobile").main_loop()
