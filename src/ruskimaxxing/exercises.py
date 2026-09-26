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

PLYOS = ("Box Jump", "Broad Jump")

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
}


def exercise_names(category: str | None = None) -> list[str]:
    return [e.name for e in CATALOG.values() if category is None or e.category == category]


# Box jump standards: box height as a fraction of the lifter's standing height
BOX_JUMP_STANDARDS = (
    ("Beginner", "1 step", None),           # one stair step: 7.5 in / 19 cm
    ("Intermediate", "above knee", 0.30),
    ("Proficient", "chest height", 0.72),
    ("Elite", "head height", 0.93),
)
STEP_HEIGHT = {"in": 7.5, "cm": 19.0}


def box_jump_targets(height: float, unit: str = "in") -> list[tuple[str, str, float]]:
    """[(level, description, box height)] for someone `height` tall (same unit)."""
    return [(level, desc, STEP_HEIGHT[unit] if ratio is None else round(height * ratio, 1))
            for level, desc, ratio in BOX_JUMP_STANDARDS]


def box_jump_level(best: float | None, height: float | None, unit: str = "in") -> str:
    if not best or not height:
        return "Not tested"
    level = "Below beginner"
    for name, _, target in box_jump_targets(height, unit):
        if best >= target:
            level = name
    return level
