"""Desktop app (Windows / macOS / Linux) built on tkinter.

Tabs: Start (intake, starting maxes, PR board, box jump standards, Prilepin's
chart) - Program (the year, log sets, weekly bodyweight) - PRs (every movement,
charted against bodyweight) - Body (weekly bodyweight, monthly body fat) - Log.
All data lives in a local SQLite file (see storage.py).
"""

import tkinter as tk
from datetime import date, timedelta
from tkinter import filedialog, messagebox, ttk

from ruskimaxxing import __version__
from ruskimaxxing.edition import app_name
from ruskimaxxing.excel import build_workbook
from ruskimaxxing.exercises import CATALOG, MAIN, box_jump_level, box_jump_targets
from ruskimaxxing.prilepin import ZONES
from ruskimaxxing.program import (WEEKS, bodyfat_week, build_program, cycle_start, next_monday,
                                  week_label)
from ruskimaxxing.storage import Store
from ruskimaxxing.tracking import (BODYFAT_GUIDE, BODYFAT_METHODS, REP_MAX_COUNTS, BodyFat,
                                   BodyWeight, LogEntry, best_e1rm, e1rm_history, new_prs,
                                   rep_maxes, training_max)

DEFAULT_INCREMENT = {"lb": 5.0, "kg": 2.5}
INTAKE = (("name", "Name (optional)"), ("height", "Height"), ("bodyweight_start", "Starting bodyweight"),
          ("bodyfat_start", "Starting body fat % (optional)"), ("age", "Age (optional)"))
