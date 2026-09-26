"""Which program this build is.

"standard"   - squat, bench press, deadlift, overhead press (+ plyometrics)
"supertotal" - adds the snatch and clean & jerk (the ruskimaxxingsupertotal repo)
"""

import os

# The ruskimaxxingsupertotal repo sets this to "supertotal"; the env var overrides it for testing.
DEFAULT_EDITION = "standard"
EDITION = os.environ.get("RUSKIMAXXING_EDITION", DEFAULT_EDITION)

NAMES = {
    "standard": "RuskiMaxxing",
    "supertotal": "RuskiMaxxing Supertotal",
}


def is_supertotal() -> bool:
    return EDITION == "supertotal"


def app_name() -> str:
    return NAMES.get(EDITION, NAMES["standard"])
