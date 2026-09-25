"""Desktop app (Windows / macOS / Linux) built on tkinter."""

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ruskimaxxing import __version__
from ruskimaxxing.excel import build_workbook
from ruskimaxxing.program import MAIN_LIFTS, WEEKS, build_program, estimate_1rm

SETTINGS = Path.home() / ".ruskimaxxing.json"
DEFAULT_INCREMENT = {"lb": 5.0, "kg": 2.5}


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    try:
        SETTINGS.write_text(json.dumps(data, indent=2))
    except OSError:
        pass


def _num(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


class App(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=12)
        self.root = root
        self.sessions = build_program()
        saved = load_settings()

        self.units = tk.StringVar(value=saved.get("units", "lb"))
        self.increment = tk.StringVar(value=f'{saved.get("increment", DEFAULT_INCREMENT[self.units.get()]):g}')
        self.week = tk.StringVar()
        self.lift_vars = {}
        self.max_labels = {}

        self._build_inputs(saved.get("lifts", {}))
        self._build_plan()
        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.refresh()

    # ----- layout -------------------------------------------------------
    def _build_inputs(self, saved_lifts: dict):
        box = ttk.LabelFrame(self, text="1. Your lifts - enter a recent set (reps = 1 if it's a true max)", padding=8)
        box.grid(row=0, column=0, sticky="ew")

        ttk.Label(box, text="Units").grid(row=0, column=0, sticky="w")
        units = ttk.Combobox(box, textvariable=self.units, values=("lb", "kg"), width=5, state="readonly")
        units.grid(row=0, column=1, sticky="w")
        units.bind("<<ComboboxSelected>>", self._units_changed)
        ttk.Label(box, text="Round to").grid(row=0, column=2, sticky="e", padx=(16, 4))
        ttk.Entry(box, textvariable=self.increment, width=6).grid(row=0, column=3, sticky="w")

        for col, text in enumerate(("Lift", "Weight", "Reps", "Estimated 1RM")):
            ttk.Label(box, text=text, font=("TkDefaultFont", 9, "bold")).grid(row=1, column=col, sticky="w", pady=(8, 2))
        for i, lift in enumerate(MAIN_LIFTS, start=2):
            weight, reps = saved_lifts.get(lift, ("", 5))
            w, r = tk.StringVar(value=str(weight or "")), tk.StringVar(value=str(reps or 5))
            self.lift_vars[lift] = (w, r)
            ttk.Label(box, text=lift).grid(row=i, column=0, sticky="w")
            ttk.Entry(box, textvariable=w, width=8).grid(row=i, column=1, sticky="w", pady=1)
            ttk.Spinbox(box, from_=1, to=10, textvariable=r, width=5).grid(row=i, column=2, sticky="w")
            self.max_labels[lift] = ttk.Label(box, text="-", width=12)
            self.max_labels[lift].grid(row=i, column=3, sticky="w")

        for var in (self.increment, *[v for pair in self.lift_vars.values() for v in pair]):
            var.trace_add("write", lambda *_: self.refresh())

    def _build_plan(self):
        box = ttk.LabelFrame(self, text="2. Your program", padding=8)
        box.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        bar = ttk.Frame(box)
        bar.pack(fill="x")
        ttk.Button(bar, text="<", width=3, command=lambda: self._step(-1)).pack(side="left")
        self.week_labels = weeks = [f"Week {w} - {next(s.phase for s in self.sessions if s.week == w)}" for w in range(1, WEEKS + 1)]
        combo = ttk.Combobox(bar, textvariable=self.week, values=weeks, state="readonly", width=28)
        combo.pack(side="left", padx=4)
        combo.bind("<<ComboboxSelected>>", lambda *_: self.refresh())
        self.week.set(weeks[0])
        ttk.Button(bar, text=">", width=3, command=lambda: self._step(1)).pack(side="left")
        ttk.Button(bar, text="Export Excel spreadsheet...", command=self.export).pack(side="right")

        cols = ("exercise", "sets", "weight", "pct", "note")
        self.tree = ttk.Treeview(box, columns=cols, show="tree headings", height=18)
        self.tree.heading("#0", text="Day")
        self.tree.column("#0", width=130, stretch=False)
        for col, text, width in zip(cols, ("Exercise", "Sets x Reps", "Weight", "% 1RM", "Guidance"),
                                    (190, 100, 80, 60, 360)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, stretch=col == "note", anchor="w")
        self.tree.tag_configure("main", font=("TkDefaultFont", 10, "bold"))
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", pady=(8, 0))
        self.tree.pack(fill="both", expand=True, pady=(8, 0))

    # ----- behavior -----------------------------------------------------
    def _units_changed(self, *_):
        self.increment.set(f"{DEFAULT_INCREMENT[self.units.get()]:g}")
        self.refresh()

    def _step(self, delta: int):
        week = min(WEEKS, max(1, self._week_number() + delta))
        self.week.set(self.week_labels[week - 1])
        self.refresh()

    def _week_number(self) -> int:
        return int(self.week.get().split()[1])

    def maxes(self) -> dict[str, float]:
        result = {}
        for lift, (w, r) in self.lift_vars.items():
            weight, reps = _num(w.get()), _num(r.get())
            if weight and reps and reps <= 10:
                result[lift] = estimate_1rm(weight, int(reps))
        return result

    def refresh(self):
        units = self.units.get()
        increment = _num(self.increment.get()) or DEFAULT_INCREMENT[units]
        maxes = self.maxes()
        for lift, label in self.max_labels.items():
            label.config(text=f"{maxes[lift]:.0f} {units}" if lift in maxes else "-")

        self.tree.delete(*self.tree.get_children())
        week = self._week_number()
        for session in (s for s in self.sessions if s.week == week):
            parent = self.tree.insert("", "end", text=session.day, open=True)
            for p in session.exercises:
                weight = p.weight(maxes, increment)
                shown = f"{weight:g} {units}" if weight else ("enter lift" if p.is_main else "")
                self.tree.insert(parent, "end", tags=("main",) if p.is_main else (), values=(
                    p.exercise, f"{p.sets} x {p.reps}" if p.sets else "", shown,
                    f"{p.percent:g}%" if p.percent else "", p.note))
        self._save()

    def _inputs(self) -> dict:
        lifts = {}
        for lift, (w, r) in self.lift_vars.items():
            weight, reps = _num(w.get()), _num(r.get())
            if weight and reps:
                lifts[lift] = (weight, int(reps))
        return {"units": self.units.get(),
                "increment": _num(self.increment.get()) or DEFAULT_INCREMENT[self.units.get()],
                "lifts": lifts}

    def _save(self):
        save_settings(self._inputs())

    def export(self):
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".xlsx", initialfile="RuskiMaxxing-Program.xlsx",
            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        try:
            build_workbook(path, self._inputs())
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc), parent=self.root)
            return
        messagebox.showinfo("Saved", f"Spreadsheet saved to:\n{path}", parent=self.root)


def main() -> None:
    root = tk.Tk()
    root.title(f"RuskiMaxxing {__version__} - Beginner Strength & Mass")
    root.geometry("1000x680")
    root.minsize(760, 520)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
