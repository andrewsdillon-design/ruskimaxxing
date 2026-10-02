"""Read-only program catalog for partner sites (/v1/programs).

The JSON files in server/programs/ are written by server/deploy/export_programs.py from the app's own
program generator. Partner sites such as orthodoxbarbellclub.com fetch them server to server, work out
each lifter's weights from his training maxes, and keep their own training logs. No account is needed.
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

PROGRAM_DIR = Path(__file__).resolve().parent.parent / "programs"
SUMMARY_KEYS = ("slug", "kind", "name", "edition", "level", "year", "days_per_week", "weeks", "description")

router = APIRouter(prefix="/v1/programs")


@lru_cache(maxsize=None)
def _load() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(PROGRAM_DIR.glob("*.json"))}


@router.get("")
def list_programs(response: Response):
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {"programs": [{k: prog[k] for k in SUMMARY_KEYS} for prog in _load().values()]}


@router.get("/{slug}")
def get_program(slug: str, response: Response):
    prog = _load().get(slug)
    if prog is None:
        raise HTTPException(404, "No program with that name")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return prog
