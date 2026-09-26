"""Desktop app (Windows / macOS / Linux) built on tkinter.

Tabs: Start (intake, starting maxes, PR board, box jump standards, Prilepin's
chart) - Program (the year, log sets, weekly bodyweight) - PRs (every movement,
charted against bodyweight) - Body (weekly bodyweight, monthly body fat) - Log.
All data lives in a local SQLite file (see storage.py).
"""

import os
import sys
import threading
import time
import webbrowser
import tkinter as tk
from pathlib import Path
from datetime import date, timedelta
from tkinter import filedialog, messagebox, ttk

from ruskimaxxing import __version__
from ruskimaxxing import workout as wo
from ruskimaxxing.edition import app_name
from ruskimaxxing.excel import build_workbook
from ruskimaxxing.exercises import (CATALOG, JUMP_STANDARDS, LEVELS, MAIN, box_jump_targets,
                                   jump_level, jump_targets)
from ruskimaxxing.prilepin import ZONES
from ruskimaxxing.program import (MONTHS, SHOULDER_TIP, WEEKS, bodyfat_week, build_program,
                                  month_label, month_of, month_weeks, next_monday, week_label)
from ruskimaxxing.storage import Store
from ruskimaxxing.sync import Cloud, CloudError
from ruskimaxxing.updates import check_for_update, dismiss, dismissed
from ruskimaxxing.tracking import (BODYFAT_GUIDE, BODYFAT_METHODS, REP_MAX_COUNTS, BodyFat,
                                   BodyWeight, LogEntry, best_e1rm, e1rm_history, new_prs,
                                   rep_maxes)

DEFAULT_INCREMENT = {"lb": 5.0, "kg": 2.5}
INTAKE = (("name", "Name (optional)"), ("height", "Height"), ("bodyweight_start", "Starting bodyweight"),
          ("bodyfat_start", "Starting body fat % (optional)"), ("age", "Age (optional)"))
# Byzantine palette: imperial purple, gold, crimson, ivory / parchment
BYZ = {"purple": "#4A1942", "purple_dark": "#2E0C28", "gold": "#C9A227", "gold_light": "#F2D675",
       "crimson": "#8B1A1A", "ivory": "#F6EFDE", "parchment": "#EDE3CF", "ink": "#2B1B24", "field": "#FFF8E1"}
COLORS = ("#4A1942", "#8B1A1A", "#B8860B", "#1F6F5C", "#7B4FA0", "#5A5A5A")
ASSETS = Path(__file__).resolve().parent / "assets"
TITLE_FONT = ("Georgia", 22, "bold")


def apply_theme(root: tk.Tk) -> None:
    """Old-school Byzantine skin on top of ttk's 'clam' theme (works the same on every OS)."""
    P, bold = BYZ, ("TkDefaultFont", 10, "bold")
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=P["parchment"])
    st.configure(".", background=P["parchment"], foreground=P["ink"], fieldbackground=P["field"],
                 bordercolor=P["gold"], lightcolor=P["ivory"], darkcolor=P["gold"], troughcolor=P["ivory"])
    for w in ("TFrame", "TLabel", "TCheckbutton", "TRadiobutton"):
        st.configure(w, background=P["parchment"], foreground=P["ink"])
    st.configure("TLabelframe", background=P["parchment"], bordercolor=P["gold"])
    st.configure("TLabelframe.Label", background=P["parchment"], foreground=P["purple"], font=bold)
    st.configure("TNotebook", background=P["purple_dark"], borderwidth=0, tabmargins=(6, 6, 6, 0))
    st.configure("TNotebook.Tab", background=P["purple"], foreground=P["gold_light"], padding=(16, 6), font=bold,
                 bordercolor=P["gold"])
    st.map("TNotebook.Tab", background=[("selected", P["gold"]), ("active", P["crimson"])],
           foreground=[("selected", P["purple_dark"])])
    st.configure("TButton", background=P["purple"], foreground=P["gold_light"], bordercolor=P["gold"],
                 focuscolor=P["gold"], padding=(10, 4), font=bold)
    st.map("TButton", background=[("pressed", P["purple_dark"]), ("active", P["crimson"])])
    st.configure("Toolbutton", background=P["ivory"], foreground=P["purple"], padding=(10, 5), font=bold,
                 bordercolor=P["gold"])
    st.map("Toolbutton", background=[("selected", P["purple"]), ("active", P["gold_light"])],
           foreground=[("selected", P["gold_light"])])
    st.configure("Treeview", background=P["ivory"], fieldbackground=P["ivory"], foreground=P["ink"], rowheight=22)
    st.configure("Treeview.Heading", background=P["purple"], foreground=P["gold_light"], font=bold, relief="flat")
    st.map("Treeview.Heading", background=[("active", P["crimson"])])
    st.map("Treeview", background=[("selected", P["crimson"])], foreground=[("selected", P["ivory"])])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        st.configure(w, fieldbackground=P["field"], bordercolor=P["gold"], arrowcolor=P["purple"])
    st.configure("TSeparator", background=P["gold"])
    st.configure("Vertical.TScrollbar", background=P["purple"], arrowcolor=P["gold_light"], bordercolor=P["gold"])


def load_logo(size: str = "96"):
    try:
        return tk.PhotoImage(file=str(ASSETS / f"logo_{size}.png" if size != "512" else ASSETS / "logo.png"))
    except (tk.TclError, OSError):
        return None