COLORS = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b")


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
        super().__init__(parent, background="white", highlightthickness=0, **kw)
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
        self.create_text(w / 2, 10, text=self.title, font=("TkDefaultFont", 10, "bold"))
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

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
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
        self.units.trace_add("write", lambda *_: (self.increment.set(f"{DEFAULT_INCREMENT[self.unit]:g}"),
                                                  self.refresh()))

        box = ttk.LabelFrame(left, text="2. Starting maxes - enter what you know, OR run Week 0 (a test week)",
                             padding=8)
        box.pack(fill="both", expand=True, pady=(8, 0))
        bar = ttk.Frame(box)
        bar.pack(fill="x")
        self.base_ex = tk.StringVar(value=MAIN[0])
        self.base_w, self.base_r = tk.StringVar(), tk.StringVar(value="1")
        ttk.Combobox(bar, textvariable=self.base_ex, values=list(CATALOG), width=24).pack(side="left")
        ttk.Label(bar, text="Weight / height").pack(side="left", padx=(8, 2))
        ttk.Entry(bar, textvariable=self.base_w, width=8).pack(side="left")
        ttk.Label(bar, text="Reps").pack(side="left", padx=(8, 2))
        ttk.Spinbox(bar, from_=1, to=20, textvariable=self.base_r, width=4).pack(side="left")
        ttk.Button(bar, text="Add", command=self._add_baseline).pack(side="left", padx=8)
        ttk.Button(bar, text="Remove selected", command=lambda: self._delete_from(self.base_tree)).pack(side="left")
        frame, self.base_tree = self._tree(box, [("ex", "Exercise"), ("set", "Set"), ("e1rm", "Est. 1RM")],
                                           (220, 120, 90), height=8)
        frame.pack(fill="both", expand=True, pady=(6, 0))
        ttk.Button(left, text="Export Excel spreadsheet...", command=self.export).pack(anchor="w", pady=(8, 0))

        box = ttk.LabelFrame(right, text="PR board", padding=6)
        box.pack(fill="x")
        frame, self.board = self._tree(box, [("lift", "Lift"), ("e1rm", "Best e1RM"), ("r1", "1RM"), ("r3", "3RM"),
                                             ("r5", "5RM")], (120, 80, 55, 55, 55), height=len(MAIN) + 1)
        frame.pack(fill="x")
        box = ttk.LabelFrame(right, text="Box jump standards (from your height)", padding=6)
        box.pack(fill="x", pady=(8, 0))
        frame, self.jumps = self._tree(box, [("level", "Level"), ("desc", "Box"), ("h", "Height"), ("ok", "Reached")],
                                       (95, 100, 72, 70), height=4)
        frame.pack(fill="x")
        self.jump_level = ttk.Label(box, font=("TkDefaultFont", 10, "bold"), wraplength=340)
        self.jump_level.pack(anchor="w", pady=(4, 0))
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

    # ----- Program tab ------------------------------------------------------------
    def _program_tab(self, tab):
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        ttk.Button(bar, text="<", width=3, command=lambda: self._step(-1)).pack(side="left")
        combo = ttk.Combobox(bar, textvariable=self.week, values=self.week_labels, state="readonly", width=38)
        combo.pack(side="left", padx=4)
        combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Button(bar, text=">", width=3, command=lambda: self._step(1)).pack(side="left")
        ttk.Button(bar, text="This week", command=self._today).pack(side="left", padx=6)
        self.bw_week = tk.StringVar()
        ttk.Button(bar, text="Save", command=self._save_week_bw).pack(side="right")
        ttk.Entry(bar, textvariable=self.bw_week, width=8).pack(side="right", padx=4)
        ttk.Label(bar, text="Bodyweight this week").pack(side="right")
        self.bf_due = ttk.Label(tab, foreground="#B00020", font=("TkDefaultFont", 10, "bold"))
        self.bf_due.pack(anchor="w", pady=(4, 0))

        cols = [("day", "Day"), ("ex", "Exercise"), ("sets", "Sets x Reps"), ("pct", "% TM"), ("tm", "Training max"),
                ("weight", "Weight / target"), ("logged", "Logged"), ("note", "Guidance")]
        frame, self.plan = self._tree(tab, cols, (130, 175, 95, 55, 110, 125, 95, 300), height=20)
        frame.pack(fill="both", expand=True, pady=(4, 0))
        self.plan.tag_configure("lift", font=("TkDefaultFont", 10, "bold"))
        self.plan.tag_configure("plyo", foreground="#2E7D32")
        self.plan.tag_configure("day", background="#EEF3F8")
        self.plan.bind("<Double-1>", lambda e: self._log_dialog())
        ttk.Label(tab, text="Double-click an exercise (or select it and press Log set) to record your top set, "
                            "box height or jump distance.").pack(anchor="w", pady=(4, 0))
        ttk.Button(tab, text="Log set...", command=self._log_dialog).pack(anchor="w", pady=(4, 0))
        self.plan_rows = {}

    def _step(self, delta):
        self.week.set(self.week_labels[min(WEEKS, max(0, self._week() + delta))])
        self.refresh()

    def _today(self):
        self._save_settings()
        self.week.set(self.week_labels[self._current_week()])
        self.refresh()

    def _save_week_bw(self):
        weight = _num(self.bw_week.get())
        week = self._week()
        if weight:
            self.store.set_bodyweight(BodyWeight(week, self.start_date + timedelta(weeks=week - 1), weight))
        else:
            self.store.delete_bodyweight(week)
        self.refresh()

    def _log_dialog(self):
        sel = self.plan.selection()
        if not sel or sel[0] not in self.plan_rows:
            messagebox.showinfo("Log set", "Select an exercise first", parent=self.root)
            return
        session, p, suggested = self.plan_rows[sel[0]]
        plyo = CATALOG.get(p.exercise) and CATALOG[p.exercise].category == "plyo"
        win = tk.Toplevel(self.root)
        win.title(f"Log {p.exercise}")
        win.transient(self.root)
        d = tk.StringVar(value=session.date(self.start_date).isoformat())
        w = tk.StringVar(value=f"{suggested:g}" if suggested else "")
        r = tk.StringVar(value="1" if plyo else (p.reps if p.reps.isdigit() else ""))
        fields = [("Date", d), (("Box height / distance" if plyo else f"Weight ({self.unit})"), w)]
        if not plyo:
            fields.append(("Reps", r))
        for i, (label, var) in enumerate(fields):
            ttk.Label(win, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(win, textvariable=var, width=12).grid(row=i, column=1, padx=8, pady=4)

        def save():
            weight, reps, day = _num(w.get()), _num(r.get()), _date(d.get())
            if not weight or not reps or not day:
                messagebox.showerror("Log set", "Enter a date (YYYY-MM-DD), weight and reps", parent=win)
                return
            kind = "test" if p.kind == "test" or p.reps in ("Max",) else "training"
            entry = self.store.add_lift(LogEntry(day, p.exercise, weight, int(reps), kind))
            prs = new_prs(self.store.lifts(), entry)
            win.destroy()
            self.refresh()
            if prs:
                messagebox.showinfo("New PR!", f"{p.exercise}\n\n" + "\n".join(prs), parent=self.root)

        ttk.Button(win, text="Save", command=save).grid(row=len(fields), column=0, columnspan=2, pady=8)

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
        jumps = [(name, sorted({e.date: max(x.weight for x in entries if x.exercise == name and x.date == e.date)
                                for e in entries if e.exercise == name}.items()), color, side)
                 for name, color, side in (("Box Jump", COLORS[2], "left"), ("Broad Jump", COLORS[4], "right"))]
        height = _num(self.intake["height"].get())
        standards = [(f"{level} {t:g}", t) for level, _, t in box_jump_targets(height, self.height_unit)] if height else []
        self.plyo_chart.plot(f"Plyometrics - box jump / broad jump ({self.height_unit})", jumps, standards)
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
            points = sorted((e.date, e.weight) for e in entries if e.exercise == ex)
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
        widgets = [("Month (1-12)", ttk.Spinbox(grid, from_=1, to=12, textvariable=self.bf_vars["month"], width=4)),
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
        guide = tk.Text(tab, height=9, wrap="word", font=("TkDefaultFont", 9))
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
        if not month or not 1 <= month <= 12 or not pct or not day:
            messagebox.showerror("Body fat", "Enter month 1-12, date (YYYY-MM-DD) and body fat %", parent=self.root)
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
                                                ("e1rm", "Est. 1RM"), ("kind", "Type")],
                                          (100, 220, 80, 60, 80, 90), height=22)
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
    def refresh(self):
        entries = self.store.lifts()
        self.height_hint.config(text=f"Height in {self.height_unit}; weights and box heights in "
                                     f"{self.unit} / {self.height_unit}.")
        self._refresh_start(entries)
        self._refresh_program(entries)
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
        jumps = [e.weight for e in entries if e.exercise == "Box Jump"]
        best_jump = max(jumps, default=None)
        for level, desc, target in box_jump_targets(height or 0, self.height_unit):
            shown = f"{target:g} {self.height_unit}" if height or level == "Beginner" else "enter height"
            ok = "YES" if best_jump and (height or level == "Beginner") and best_jump >= target else ""
            self.jumps.insert("", "end", values=(level, desc, shown, ok))
        best_txt = f"{best_jump:g} {self.height_unit}" if best_jump else "none logged"
        self.jump_level.config(text=f"Best box jump: {best_txt} - level: "
                                    f"{box_jump_level(best_jump, height, self.height_unit)}")

    def _refresh_program(self, entries):
        week = self._week()
        bw = {b.week: b.weight for b in self.store.bodyweights()}
        self.bw_week.set(f"{bw[week]:g}" if week in bw else "")
        month = next((m for m in range(1, 13) if bodyfat_week(m) == week), None)
        self.bf_due.config(text=f"Body fat test due this week (month {month}) - enter it on the Body tab"
                           if month else "")
        self.plan.delete(*self.plan.get_children())
        self.plan_rows = {}
        increment = self._increment()
        height = _num(self.intake["height"].get())
        best_jump = max((e.weight for e in entries if e.exercise == "Box Jump"), default=0)
        for s in (s for s in self.sessions if s.week == week):
            day = s.date(self.start_date)
            self.plan.insert("", "end", values=(f"{s.day}", day.strftime("%a %b %d"), "", "", "", "", "", ""),
                             tags=("day",))
            cs = cycle_start(self.start_date, s.cycle)
            for i, p in enumerate(s.exercises):
                info = CATALOG.get(p.exercise)
                tm, estimated = training_max(entries, p.exercise, cs) if info and info.category in (
                    "main", "variation") else (None, False)
                weight = p.weight(tm, increment)
                target = None
                if p.exercise == "Box Jump" and height:
                    target = next((t for _, _, t in box_jump_targets(height, self.height_unit) if t > best_jump), None)
                shown = (f"{weight:g}" if weight else
                         f"box {target:g} {self.height_unit}" if target else
                         "enter maxes" if p.is_loaded else "")
                logged = [e for e in entries if e.exercise == p.exercise and e.date == day]
                top = max(logged, key=lambda e: e.e1rm, default=None)
                iid = f"p-{s.week}-{s.day_index}-{i}"
                tags = ("plyo",) if info and info.category == "plyo" else ("lift",) if p.kind != "accessory" else ()
                self.plan.insert("", "end", iid=iid, tags=tags, values=(
                    "", p.exercise, f"{p.sets} x {p.reps}" if p.sets else "", f"{p.percent:g}%" if p.percent else "",
                    (f"{tm:.0f}" + ("*" if estimated else "")) if tm else "", shown,
                    f"{top.weight:g} x {top.reps}" if top else "", p.note))
                self.plan_rows[iid] = (s, p, weight or target)

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
        for m in range(1, 13):
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
                e.date.isoformat(), e.exercise, f"{e.weight:g}", e.reps, f"{e.e1rm:.0f}", e.kind))

    # ----- export -----------------------------------------------------------------
    def export_data(self) -> dict:
        entries = self.store.lifts()
        data = {"units": self.unit, "increment": self._increment(), "start": self.start_date,
                "height": _num(self.intake["height"].get()), "bodyweight_start": _num(self.intake["bodyweight_start"].get()),
                "bodyfat_start": _num(self.intake["bodyfat_start"].get()), "bodyfat_method": self.bf_method.get() or None,
                "name": self.intake["name"].get() or None, "age": _num(self.intake["age"].get()),
                "sex": self.sex.get() or None}
        base = [e for e in entries if e.kind == "baseline"]
        rest = [e for e in entries if e.kind != "baseline"]
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
    root.geometry("1180x760")
    root.minsize(900, 600)
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app._save_settings(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
