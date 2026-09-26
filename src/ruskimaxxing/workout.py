"""UI-independent workout logic shared by the desktop and phone apps.

A workout is a list of blocks, one per exercise in a session:
    {"p": Prescription, "rows": [set rows], "source": str, "planned": int, "note": str}
and each set row is a dict of strings/bools the UI binds to:
    {"target": "185 x 6", "weight": "185", "reps": "6", "rpe": "", "done": False}
"""

from dataclasses import dataclass
from datetime import date

from ruskimaxxing.exercises import CATALOG, STEP_HEIGHT, box_jump_targets
from ruskimaxxing.program import build_program, cycle_start, next_monday
from ruskimaxxing.storage import Store
from ruskimaxxing.tracking import LogEntry, new_prs, training_max

DEFAULT_INCREMENT = {"lb": 5.0, "kg": 2.5}
_SESSIONS = build_program()


def number(text) -> float | None:
    """Positive number from user text, else None."""
    try:
        value = float(str(text).strip())
    except ValueError:
        return None
    return value if value > 0 else None


@dataclass(frozen=True)
class Settings:
    start: date
    unit: str = "lb"
    increment: float = 5.0
    height: float | None = None

    @property
    def height_unit(self) -> str:
        return "cm" if self.unit == "kg" else "in"

    @classmethod
    def from_store(cls, store: Store) -> "Settings":
        unit = store.get("units", "lb")
        try:
            start = date.fromisoformat(store.get("start", ""))
        except ValueError:
            start = next_monday()
        return cls(start, unit, number(store.get("increment", "")) or DEFAULT_INCREMENT[unit],
                   number(store.get("height", "")))


def session(week: int, day: int):
    return next(s for s in _SESSIONS if s.week == week and s.day_index == day)


def default_reps(reps: str) -> str:
    """'6' -> 6, '8-10' -> 8, '30-60s' -> 30, '5RM' -> 5, 'Max' -> 1."""
    if reps == "Max":
        return "1"
    digits = ""
    for ch in reps:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return digits


def expected_weight(p, entries, cycle_start_date: date, reps: str, cfg: Settings) -> tuple[str, str]:
    """(pre-filled weight, text describing where it came from) for one prescription."""
    info = CATALOG.get(p.exercise)
    inc, hu = cfg.increment, cfg.height_unit
    if info and info.category == "plyo":
        # like training maxes: only jumps logged before this cycle (or starting values) set the target
        entries = [e for e in entries if e.kind == "baseline" or e.date < cycle_start_date]
        best = max((e.weight for e in entries if e.exercise == p.exercise and e.done), default=0)
        if p.exercise == "Box Jump":
            # train on a box you land safely (your best so far); the next standard is the goal
            start_box = best or STEP_HEIGHT[hu]
            goal = ""
            if cfg.height:
                nxt = next(((lvl, t) for lvl, _, t in box_jump_targets(cfg.height, hu) if t > best), None)
                goal = f" - next standard: {nxt[0]} {nxt[1]:g} {hu}" if nxt else " - Elite!"
            return f"{start_box:g}", f"best {best:g} {hu}{goal}" if best else f"start low{goal}"
        return (f"{best:g}", f"beat {best:g} {hu}") if best else ("", "distance")
    if info and info.category in ("main", "variation"):
        tm, estimated = training_max(entries, p.exercise, cycle_start_date)
        if not tm:
            return "", "enter a starting max"
        note = f"TM {tm:.0f}{' (est.)' if estimated else ''}"
        if p.is_loaded:
            return f"{p.weight(tm, inc):g}", note
        r = int(reps or 1)  # test set: the weight you'd expect for that many reps
        w = round(tm / (1 + r / 30) / inc) * inc if r > 1 else round(tm / inc) * inc
        return f"{w:g}", note + " - try to beat it"
    last = max((e for e in entries if e.exercise == p.exercise and e.done and e.weight > 0),
               key=lambda e: (e.date, e.id or 0), default=None)
    return (f"{last.weight:g}", f"last time {last.weight:g} x {last.reps}") if last else ("", "pick a weight")