def _num(text) -> float | None:
    try:
        value = float(str(text).strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _date(text) -> date | None:
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        return None


class Chart(tk.Canvas):
    """Minimal line chart: up to two y axes, x values are dates."""

    PAD = (58, 20, 58, 36)  # left, top, right, bottom

    def __init__(self, parent, **kw):
        super().__init__(parent, background=BYZ["ivory"], highlightthickness=1,
                         highlightbackground=BYZ["gold"], **kw)
        self.series = []
        self.hlines = []
        self.title = ""
        self.bind("<Configure>", lambda e: self.redraw())

    def plot(self, title, series, hlines=()):
        """series: [(label, [(date, value)], color, "left" | "right")]; hlines: [(label, value)] on the left axis"""
        self.title, self.series, self.hlines = title, [s for s in series if s[1]], list(hlines)
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        left, top, right, bottom = self.PAD
        self.create_text(w / 2, 10, text=self.title, font=("TkDefaultFont", 10, "bold"), fill=BYZ["purple"])
        if not self.series or w < 150 or h < 100:
            self.create_text(w / 2, h / 2, text="No data yet", fill="#888")
            return
        xs = [p[0].toordinal() for s in self.series for p in s[1]]
        x0, x1 = min(xs), max(xs)
        if x0 == x1:
            x0, x1 = x0 - 3, x1 + 3
        px = lambda x: left + (x - x0) / (x1 - x0) * (w - left - right)
        self.create_rectangle(left, top, w - right, h - bottom, outline="#ccc")
        for side in ("left", "right"):
            vals = [p[1] for s in self.series if s[3] == side for p in s[1]]
            if not vals:
                continue
            if side == "left":
                vals += [v for _, v in self.hlines]
            lo, hi = min(vals), max(vals)
            span = (hi - lo) or max(1.0, abs(hi) * 0.1)
            lo, hi = lo - span * 0.1, hi + span * 0.1
            py = lambda y, lo=lo, hi=hi: h - bottom - (y - lo) / (hi - lo) * (h - top - bottom)
            ax = left if side == "left" else w - right
            for i in range(5):
                v = lo + (hi - lo) * i / 4
                self.create_text(ax - 4 if side == "left" else ax + 4, py(v), text=f"{v:.1f}" if hi - lo < 10 else f"{v:.0f}",
                                 anchor="e" if side == "left" else "w", fill="#555", font=("TkDefaultFont", 8))
            if side == "left":
                for label, v in self.hlines:
                    self.create_line(left, py(v), w - right, py(v), fill="#bbb", dash=(2, 3))
                    self.create_text(w - right - 4, py(v) - 7, text=label, anchor="e", fill="#999",
                                     font=("TkDefaultFont", 8))
            for label, points, color, s_side in self.series:
                if s_side != side:
                    continue
                coords = [(px(d.toordinal()), py(v)) for d, v in points]
                if len(coords) > 1:
                    self.create_line(*[c for xy in coords for c in xy], fill=color, width=2,
                                     dash=(4, 2) if side == "right" else None)
                for x, y in coords:
                    self.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline=color)
        for d in (date.fromordinal(x0), date.fromordinal(x1)):
            self.create_text(px(d.toordinal()), h - bottom + 12, text=d.isoformat(), fill="#555",
                             font=("TkDefaultFont", 8))
        lx = left + 6
        for label, _, color, side in self.series:
            text = label + (" (right axis)" if side == "right" else "")
            self.create_line(lx, h - 10, lx + 16, h - 10, fill=color, width=2)
            item = self.create_text(lx + 20, h - 10, text=text, anchor="w", font=("TkDefaultFont", 8))
            lx = self.bbox(item)[2] + 14


