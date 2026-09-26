"""Catalog of every movement the program uses or tracks.

Each variation names its parent competition lift and a typical strength ratio
to that lift. When someone has no max for a variation yet, its max is estimated
as parent max x ratio until they log a real set of it.
"""

from dataclasses import dataclass

from ruskimaxxing.edition import is_supertotal


@dataclass(frozen=True)
class Exercise:
    name: str
    category: str  # "main", "variation", "accessory" or "plyo"
    parent: str | None = None
    ratio: float | None = None  # typical max relative to the parent lift


POWER = ("Squat", "Bench Press", "Deadlift", "Overhead Press")
OLY = ("Snatch", "Clean & Jerk")
MAIN = POWER + OLY if is_supertotal() else POWER

_VARIATIONS = {
    "Squat": [
        ("Box Squat", 0.90), ("Pause Squat", 0.85), ("Front Squat", 0.80),
        ("Safety Bar Squat", 0.90), ("Pin Squat", 0.85), ("Tempo Squat", 0.80),
    ],
    "Bench Press": [
        ("Close-Grip Bench Press", 0.92), ("1-Board Press", 1.03), ("2-Board Press", 1.06),
        ("3-Board Press", 1.10), ("Pause Bench Press", 0.95), ("Floor Press", 0.95),
        ("Pin Press", 1.00), ("Spoto Press", 0.93), ("Incline Bench Press", 0.80),
    ],
    "Deadlift": [
        ("Romanian Deadlift", 0.70), ("Deficit Deadlift", 0.90), ("Paused Deadlift", 0.85),
        ("Block Pull", 1.05), ("Rack Pull", 1.10), ("Sumo Deadlift", 1.00),
        ("Snatch-Grip Deadlift", 0.80),
    ],
    "Overhead Press": [
        ("Push Press", 1.20), ("Seated Overhead Press", 0.90), ("Z Press", 0.80),
        ("Behind-the-Neck Press", 0.85),
    ],
}

_OLY_VARIATIONS = {
    "Snatch": [
        ("Power Snatch", 0.82), ("Hang Snatch", 0.95), ("Hang Power Snatch", 0.78),
        ("Muscle Snatch", 0.65), ("Snatch Balance", 1.05), ("Snatch Pull", 1.15),
        ("Block Snatch", 0.95),
    ],
    "Clean & Jerk": [
        ("Clean", 1.03), ("Power Clean", 0.85), ("Hang Clean", 0.95), ("Hang Power Clean", 0.80),
        ("Push Jerk", 1.00), ("Split Jerk", 1.03), ("Push Press (Jerk Rack)", 0.85),
        ("Clean Pull", 1.20), ("Block Clean", 0.95),
    ],
}
if is_supertotal():
    _VARIATIONS.update(_OLY_VARIATIONS)

# Tested plyos have standards; the rest rotate through Day 3 (distance / height logged)
PLYOS = ("Box Jump", "Broad Jump", "Vertical Jump", "Depth Jump", "Hurdle Hop", "Lateral Bound",
         "Plyo Push-up", "Seated Box Jump", "Med Ball Chest Pass")

ACCESSORIES = (
    "Barbell Row", "Face Pull", "Dumbbell Curl", "Chin-up", "Lat Pulldown", "Back Extension",
    "Plank", "Incline Dumbbell Press", "One-Arm Dumbbell Row", "Triceps Pushdown",
    "Walking Lunge", "Leg Press", "Hanging Leg Raise", "Dip", "Hammer Curl",
    "Lateral Raise", "Reverse Hyper", "Good Morning", "Glute-Ham Raise",
)

CATALOG: dict[str, Exercise] = {name: Exercise(name, "main") for name in MAIN}
for parent, variations in _VARIATIONS.items():
    for name, ratio in variations:
        CATALOG[name] = Exercise(name, "variation", parent, ratio)
for name in ACCESSORIES:
    CATALOG[name] = Exercise(name, "accessory")
for name in PLYOS:
    CATALOG[name] = Exercise(name, "plyo")

# Variations rotated through Day 3 max-effort slots, one per 3-week block
ROTATION = {
    "Squat": ["Box Squat", "Pause Squat", "Front Squat", "Safety Bar Squat", "Pin Squat"],
    "Bench Press": ["Close-Grip Bench Press", "2-Board Press", "Pause Bench Press",
                    "1-Board Press", "Floor Press", "3-Board Press", "Spoto Press"],
    "Deadlift": ["Romanian Deadlift", "Deficit Deadlift", "Paused Deadlift", "Block Pull"],
    # supertotal only: one Olympic variation slot on Day 3, alternating snatch / clean & jerk work
    "Olympic": ["Power Snatch", "Power Clean", "Hang Snatch", "Hang Clean", "Snatch Balance",
                "Push Jerk", "Block Snatch", "Split Jerk"],
    "Plyo": ["Depth Jump", "Hurdle Hop", "Vertical Jump", "Lateral Bound", "Plyo Push-up", "Seated Box Jump"],
}


