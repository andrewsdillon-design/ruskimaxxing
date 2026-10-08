"""The Expo phone app (mobile/) re-implements the training logic in TypeScript and is tested against
golden data produced by the Python originals. This fails if that data is stale: after changing the
program, workout or PR logic, run `python tools/export_mobile_fixtures.py` and commit the result."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_mobile_golden_data_is_up_to_date():
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "export_mobile_fixtures.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