class App(ttk.Frame):
    def __init__(self, root: tk.Tk, store: Store | None = None):
        super().__init__(root, padding=8)
        self.root = root
        self.store = store or Store()
        self.sessions = build_program()
        self.week_labels = [week_label(w) for w in range(0, WEEKS + 1)]

        self.units = tk.StringVar(value=self.store.get("units", "lb"))
        self.increment = tk.StringVar(value=self.store.get("increment", f"{DEFAULT_INCREMENT[self.units.get()]:g}"))
        start = _date(self.store.get("start", "")) or next_monday()
        self.start = tk.StringVar(value=start.isoformat())
        self.intake = {k: tk.StringVar(value=self.store.get(k, "")) for k, _ in INTAKE}
        self.bf_method = tk.StringVar(value=self.store.get("bodyfat_method", ""))
        self.sex = tk.StringVar(value=self.store.get("sex", ""))
        self.week = tk.StringVar(value=self.week_labels[self._current_week()])

        banner = tk.Frame(self, bg=BYZ["purple_dark"], highlightthickness=2, highlightbackground=BYZ["gold"])
        banner.pack(fill="x")
        self.logo = load_logo("96")
        if self.logo:
            tk.Label(banner, image=self.logo, bg=BYZ["purple_dark"]).pack(side="left", padx=(8, 12), pady=4)
        titles = tk.Frame(banner, bg=BYZ["purple_dark"])
        titles.pack(side="left", fill="y", pady=6)
        tk.Label(titles, text=app_name().upper(), font=TITLE_FONT, fg=BYZ["gold"], bg=BYZ["purple_dark"]).pack(
            anchor="w")
        tk.Label(titles, text="STRENGTH  \u2022  MASS  \u2022  POWER    |    Verkhoshansky \u2022 Siff \u2022 Prilepin",
                 font=("TkDefaultFont", 10, "bold"), fg=BYZ["gold_light"], bg=BYZ["purple_dark"]).pack(anchor="w")
        tk.Label(self, text=SHOULDER_TIP, bg=BYZ["crimson"], fg=BYZ["ivory"], font=("TkDefaultFont", 9, "bold"),
                 wraplength=1100, justify="left", padx=10, pady=4).pack(fill="x")
        tk.Label(banner, text=f"v{__version__}", fg=BYZ["gold_light"], bg=BYZ["purple_dark"]).pack(
            side="right", anchor="s", padx=8, pady=4)
        self.update_bar = tk.Frame(self, bg=BYZ["gold"])       # shown only when a newer version is out
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, pady=(4, 0))
        for name, builder in (("Start", self._start_tab), ("Program", self._program_tab),
                              ("Progress", self._progress_tab), ("PRs", self._prs_tab),
                              ("Body", self._body_tab), ("Log", self._log_tab)):
            frame = ttk.Frame(self.tabs, padding=8)
            self.tabs.add(frame, text=name)
            builder(frame)
        self.tabs.bind("<<NotebookTabChanged>>", lambda e: self.refresh())
        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.refresh()
        if not os.environ.get("RUSKIMAXXING_NO_UPDATE_CHECK"):
            self.check_updates(force=False)

    # ----- helpers ----------------------------------------------------------------
    @property
    def start_date(self) -> date:
        return _date(self.start.get()) or next_monday()

    @property
    def unit(self) -> str:
        return self.units.get()

    @property
    def height_unit(self) -> str:
        return "cm" if self.unit == "kg" else "in"

    def _increment(self) -> float:
        return _num(self.increment.get()) or DEFAULT_INCREMENT[self.unit]

    def _current_week(self) -> int:
        start = _date(self.store.get("start", "")) or next_monday()
        return max(0, min(WEEKS, (date.today() - start).days // 7 + 1))

    def _week(self) -> int:
        return self.week_labels.index(self.week.get())

    def _save_settings(self, *_):
        self.store.set("units", self.unit)
        self.store.set("increment", self.increment.get())
        if _date(self.start.get()):
            self.store.set("start", self.start.get())
        for k, var in self.intake.items():
            self.store.set(k, var.get())
        self.store.set("bodyfat_method", self.bf_method.get())
        self.store.set("sex", self.sex.get())

    def _tree(self, parent, columns, widths, height=12):
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, columns=[c for c, _ in columns], show="headings", height=height)
        for (col, text), width in zip(columns, widths):
            tree.heading(col, text=text, anchor="w")
            tree.column(col, width=width, anchor="w", stretch=width > 150)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return frame, tree

    # ----- Start tab --------------------------------------------------------------
    def _start_tab(self, tab):
        left, right = ttk.Frame(tab), ttk.Frame(tab)
        right.pack(side="right", fill="y", padx=(12, 0))  # packed first so it keeps its width
        left.pack(side="left", fill="both", expand=True)

        box = ttk.LabelFrame(left, text="1. Intake", padding=8)
        box.pack(fill="x")
        rows = [("Units", ttk.Combobox(box, textvariable=self.units, values=("lb", "kg"), width=8, state="readonly")),
                ("Round weights to", ttk.Entry(box, textvariable=self.increment, width=10)),
                ("Start date (Monday, YYYY-MM-DD)", ttk.Entry(box, textvariable=self.start, width=12))]
        rows += [(label, ttk.Entry(box, textvariable=self.intake[key], width=12)) for key, label in INTAKE]
        rows += [("Body fat method", ttk.Combobox(box, textvariable=self.bf_method, values=BODYFAT_METHODS, width=20)),
                 ("Sex (optional)", ttk.Combobox(box, textvariable=self.sex, values=("Male", "Female"), width=10))]
        for i, (label, widget) in enumerate(rows):
            ttk.Label(box, text=label).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 6), pady=1)
            widget.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 18))
        self.height_hint = ttk.Label(box, foreground="#666")
        self.height_hint.grid(row=6, column=0, columnspan=4, sticky="w")
        ttk.Button(box, text="Save intake", command=self._save_intake).grid(row=7, column=0, sticky="w", pady=(6, 0))
        ttk.Button(box, text="Export Excel spreadsheet...", command=self.export).grid(row=7, column=1, columnspan=2,
                                                                                    sticky="w", pady=(6, 0))
        self.units.trace_add("write", lambda *_: (self.increment.set(f"{DEFAULT_INCREMENT[self.unit]:g}"),
                                                  self.refresh()))

        box = ttk.LabelFrame(left, text="2. Starting maxes - enter what you know, OR run Week 0 (a test week)",
                             padding=8)
        box.pack(fill="both", expand=True, pady=(8, 0))
        bar = ttk.Frame(box)
        bar.pack(fill="x")
        self.base_ex = tk.StringVar(value=MAIN[0])
        self.base_w, self.base_r = tk.StringVar(), tk.StringVar(value="1")
        ttk.Combobox(bar, textvariable=self.base_ex, values=list(CATALOG), width=20).pack(side="left")
        ttk.Label(bar, text="Weight").pack(side="left", padx=(8, 2))
        ttk.Entry(bar, textvariable=self.base_w, width=8).pack(side="left")
        ttk.Label(bar, text="Reps").pack(side="left", padx=(8, 2))
        ttk.Spinbox(bar, from_=1, to=20, textvariable=self.base_r, width=4).pack(side="left")
        ttk.Button(bar, text="Add", command=self._add_baseline, style="Small.TButton", width=5).pack(side="left", padx=8)
        ttk.Button(bar, text="Remove", command=lambda: self._delete_from(self.base_tree), style="Small.TButton", width=7).pack(side="left")
        frame, self.base_tree = self._tree(box, [("ex", "Exercise"), ("set", "Set"), ("e1rm", "Est. 1RM")],
                                           (220, 120, 90), height=5)
        frame.pack(fill="both", expand=True, pady=(6, 0))
        self._cloud_box(left)
        self._updates_box(left)

        box = ttk.LabelFrame(right, text="PR board", padding=6)
        box.pack(fill="x")
        frame, self.board = self._tree(box, [("lift", "Lift"), ("e1rm", "Best e1RM"), ("r1", "1RM"), ("r3", "3RM"),
                                             ("r5", "5RM")], (125, 90, 60, 60, 60), height=len(MAIN) + 1)
        frame.pack(fill="x")
        box = ttk.LabelFrame(right, text="Plyometric standards (from your height)", padding=6)
        box.pack(fill="x", pady=(8, 0))
        frame, self.jumps = self._tree(box, [("level", "Level"), ("box", "Box jump"), ("broad", "Broad jump"),
                                             ("vert", "Vertical")], (100, 100, 105, 100), height=6)
        frame.pack(fill="x")
        self.jumps.tag_configure("you", font=("TkDefaultFont", 10, "bold"), foreground=BYZ["crimson"])
        ttk.Label(box, text="Box: step / knee / chest / head.  Broad: 0.75-1.5x height.  Vertical: 12-30 in.",
                  foreground="#6b5a45", wraplength=350).pack(anchor="w", pady=(4, 0))
        box = ttk.LabelFrame(right, text="Prilepin's chart", padding=6)
        box.pack(fill="x", pady=(8, 0))
        frame, tree = self._tree(box, [("pct", "% of max"), ("reps", "Reps/set"), ("opt", "Optimal"), ("rng", "Range")],
                                 (90, 80, 72, 70), height=4)
        frame.pack(fill="x")
        for label, z in zip(("Under 70%", "70-80%", "80-90%", "90%+"), ZONES):
            tree.insert("", "end", values=(label, f"{z.reps_per_set[0]}-{z.reps_per_set[1]}", z.optimal_total,
                                           f"{z.total_range[0]}-{z.total_range[1]}"))

    def _save_intake(self):
        if not _date(self.start.get()):
            messagebox.showerror("Start date", "Use the format YYYY-MM-DD", parent=self.root)
            return
        self._save_settings()
        bw = _num(self.intake["bodyweight_start"].get())
        if bw and not any(b.week == 0 for b in self.store.bodyweights()):
            self.store.set_bodyweight(BodyWeight(0, self.start_date - timedelta(weeks=1), bw))
        self.refresh()

    def _add_baseline(self):
        weight, reps = _num(self.base_w.get()), _num(self.base_r.get())
        if not weight or not reps or not self.base_ex.get().strip():
            messagebox.showerror("Starting max", "Pick an exercise and enter weight and reps", parent=self.root)
            return
        self._save_settings()
        entry = LogEntry(self.start_date - timedelta(weeks=1), self.base_ex.get().strip(), weight, int(reps),
                         "baseline", "starting max")
        self.store.add_lift(entry)
        self.base_w.set("")
        self.refresh()

    # ----- cloud backup ---------------------------------------------------------
    # ----- app updates -------------------------------------------------------------
    def _updates_box(self, parent):
        box = ttk.LabelFrame(parent, text="App updates", padding=6)
        box.pack(fill="x", pady=(8, 0))
        self.update_status = ttk.Label(box, text=f"You have version {__version__}.", foreground="#6b5a45")
        self.update_status.pack(side="left")
        ttk.Button(box, text="Check for updates", style="Small.TButton",
                   command=lambda: self.check_updates(force=True)).pack(side="left", padx=8)

    def check_updates(self, force=True):
        """Look for a newer release in the background; show a bar at the top if there is one."""
        if force:
            self.update_status.config(text="Checking...")

        def worker():
            update = check_for_update(self.store, force=force)
            self.root.after(0, lambda: self._show_update(update, force))
        threading.Thread(target=worker, daemon=True).start()

    def _show_update(self, update, asked):
        for w in self.update_bar.winfo_children():
            w.destroy()
        self.update_bar.pack_forget()
        if not update:
            self.update_status.config(text=f"You have version {__version__}" +
                                      (" - it's the latest." if asked else "."))
            return
        self.update_status.config(text=f"You have {__version__}. Version {update.version} is available.")
        if dismissed(self.store, update) and not asked:
            return
        style = {"bg": BYZ["gold"], "fg": BYZ["purple_dark"], "font": ("TkDefaultFont", 10, "bold")}
        tk.Label(self.update_bar, text=f"Update available: version {update.version} (you have {__version__})",
                 **style).pack(side="left", padx=10, pady=3)
        ttk.Button(self.update_bar, text="Download", style="Small.TButton",
                   command=lambda: webbrowser.open(update.url)).pack(side="left")
        ttk.Button(self.update_bar, text="What's new", style="Small.TButton",
                   command=lambda: webbrowser.open(update.page)).pack(side="left", padx=4)

        def later():
            dismiss(self.store, update)
            self.update_bar.pack_forget()
        ttk.Button(self.update_bar, text="Not now", style="Small.TButton", command=later).pack(side="right", padx=6)
        self.update_bar.pack(fill="x", before=self.tabs)

    def _cloud_box(self, parent):
        self.cloud = Cloud(self.store)
        box = ttk.LabelFrame(parent, text="3. Cloud backup (optional) - get your data back on a new device", padding=6)
        box.pack(fill="x", pady=(8, 0))
        ttk.Style(self.root).configure("Small.TButton", padding=(4, 1), font=("TkDefaultFont", 9, "bold"))
        self.cloud_status = ttk.Label(box, foreground="#6b5a45")
        self.cloud_status.pack(anchor="w")
        self.cloud_btns = ttk.Frame(box)
        self.cloud_btns.pack(anchor="w", pady=(4, 0))
        self._cloud_polling = False
        self.refresh_cloud()
        if self.cloud.pending_code:     # closed while signing in: keep waiting
            self._poll_sign_in()

    def refresh_cloud(self):
        self.cloud_status.config(text=self.cloud.status())
        for w in self.cloud_btns.winfo_children():
            w.destroy()
        if self.cloud.logged_in:
            actions = (("Back up now", self._cloud_sync), ("Log out", self._cloud_logout),
                       ("Delete account (website)", self._cloud_delete))
        elif self.cloud.pending_code:
            ttk.Label(self.cloud_btns, text=f"Code {self.cloud.pending_code}", font=("TkDefaultFont", 12, "bold"),
                      foreground=BYZ["purple"]).pack(side="left", padx=(0, 8))
            actions = (("Open sign-in page again", lambda: webbrowser.open(self.store.get("cloud_link_url", ""))),
                       ("Cancel", self._cloud_cancel))
        else:
            actions = (("Sign in or create account", self._cloud_sign_in),)
            ttk.Label(self.cloud_btns, text="  Opens the RuskiMaxxing website in your browser. Accounts are free.",
                      foreground="#6b5a45").pack(side="right")
        for text, action in actions:
            ttk.Button(self.cloud_btns, text=text, command=action, style="Small.TButton").pack(side="left",
                                                                                             padx=(0, 4))

    def _cloud_run(self, work, done_message=None):
        """Run a network call off the UI thread, then report back."""
        self.cloud_status.config(text="Working...")

        def worker():
            try:
                result = work()
                msg = done_message(result) if callable(done_message) else (done_message or "")
                err = None
            except CloudError as e:
                # 402 = signed in fine, but backups aren't active for the account: informational, not an error
                msg, err = (str(e), None) if e.code == 402 else ("", str(e))
            self.root.after(0, lambda: self._cloud_done(msg, err))
        threading.Thread(target=worker, daemon=True).start()

    def _cloud_done(self, message, error):
        self.refresh_cloud()
        if error:
            messagebox.showerror("Cloud backup", error, parent=self.root)
        else:
            if message:
                messagebox.showinfo("Cloud backup", message, parent=self.root)
            self.refresh(rebuild=True)

    def _cloud_sign_in(self):
        def started(link):
            webbrowser.open(link["url"])
            self._poll_sign_in()
            return ""
        self._cloud_run(lambda: started(self.cloud.start_browser_sign_in()))

    def _cloud_cancel(self):
        self.cloud.cancel_sign_in()
        self.refresh_cloud()

    def _poll_sign_in(self):
        """Check every 2 seconds (off the UI thread) until the website sign-in is finished or expires."""
        if self._cloud_polling:
            return
        self._cloud_polling = True

        def worker():
            while self.cloud.pending_code:
                time.sleep(2)
                try:
                    if self.cloud.poll_sign_in():
                        sent, got = self.cloud.sync()
                        msg = f"Signed in as {self.cloud.email}. Restored {got} records, backed up {sent}."
                        self.root.after(0, lambda: self._cloud_done(msg, None))
                        break
                except CloudError as e:
                    if not self.cloud.pending_code and not self.cloud.logged_in:
                        self.root.after(0, lambda e=e: self._cloud_done("", str(e)))
                        break
                    if self.cloud.logged_in:   # signed in; only the first backup failed (e.g. 402)
                        self.root.after(0, lambda e=e: self._cloud_done(str(e), None))
                        break
            self._cloud_polling = False
            self.root.after(0, self.refresh_cloud)
        threading.Thread(target=worker, daemon=True).start()

    def _cloud_sync(self):
        self._cloud_run(self.cloud.sync, lambda r: f"Backed up {r[0]}, received {r[1]} records.")

    def _cloud_logout(self):
        self._cloud_run(self.cloud.logout, "Logged out. Your data stays on this device.")

    def _cloud_delete(self):
        webbrowser.open(self.cloud.account_page("/account/delete"))

    def autosave_workout(self):
        if self.wo_dirty:
            self._save_workout(quiet=True)

    def sync_quietly(self):
        """Best-effort backup on exit; never blocks closing for long or shows errors."""
        if self.cloud.logged_in:
            try:
                self.cloud.sync()
            except CloudError:
                pass

    # ----- Program tab: per-set workout logger --------------------------------------
    def _program_tab(self, tab):
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        self.month_labels = [month_label(m) for m in range(0, MONTHS + 1)]
        self.month_pick = tk.StringVar()
        ttk.Label(bar, text="Month").pack(side="left")
        month_combo = ttk.Combobox(bar, textvariable=self.month_pick, values=self.month_labels, state="readonly",
                                   width=32)
        month_combo.pack(side="left", padx=(4, 10))
        month_combo.bind("<<ComboboxSelected>>", lambda e: self._pick_month())
        ttk.Label(bar, text="Week").pack(side="left")
        self.week_combo = ttk.Combobox(bar, textvariable=self.week, state="readonly", width=36)
        self.week_combo.pack(side="left", padx=4)
        self.week_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Button(bar, text="This week", command=self._today).pack(side="left", padx=6)
        self.week.trace_add("write", lambda *a: self._sync_pickers())
        self._sync_pickers()
        self.bw_week = tk.StringVar()
        ttk.Button(bar, text="Save", command=self._save_week_bw).pack(side="right")
        ttk.Entry(bar, textvariable=self.bw_week, width=8).pack(side="right", padx=4)
        ttk.Label(bar, text="Bodyweight this week").pack(side="right")
        self.bf_due = ttk.Label(tab, foreground="#B00020", font=("TkDefaultFont", 10, "bold"))
        self.bf_due.pack(anchor="w", pady=(4, 0))

        days = ttk.Frame(tab)
        days.pack(fill="x", pady=(4, 0))
        self.day_var = tk.IntVar(value=0)
        self.day_buttons = []
        for i in range(3):
            b = ttk.Radiobutton(days, variable=self.day_var, value=i, style="Toolbutton", command=self.refresh)
            b.pack(side="left", padx=(0, 4), ipadx=6, ipady=3)
            self.day_buttons.append(b)

        ttk.Label(tab, text="Every set is pre-filled with the plan. Change anything that differed, tick Done "
                            "for each set you completed, then Save workout.", foreground="#666").pack(anchor="w",
                                                                                                   pady=(4, 0))
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=(4, 0))
        ttk.Button(actions, text="Save workout", command=self._save_workout).pack(side="left")
        ttk.Button(actions, text="Mark all done as prescribed", command=self._mark_all_done).pack(side="left", padx=6)
        ttk.Button(actions, text="Reset to prescribed", command=self._reset_workout).pack(side="left")
        self.wo_status = ttk.Label(actions, foreground="#666")
        self.wo_status.pack(side="left", padx=12)

        outer = ttk.Frame(tab)
        outer.pack(fill="both", expand=True, pady=(6, 0))
        self.wo_canvas = tk.Canvas(outer, highlightthickness=0, bg=BYZ["parchment"])
        scroll = ttk.Scrollbar(outer, orient="vertical", command=self.wo_canvas.yview)
        self.wo_frame = ttk.Frame(self.wo_canvas, padding=(0, 0, 8, 0))
        self.wo_frame.bind("<Configure>",
                           lambda e: self.wo_canvas.configure(scrollregion=self.wo_canvas.bbox("all")))
        self.wo_canvas.create_window((0, 0), window=self.wo_frame, anchor="nw")
        self.wo_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.wo_canvas.pack(side="left", fill="both", expand=True)
        self.wo_canvas.bind("<Enter>", lambda e: self._wheel(True))
        self.wo_canvas.bind("<Leave>", lambda e: self._wheel(False))
        self.wo_blocks = []   # one dict per exercise: prescription, set rows, notes
        self.wo_key = None    # (week, day) currently on screen
        self.wo_dirty = False

    def _wheel(self, on):
        if not on:
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.wo_canvas.unbind_all(seq)
            return
        self.wo_canvas.bind_all("<MouseWheel>", lambda e: self.wo_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.wo_canvas.bind_all("<Button-4>", lambda e: self.wo_canvas.yview_scroll(-1, "units"))
        self.wo_canvas.bind_all("<Button-5>", lambda e: self.wo_canvas.yview_scroll(1, "units"))

    def _sync_pickers(self):
        """Month dropdown follows the chosen week; the week dropdown lists only that month's weeks."""
        if not hasattr(self, "week_combo"):
            return
        month = month_of(self._week())
        self.month_pick.set(self.month_labels[month])
        self.week_combo["values"] = [self.week_labels[w] for w in month_weeks(month)]

    def _pick_month(self):
        month = self.month_labels.index(self.month_pick.get())
        if month_of(self._week()) != month:
            self.week.set(self.week_labels[month_weeks(month)[0]])
            self.refresh()

    def _today(self):
        self._save_settings()
        self.week.set(self.week_labels[self._current_week()])
        today = date.today()
        s = next((s for s in self.sessions if s.week == self._week() and s.date(self.start_date) >= today), None)
        if s:
            self.day_var.set(s.day_index)
        self.refresh()

    def _save_week_bw(self):
        weight = _num(self.bw_week.get())
        week = self._week()
        if weight:
            self.store.set_bodyweight(BodyWeight(week, self.start_date + timedelta(weeks=week - 1), weight))
        else:
            self.store.delete_bodyweight(week)
        self.refresh()

    # -- building the workout model (logic lives in workout.py, shared with the phone app) --
    def _cfg(self) -> wo.Settings:
        return wo.Settings(self.start_date, self.unit, self._increment(), _num(self.intake["height"].get()))

    def _session(self, week, day):
        return wo.session(week, day)

    def _workout_model(self, week, day, use_saved=True):
        return wo.workout_model(self.store, week, day, self._cfg(), use_saved)

    # -- rendering ------------------------------------------------------------------
    def _render_workout(self, blocks):
        for child in self.wo_frame.winfo_children():
            child.destroy()
        self.wo_blocks = []
        unit, hunit = self.unit, self.height_unit
        r = 0
        for bi, b in enumerate(blocks):
            p = b["p"]
            info = CATALOG.get(p.exercise)
            plyo = bool(info and info.category == "plyo")
            color = "#1F6F5C" if plyo else BYZ["purple"] if p.kind != "accessory" else BYZ["ink"]
            head = ttk.Frame(self.wo_frame)
            head.grid(row=r, column=0, columnspan=7, sticky="ew", pady=(10 if r else 0, 2))
            tk.Label(head, text=p.exercise, font=("TkDefaultFont", 11, "bold"), fg=color,
                     bg=BYZ["parchment"]).pack(side="left")
            scheme = f"{p.sets} x {p.reps}" if p.sets else p.reps
            if p.percent:
                scheme += f" @ {p.percent:g}%"
            ttk.Label(head, text=f"   {scheme}   -   {b['source']}").pack(side="left")
            ttk.Button(head, text="+ Add set", width=9,
                       command=lambda bi=bi: self._add_set(bi)).pack(side="right")
            r += 1
            if p.note:
                ttk.Label(self.wo_frame, text=p.note, foreground="#666", wraplength=900).grid(
                    row=r, column=0, columnspan=7, sticky="w")
                r += 1
            wlabel = f"Height / distance ({hunit})" if plyo else f"Weight ({unit})"
            rlabel = "Seconds" if "s" in p.reps and p.reps[-1] == "s" else "Reps"
            for col, text in enumerate(("Set", "Target", wlabel, rlabel, "RPE", "Done")):
                ttk.Label(self.wo_frame, text=text, font=("TkDefaultFont", 9, "bold")).grid(
                    row=r, column=col, sticky="w", padx=(0, 10))
            r += 1
            vars_rows = []
            for k, row in enumerate(b["rows"], start=1):
                v = {"weight": tk.StringVar(value=row["weight"]), "reps": tk.StringVar(value=row["reps"]),
                     "rpe": tk.StringVar(value=row["rpe"]), "done": tk.BooleanVar(value=row["done"]),
                     "target": row["target"]}
                ttk.Label(self.wo_frame, text=str(k)).grid(row=r, column=0, sticky="w")
                ttk.Label(self.wo_frame, text=row["target"], foreground="#666").grid(row=r, column=1, sticky="w",
                                                                                    padx=(0, 10))
                ttk.Entry(self.wo_frame, textvariable=v["weight"], width=9).grid(row=r, column=2, sticky="w", pady=1)
                ttk.Entry(self.wo_frame, textvariable=v["reps"], width=6).grid(row=r, column=3, sticky="w")
                ttk.Combobox(self.wo_frame, textvariable=v["rpe"], width=5,
                             values=("", "6", "6.5", "7", "7.5", "8", "8.5", "9", "9.5", "10")).grid(
                    row=r, column=4, sticky="w")
                ttk.Checkbutton(self.wo_frame, variable=v["done"]).grid(row=r, column=5, sticky="w")
                for var in (v["weight"], v["reps"], v["rpe"], v["done"]):
                    var.trace_add("write", lambda *_: self._set_dirty(True))
                vars_rows.append(v)
                r += 1
            note = tk.StringVar(value=b["note"])
            ttk.Label(self.wo_frame, text="Notes").grid(row=r, column=0, sticky="w")
            ttk.Entry(self.wo_frame, textvariable=note, width=70).grid(row=r, column=1, columnspan=5, sticky="w",
                                                                     pady=(2, 0))
            note.trace_add("write", lambda *_: self._set_dirty(True))
            r += 1
            ttk.Separator(self.wo_frame).grid(row=r, column=0, columnspan=7, sticky="ew", pady=(6, 0))
            r += 1
            self.wo_blocks.append({**b, "vars": vars_rows, "note_var": note})
        self.wo_canvas.yview_moveto(0)

    def _collect(self):
        """Current screen state back into model form."""
        blocks = []
        for b in self.wo_blocks:
            rows = [{"target": v["target"], "weight": v["weight"].get(), "reps": v["reps"].get(),
                     "rpe": v["rpe"].get(), "done": v["done"].get()} for v in b["vars"]]
            blocks.append({"p": b["p"], "rows": rows, "source": b["source"], "planned": b["planned"],
                           "note": b["note_var"].get()})
        return blocks

    def _set_dirty(self, dirty):
        self.wo_dirty = dirty
        if dirty:
            self.wo_status.config(text="Unsaved changes - press Save workout")

    def _add_set(self, bi):
        blocks = self._collect()
        wo.add_set(blocks, bi)
        self._render_workout(blocks)
        self._set_dirty(True)

    def _mark_all_done(self):
        blocks = self._collect()
        wo.mark_all_done(blocks)
        self._render_workout(blocks)
        self._set_dirty(True)

    def _reset_workout(self):
        if self.wo_key:
            self._render_workout(self._workout_model(*self.wo_key, use_saved=False))
            self._set_dirty(True)

    def _save_workout(self, quiet=False):
        if not self.wo_key or not self.wo_blocks:
            return
        week, day = self.wo_key
        saved, prs, bad = wo.save_workout(self.store, week, day, self._collect(), self._cfg())
        if bad and not quiet:
            messagebox.showwarning("Check reps", "These sets are ticked Done but have no reps, so they were saved "
                                   "as not done:\n" + "\n".join(bad), parent=self.root)
        self.wo_dirty = False
        done = sum(e.done for e in saved)
        self.wo_status.config(text=f"Saved {self._session(week, day).day}: {done} set{'s' * (done != 1)} done")
        self.refresh(rebuild=True)
        if prs and not quiet:
            messagebox.showinfo("New PR!", "\n".join(prs), parent=self.root)
        return prs

    # ----- Progress tab -----------------------------------------------------------
    def _progress_tab(self, tab):
        self.lift_chart = Chart(tab, height=240)
        self.lift_chart.pack(fill="both", expand=True)
        row = ttk.Frame(tab)
        row.pack(fill="both", expand=True, pady=(6, 0))
        self.plyo_chart = Chart(row, height=220)
        self.plyo_chart.pack(side="left", fill="both", expand=True)
        self.body_chart = Chart(row, height=220)
        self.body_chart.pack(side="left", fill="both", expand=True, padx=(6, 0))

    def _refresh_progress(self, entries):
        bw = [(b.date, b.weight) for b in self.store.bodyweights()]
        lifts = [(lift, e1rm_history(entries, lift), COLORS[i % len(COLORS)], "left") for i, lift in enumerate(MAIN)]
        self.lift_chart.plot(f"Main lifts - best est. 1RM ({self.unit}) vs bodyweight",
                             lifts + [("Bodyweight", bw, "#555", "right")])
        done = [e for e in entries if e.done and e.weight > 0]
        jumps = [(name, sorted({e.date: max(x.weight for x in done if x.exercise == name and x.date == e.date)
                                for e in done if e.exercise == name}.items()), color, side)
                 for name, color, side in (("Box Jump", COLORS[2], "left"), ("Vertical Jump", COLORS[3], "left"),
                                           ("Broad Jump", COLORS[1], "right"))]
        height = _num(self.intake["height"].get())
        standards = [(f"{level} {t:g}", t) for level, _, t in box_jump_targets(height, self.height_unit)] if height else []
        self.plyo_chart.plot(f"Plyometrics ({self.height_unit}) - box-jump standards dotted", jumps, standards)
        fats = sorted(self.store.bodyfats(), key=lambda f: f.date)
        self.body_chart.plot("Bodyweight and body fat %", [
            ("Bodyweight", bw, COLORS[1], "left"), ("Body fat %", [(f.date, f.percent) for f in fats], COLORS[3], "right")])

    # ----- PRs tab ----------------------------------------------------------------
    def _prs_tab(self, tab):
        cols = [("ex", "Exercise"), ("type", "Type"), ("e1rm", "Best e1RM")] + \
               [(f"r{n}", f"{n}RM") for n in REP_MAX_COUNTS]
        frame, self.pr_tree = self._tree(tab, cols, [200, 75, 75] + [52] * len(REP_MAX_COUNTS), height=12)
        frame.pack(fill="both", expand=True)
        self.pr_tree.bind("<<TreeviewSelect>>", lambda e: self._draw_pr_chart())
        ttk.Label(tab, text="Every movement and variation you've logged. NRM = heaviest weight for at least N reps. "
                            "Jumps: 1RM = best height / distance. Select a row to chart it.").pack(anchor="w")
        self.pr_chart = Chart(tab, height=260)
        self.pr_chart.pack(fill="both", expand=True, pady=(6, 0))

    def _draw_pr_chart(self):
        sel = self.pr_tree.selection()
        entries = self.store.lifts()
        ex = sel[0] if sel else MAIN[0]
        info = CATALOG.get(ex)
        if info and info.category == "plyo":
            points = sorted((e.date, e.weight) for e in entries if e.exercise == ex and e.done and e.weight > 0)
            label = "Best height / distance"
        else:
            points, label = e1rm_history(entries, ex), "Best est. 1RM"
        bw = [(b.date, b.weight) for b in self.store.bodyweights()]
        self.pr_chart.plot(f"{ex} vs bodyweight", [(label, points, COLORS[0], "left"),
                                                    ("Bodyweight", bw, COLORS[1], "right")])

    # ----- Body tab ---------------------------------------------------------------
    def _body_tab(self, tab):
        top = ttk.Frame(tab)
        top.pack(fill="x")
        box = ttk.LabelFrame(top, text="Bodyweight - once a week (enter it on the Program tab or here)", padding=6)
        box.pack(side="left", fill="both", expand=True)
        bar = ttk.Frame(box)
        bar.pack(fill="x")
        self.bw_pick = tk.StringVar(value=self.week_labels[self._current_week()])
        self.bw_value = tk.StringVar()
        ttk.Combobox(bar, textvariable=self.bw_pick, values=self.week_labels, state="readonly", width=30).pack(side="left")
        ttk.Entry(bar, textvariable=self.bw_value, width=8).pack(side="left", padx=4)
        ttk.Button(bar, text="Save", command=self._save_bw_pick).pack(side="left")
        frame, self.bw_tree = self._tree(box, [("week", "Week"), ("date", "Week of"), ("bw", "Bodyweight")],
                                         (60, 100, 90), height=6)
        frame.pack(fill="both", expand=True, pady=(4, 0))

        box = ttk.LabelFrame(top, text="Body fat - once a month", padding=6)
        box.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.bf_vars = {k: tk.StringVar() for k in ("month", "date", "pct", "method", "weight")}
        self.bf_vars["month"].set("1")
        self.bf_vars["date"].set(date.today().isoformat())
        self.bf_vars["method"].set(self.store.get("bodyfat_method", "") or BODYFAT_METHODS[0])
        grid = ttk.Frame(box)
        grid.pack(fill="x")
        widgets = [(f"Month (1-{MONTHS})", ttk.Spinbox(grid, from_=1, to=MONTHS, textvariable=self.bf_vars["month"], width=4)),
                   ("Date tested", ttk.Entry(grid, textvariable=self.bf_vars["date"], width=11)),
                   ("Body fat %", ttk.Entry(grid, textvariable=self.bf_vars["pct"], width=6)),
                   ("Method", ttk.Combobox(grid, textvariable=self.bf_vars["method"], values=BODYFAT_METHODS, width=20)),
                   ("Weight at test", ttk.Entry(grid, textvariable=self.bf_vars["weight"], width=8))]
        for i, (label, widget) in enumerate(widgets):
            ttk.Label(grid, text=label).grid(row=i // 3, column=(i % 3) * 2, sticky="w", padx=(0, 4))
            widget.grid(row=i // 3, column=(i % 3) * 2 + 1, sticky="w", padx=(0, 10), pady=1)
        ttk.Button(grid, text="Save", command=self._save_bf).grid(row=2, column=0, sticky="w", pady=(2, 0))
        frame, self.bf_tree = self._tree(box, [("m", "Month"), ("due", "Due"), ("d", "Tested"), ("pct", "BF %"),
                                               ("method", "Method"), ("lean", "Lean mass")],
                                         (46, 88, 88, 46, 100, 70), height=6)
        frame.pack(fill="both", expand=True, pady=(4, 0))

        charts = ttk.Frame(tab)
        charts.pack(fill="both", expand=True, pady=(6, 0))
        self.bw_chart = Chart(charts, height=200)
        self.bw_chart.pack(side="left", fill="both", expand=True)
        self.bf_chart = Chart(charts, height=200)
        self.bf_chart.pack(side="left", fill="both", expand=True, padx=(6, 0))
        guide = tk.Text(tab, height=9, wrap="word", font=("TkDefaultFont", 9), bg=BYZ["ivory"], fg=BYZ["ink"],
                        highlightthickness=1, highlightbackground=BYZ["gold"], relief="flat")
        guide.insert("1.0", BODYFAT_GUIDE)
        guide.configure(state="disabled")
        guide.pack(fill="x", pady=(6, 0))

    def _save_bw_pick(self):
        week = self.week_labels.index(self.bw_pick.get())
        weight = _num(self.bw_value.get())
        if weight:
            self.store.set_bodyweight(BodyWeight(week, self.start_date + timedelta(weeks=week - 1), weight))
            self.bw_value.set("")
        self.refresh()

    def _save_bf(self):
        v = self.bf_vars
        month, pct, day = _num(v["month"].get()), _num(v["pct"].get()), _date(v["date"].get())
        if not month or not 1 <= month <= MONTHS or not pct or not day:
            messagebox.showerror("Body fat", f"Enter month 1-{MONTHS}, date (YYYY-MM-DD) and body fat %",
                                 parent=self.root)
            return
        self.store.set_bodyfat(BodyFat(int(month), day, pct, v["method"].get(), _num(v["weight"].get())))
        v["pct"].set("")
        self.refresh()

    # ----- Log tab ----------------------------------------------------------------
    def _log_tab(self, tab):
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        self.log_vars = {"date": tk.StringVar(value=date.today().isoformat()), "ex": tk.StringVar(value=MAIN[0]),
                         "w": tk.StringVar(), "r": tk.StringVar(value="5")}
        for label, widget in (("Date", ttk.Entry(bar, textvariable=self.log_vars["date"], width=11)),
                              ("Exercise", ttk.Combobox(bar, textvariable=self.log_vars["ex"], values=list(CATALOG),
                                                        width=24)),
                              ("Weight / height", ttk.Entry(bar, textvariable=self.log_vars["w"], width=8)),
                              ("Reps", ttk.Spinbox(bar, from_=1, to=30, textvariable=self.log_vars["r"], width=4))):
            ttk.Label(bar, text=label).pack(side="left", padx=(8, 2))
            widget.pack(side="left")
        ttk.Button(bar, text="Add set", command=self._add_log).pack(side="left", padx=8)
        ttk.Button(bar, text="Delete selected", command=lambda: self._delete_from(self.log_tree)).pack(side="right")
        frame, self.log_tree = self._tree(tab, [("date", "Date"), ("ex", "Exercise"), ("w", "Weight"), ("r", "Reps"),
                                                ("e1rm", "Est. 1RM"), ("kind", "Type"), ("done", "Done")],
                                          (100, 220, 80, 60, 80, 90, 60), height=22)
        frame.pack(fill="both", expand=True, pady=(6, 0))

    def _add_log(self):
        v = self.log_vars
        weight, reps, day = _num(v["w"].get()), _num(v["r"].get()), _date(v["date"].get())
        if not weight or not reps or not day or not v["ex"].get().strip():
            messagebox.showerror("Log", "Enter date (YYYY-MM-DD), exercise, weight and reps", parent=self.root)
            return
        entry = self.store.add_lift(LogEntry(day, v["ex"].get().strip(), weight, int(reps)))
        prs = new_prs(self.store.lifts(), entry)
        v["w"].set("")
        self.refresh()
        if prs:
            messagebox.showinfo("New PR!", f"{entry.exercise}\n\n" + "\n".join(prs), parent=self.root)

    def _delete_from(self, tree):
        for iid in tree.selection():
            if iid.startswith("lift-"):
                self.store.delete_lift(int(iid[5:]))
        self.refresh()

    # ----- refresh ----------------------------------------------------------------
    def refresh(self, rebuild=False):
        entries = self.store.lifts()
        self.height_hint.config(text=f"Height in {self.height_unit}; weights and box heights in "
                                     f"{self.unit} / {self.height_unit}.")
        self._refresh_start(entries)
        self._refresh_program(entries, rebuild)
        self._refresh_progress(entries)
        self._refresh_prs(entries)
        self._refresh_body()
        self._refresh_log(entries)

    def _refresh_start(self, entries):
        self.base_tree.delete(*self.base_tree.get_children())
        for e in (e for e in entries if e.kind == "baseline"):
            self.base_tree.insert("", "end", iid=f"lift-{e.id}",
                                  values=(e.exercise, f"{e.weight:g} x {e.reps}", f"{e.e1rm:.0f}"))
        self.board.delete(*self.board.get_children())
        total = 0.0
        for lift in MAIN:
            best, rms = best_e1rm(entries, lift), rep_maxes(entries, lift)
            total += best.e1rm if best else 0
            self.board.insert("", "end", values=(lift, f"{best.e1rm:.0f}" if best else "-",
                                                 *[f"{rms[n].weight:g}" if n in rms else "-" for n in (1, 3, 5)]))
        self.board.insert("", "end", values=("Total", f"{total:.0f}" if total else "-", "", "", ""))
        self.jumps.delete(*self.jumps.get_children())
        height = _num(self.intake["height"].get())
        u = self.height_unit
        bests = {j: max((e.weight for e in entries if e.exercise == j and e.done), default=None)
                 for j in JUMP_STANDARDS}
        targets = {j: dict((lvl, t) for lvl, _, t in jump_targets(j, height, u)) for j in JUMP_STANDARDS}
        for level in LEVELS:
            cells = []
            for j in JUMP_STANDARDS:
                t = targets[j][level]
                mark = " \u2713" if t and bests[j] and bests[j] >= t else ""
                cells.append(f"{t:g} {u}{mark}" if t is not None else "enter height")
            self.jumps.insert("", "end", values=(level, *cells))
        self.jumps.insert("", "end", tags=("you",), values=(
            "Your best", *[f"{bests[j]:g} {u}" if bests[j] else "-" for j in JUMP_STANDARDS]))
        self.jumps.insert("", "end", tags=("you",), values=(
            "Your level", *[jump_level(j, bests[j], height, u) for j in JUMP_STANDARDS]))

    def _refresh_program(self, entries, rebuild=False):
        week, day = self._week(), self.day_var.get()
        bw = {b.week: b.weight for b in self.store.bodyweights()}
        self.bw_week.set(f"{bw[week]:g}" if week in bw else "")
        month = next((m for m in range(1, MONTHS + 1) if bodyfat_week(m) == week), None)
        self.bf_due.config(text=f"Body fat test due this week (month {month}) - enter it on the Body tab"
                           if month else "")
        for i, button in enumerate(self.day_buttons):
            s = self._session(week, i)
            done, planned = wo.day_progress(self.store, week, i)
            mark = "  \u2713" if done >= planned else ""
            button.config(text=f"{s.day}  |  {s.date(self.start_date):%a %b %d}  |  {done}/{planned} sets{mark}")
        key = (week, day)
        if key != self.wo_key:
            if self.wo_dirty:
                self._save_workout(quiet=True)  # never lose edits when moving to another day or week
            rebuild = True
        if rebuild or not self.wo_dirty:
            self.wo_key = key
            self._render_workout(self._workout_model(week, day))
            self.wo_dirty = False

    def _refresh_prs(self, entries):
        selected = self.pr_tree.selection()
        self.pr_tree.delete(*self.pr_tree.get_children())
        logged = {e.exercise for e in entries}
        names = [n for n in CATALOG if n in logged or n in MAIN] + sorted(logged - set(CATALOG))
        for name in names:
            info = CATALOG.get(name)
            best, rms = best_e1rm(entries, name), rep_maxes(entries, name)
            plyo = info and info.category == "plyo"
            self.pr_tree.insert("", "end", iid=name, values=(
                name, info.category if info else "custom", "" if plyo else (f"{best.e1rm:.0f}" if best else "-"),
                *[(f"{rms[n].weight:g}" if n in rms else "-") if not plyo or n == 1 else "" for n in REP_MAX_COUNTS]))
        keep = [s for s in selected if self.pr_tree.exists(s)]
        if keep:
            self.pr_tree.selection_set(keep)
        self._draw_pr_chart()

    def _refresh_body(self):
        self.bw_tree.delete(*self.bw_tree.get_children())
        bws = self.store.bodyweights()
        for b in sorted(bws, key=lambda b: -b.week):
            self.bw_tree.insert("", "end", values=(b.week, b.date.isoformat(), f"{b.weight:g}"))
        self.bf_tree.delete(*self.bf_tree.get_children())
        fats = {f.month: f for f in self.store.bodyfats()}
        for m in range(1, MONTHS + 1):
            f = fats.get(m)
            due = self.start_date + timedelta(weeks=bodyfat_week(m) - 1)
            self.bf_tree.insert("", "end", values=(m, due.isoformat(), f.date.isoformat() if f else "",
                                                   f"{f.percent:g}" if f else "", f.method if f else "",
                                                   f"{f.lean_mass:g}" if f and f.lean_mass else ""))
        self.bw_chart.plot("Bodyweight (weekly)", [("Bodyweight", [(b.date, b.weight) for b in bws], COLORS[1], "left")])
        fat_list = sorted(fats.values(), key=lambda f: f.date)
        self.bf_chart.plot("Body fat % and lean mass (monthly)", [
            ("Body fat %", [(f.date, f.percent) for f in fat_list], COLORS[3], "left"),
            ("Lean mass", [(f.date, f.lean_mass) for f in fat_list if f.lean_mass], COLORS[2], "right")])

    def _refresh_log(self, entries):
        self.log_tree.delete(*self.log_tree.get_children())
        for e in reversed(entries):
            self.log_tree.insert("", "end", iid=f"lift-{e.id}", values=(
                e.date.isoformat(), e.exercise, f"{e.weight:g}", e.reps,
                f"{e.e1rm:.0f}" if e.reps else "", e.kind + (f" wk{e.week} d{e.day + 1} s{e.set_no}" if e.week is not None else ""),
                "\u2713" if e.done else "-"))

    # ----- export -----------------------------------------------------------------
    def export_data(self) -> dict:
        entries = self.store.lifts()
        data = {"units": self.unit, "increment": self._increment(), "start": self.start_date,
                "height": _num(self.intake["height"].get()), "bodyweight_start": _num(self.intake["bodyweight_start"].get()),
                "bodyfat_start": _num(self.intake["bodyfat_start"].get()), "bodyfat_method": self.bf_method.get() or None,
                "name": self.intake["name"].get() or None, "age": _num(self.intake["age"].get()),
                "sex": self.sex.get() or None}
        base = [e for e in entries if e.kind == "baseline"]
        rest = [e for e in entries if e.kind != "baseline" and e.done]
        data["baseline"] = [(e.exercise, e.weight, e.reps) for e in base[:40]]
        data["log"] = [(e.date, e.exercise, e.weight, e.reps, e.note) for e in base[40:] + rest]
        data["bodyweight"] = {b.week: b.weight for b in self.store.bodyweights()}
        data["bodyfat"] = {f.month: (f.date, f.percent, f.method, f.weight) for f in self.store.bodyfats()}
        return data

    def export(self):
        self._save_settings()
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".xlsx", initialfile=f"{app_name().replace(' ', '-')}.xlsx",
            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        try:
            build_workbook(path, self.export_data())
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc), parent=self.root)
            return
        messagebox.showinfo("Saved", f"Spreadsheet saved to:\n{path}\n\nYour sets are in the Log sheet and "
                                     "starting maxes on Start Here.", parent=self.root)


def main() -> None:
    root = tk.Tk()
    root.title(f"{app_name()} {__version__} - Strength, Mass & Power")
    apply_theme(root)
    icon = load_logo("512")
    if icon:
        root.iconphoto(True, icon)  # title bar / taskbar / dock on every OS
    if sys.platform == "win32":
        try:
            root.iconbitmap(default=str(ASSETS / "icon.ico"))  # crisp multi-size icon on Windows
        except tk.TclError:
            pass
    root.geometry("1180x820")
    root.minsize(900, 600)
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app._save_settings(), app.autosave_workout(), app.sync_quietly(),
                                               root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