def exercise_names(category: str | None = None) -> list[str]:
    return [e.name for e in CATALOG.values() if category is None or e.category == category]


# Jump standards. A ratio is a fraction of the lifter's standing height; an absolute
# value is (inches, cm). Broad and vertical jump numbers are common rules of thumb.
JUMP_STANDARDS = {
    "Box Jump": (
        ("Beginner", "1 step", ("abs", 7.5, 19.0)),
        ("Intermediate", "above knee height", ("ratio", 0.30)),
        ("Proficient", "chest height", ("ratio", 0.72)),
        ("Elite", "head height", ("ratio", 0.93)),
    ),
    "Broad Jump": (
        ("Beginner", "3/4 of your height", ("ratio", 0.75)),
        ("Intermediate", "your height", ("ratio", 1.0)),
        ("Proficient", "1.25 x your height", ("ratio", 1.25)),
        ("Elite", "1.5 x your height", ("ratio", 1.5)),
    ),
    "Vertical Jump": (
        ("Beginner", "12 in / 30 cm", ("abs", 12.0, 30.0)),
        ("Intermediate", "18 in / 46 cm", ("abs", 18.0, 46.0)),
        ("Proficient", "24 in / 61 cm", ("abs", 24.0, 61.0)),
        ("Elite", "30 in / 76 cm", ("abs", 30.0, 76.0)),
    ),
}
LEVELS = ("Beginner", "Intermediate", "Proficient", "Elite")
STEP_HEIGHT = {"in": 7.5, "cm": 19.0}
BOX_JUMP_STANDARDS = tuple((lvl, desc, None if rule[0] == "abs" else rule[1])
                           for lvl, desc, rule in JUMP_STANDARDS["Box Jump"])

PLYO_GUIDE = {
    "Box Jump": "Two-foot jump onto a box, land soft in a quarter squat, STEP down. Log the box height "
                "(floor to top of box).",
    "Broad Jump": "Standing two-foot jump forward, stick the landing. Measure toe line to the back of the "
                  "nearest heel.",
    "Vertical Jump": "Stand side-on to a wall, reach up and mark it; jump and touch as high as you can. "
                     "Log jump mark minus standing reach.",
    "Depth Jump": "Step off a low box (12-18 in / 30-45 cm), land and rebound straight up as fast as possible. "
                  "Log the drop-box height.",
    "Hurdle Hop": "Continuous two-foot hops over a row of 4-6 low hurdles or cones, minimal ground contact. "
                  "Log the hurdle height.",
    "Lateral Bound": "Single-leg bound sideways, stick the landing on the other leg, then back. "
                     "Log distance (each side counts as a rep).",
    "Plyo Push-up": "Explosive push-up so the hands leave the floor. Log reps (distance/height = 1).",
    "Seated Box Jump": "Sit on a box, feet flat, then jump from seated onto a second box. Log the landing-box height.",
    "Med Ball Chest Pass": "Kneeling or standing chest pass for distance with a 6-10 lb / 3-5 kg ball. "
                           "Log the distance.",
}


def jump_targets(exercise: str, height: float | None, unit: str = "in") -> list[tuple[str, str, float | None]]:
    """[(level, description, target)] for a jump with standards (same unit as `height`)."""
    out = []
    for level, desc, rule in JUMP_STANDARDS.get(exercise, ()):
        if rule[0] == "abs":
            value = rule[1] if unit == "in" else rule[2]
        else:
            value = round(height * rule[1], 1) if height else None
        out.append((level, desc, value))
    return out


def jump_level(exercise: str, best: float | None, height: float | None, unit: str = "in") -> str:
    if not best:
        return "Not tested"
    level = "Below beginner"
    for name, _, target in jump_targets(exercise, height, unit):
        if target is None:
            return "Enter your height"
        if best >= target:
            level = name
    return level


def box_jump_targets(height: float, unit: str = "in") -> list[tuple[str, str, float]]:
    return [(l, d, t if t is not None else 0.0) for l, d, t in jump_targets("Box Jump", height, unit)]


def box_jump_level(best: float | None, height: float | None, unit: str = "in") -> str:
    return jump_level("Box Jump", best, height, unit)
