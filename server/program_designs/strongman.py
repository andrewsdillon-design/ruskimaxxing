"""Strongman Conditioning: an add-on of finishers that rides on top of any program.

Two finishers a week, done at the end of a training day:

    Finisher A (slot 0, the week's first training day)  sled push, then car push or farmer's carry
    Finisher B (slot 1, the week's last training day)   sled drag, then atlas stones or car pull

It follows the same 52-week calendar as the programs: it builds across each 3-week block, eases off in
deload weeks, and is skipped in taper and test weeks so maxes come in fresh. Loads are set by effort,
not percentages: each note says how hard a trip or rep should feel.

An add-on session's day_index is a slot, not a day: 0 = the first training day of the week,
1 = the last.
"""

from ruskimaxxing.program import CYCLE_WEEKS, CYCLES, WEEKS, Prescription, Session

KIND = "addon"
DAYS_PER_WEEK = 2
DAY_NAMES = ("Finisher A - Push", "Finisher B - Pull and Stones")

EXTRA_EXERCISES = {
    name: {"category": "strongman", "parent": None, "ratio": None}
    for name in ("Sled Push", "Sled Drag", "Car Push", "Car Pull", "Farmer's Carry", "Atlas Stone to Lap",
                 "Atlas Stone Load")
}

SLED = "Load it so each trip is 15-20 seconds of hard driving. Walk back to recover"
DRAG = "Face the sled and walk backward with short, fast steps, then turn and drag it forward"
CAR_PUSH = ("Flat, empty lot only. A driver sits at the wheel, steers, and is ready to brake. Hands on the frame, "
            "body low, drive with the legs")
CAR_PULL = ("Flat, empty lot only, with a driver at the wheel ready to brake. Harness or rope on the tow point, "
            "lean forward and take short, powerful steps")
FARMER = "Heavy handles or dumbbells, stand tall, quick steps. Set them down under control"
LAP = "Pick the stone and lap it, stand, set it down. Learn the lap before going heavy. Tacky or a sleeve on the forearms"
LOAD = "Pick, lap, then extend the hips hard and roll the stone onto the platform or over the bar"

# By week within a 3-week block: (sled trips, distance), (second exercise sets, reps)
BUILD = (
    ((5, "20 yd"), (3, "40 yd")),
    ((6, "20 yd"), (4, "40 yd")),
    ((7, "20 yd"), (4, "50 yd")),
)
STONES = ((3, "3"), (4, "3"), (5, "2"))  # sets x reps by week in block


def _week_plan(week: int):
    """('phase', week-in-block or None) for this calendar week."""
    if week == 0:
        return "Intro", None
    cycle = min(CYCLES + 1, (week - 1) // CYCLE_WEEKS + 1)
    if cycle == CYCLES + 1:
        return ("Off" if week == WEEKS else "Easy"), None
    w = (week - 1) % CYCLE_WEEKS + 1
    if w in (4, 8):
        return "Deload", None
    if w in (11, 12):
        return "Off", None
    return "Build", (w - 1) % 4


def _finisher(slot: int, week: int, phase: str, idx):
    block = 0 if week == 0 else ((week - 1) % CYCLE_WEEKS) // 4
    if phase == "Off":
        return []
    if phase in ("Intro", "Deload", "Easy"):
        easy = "Easy - learn the movement, no grinding"
        if slot == 0:
            return [Prescription("Sled Push", 4, "20 yd", note=f"{easy}. {SLED}", kind="strongman"),
                    Prescription("Farmer's Carry", 2, "40 yd", note=f"{easy}. {FARMER}", kind="strongman")]
        return [Prescription("Sled Drag", 4, "20 yd", note=f"{easy}. {DRAG}", kind="strongman"),
                Prescription("Atlas Stone to Lap", 3, "3", note=f"{easy}. {LAP}", kind="strongman")]
    (trips, dist), (sets2, reps2) = BUILD[idx]
    if slot == 0:
        second = (Prescription("Car Push", sets2, reps2, note=CAR_PUSH, kind="strongman") if block == 1 else
                  Prescription("Farmer's Carry", sets2, reps2, note=FARMER, kind="strongman"))
        return [Prescription("Sled Push", trips, dist, note=SLED, kind="strongman"), second]
    stone_sets, stone_reps = STONES[idx]
    if block == 1:
        second = Prescription("Car Pull", sets2, reps2, note=CAR_PULL, kind="strongman")
    elif block == 2:
        second = Prescription("Atlas Stone Load", stone_sets, stone_reps, note=LOAD, kind="strongman")
    else:
        second = Prescription("Atlas Stone to Lap", stone_sets, stone_reps, note=LAP, kind="strongman")
    return [Prescription("Sled Drag", trips, dist, note=DRAG, kind="strongman"), second]


def build():
    out = []
    for week in range(0, WEEKS + 1):
        phase, idx = _week_plan(week)
        cycle = 0 if week == 0 else min(CYCLES + 1, (week - 1) // CYCLE_WEEKS + 1)
        for slot, name in enumerate(DAY_NAMES):
            ex = _finisher(slot, week, phase, idx)
            if ex:
                out.append(Session(week, cycle, phase, slot, name, tuple(ex)))
    return out