def workout_model(store: Store, week: int, day: int, cfg: Settings, use_saved: bool = True) -> list[dict]:
    """Blocks for one session, pre-filled from the plan and overlaid with anything saved."""
    entries = store.lifts()
    s = session(week, day)
    cs = cycle_start(cfg.start, s.cycle)
    saved = {}
    if use_saved:
        for e in store.workout(week, day):
            saved.setdefault(e.exercise, []).append(e)
    blocks = []
    for p in s.exercises:
        reps = default_reps(p.reps)
        weight, source = expected_weight(p, entries, cs, reps, cfg)
        planned = max(p.sets, 1)
        mine = sorted(saved.get(p.exercise, []), key=lambda e: e.set_no or 0)
        rows = []
        for k in range(max(planned, len(mine))):
            e = mine[k] if k < len(mine) else None
            rows.append({
                "target": f"{weight or '-'} x {reps or p.reps}" if k < planned else "extra set",
                "weight": (f"{e.weight:g}" if e.weight else "") if e else weight,
                "reps": (str(e.reps) if e.reps else "") if e else reps,
                "rpe": (f"{e.rpe:g}" if e.rpe else "") if e else "",
                "done": e.done if e else False,
            })
        blocks.append({"p": p, "rows": rows, "source": source, "planned": planned,
                       "note": mine[0].note if mine else ""})
    return blocks


def add_set(blocks: list[dict], index: int) -> None:
    """Append an extra set to block `index`, copying the last set's numbers."""
    rows = blocks[index]["rows"]
    extra = dict(rows[-1]) if rows else {"weight": "", "reps": ""}
    extra.update(target="extra set", done=False, rpe="")
    rows.append(extra)


def mark_all_done(blocks: list[dict]) -> None:
    for b in blocks:
        for row in b["rows"]:
            if row["reps"]:
                row["done"] = True


def workout_prs(others, done_sets) -> list[str]:
    """Best new PR per exercise and type, e.g. 'Squat: 5RM 210'."""
    best = {}
    for e in done_sets:
        plyo = CATALOG.get(e.exercise) and CATALOG[e.exercise].category == "plyo"
        for label in new_prs(others + [e], e):
            if plyo:
                if not label.startswith("1RM"):
                    continue
                label = f"Best {e.weight:g}"
            kind, value = label.rsplit(" ", 1)
            key = (e.exercise, kind)
            if key not in best or float(value) > best[key]:
                best[key] = float(value)
    return [f"{ex}: {kind} {value:g}" for (ex, kind), value in best.items()]


def save_workout(store: Store, week: int, day: int, blocks: list[dict], cfg: Settings):
    """Save every set of a session. Returns (saved entries, new PRs, sets ticked done without reps)."""
    s = session(week, day)
    when = s.date(cfg.start)
    entries, bad = [], []
    for b in blocks:
        p = b["p"]
        kind = "test" if p.kind == "test" or p.reps == "Max" else "training"
        for k, row in enumerate(b["rows"], start=1):
            reps = number(row["reps"])
            if row["done"] and not reps:
                bad.append(f"{p.exercise} set {k}")
            entries.append(LogEntry(when, p.exercise, number(row["weight"]) or 0.0, int(reps or 0), kind,
                                    b.get("note", ""), set_no=k, rpe=number(row["rpe"]),
                                    done=bool(row["done"] and reps)))
    others = [e for e in store.lifts() if not (e.week == week and e.day == day)]
    saved = store.save_workout(week, day, entries)
    return saved, workout_prs(others, [e for e in saved if e.done]), bad


def day_progress(store: Store, week: int, day: int) -> tuple[int, int]:
    """(sets done, sets planned) for a session."""
    planned = sum(max(p.sets, 1) for p in session(week, day).exercises)
    return sum(e.done for e in store.workout(week, day)), planned
