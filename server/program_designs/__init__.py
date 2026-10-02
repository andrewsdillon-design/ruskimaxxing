"""Programs for partner sites (orthodoxbarbellclub.com), served by /v1/programs.

Each module has build() -> list of program.Session, plus optional DAYS_PER_WEEK and EXTRA_EXERCISES.
server/deploy/export_programs.py runs them with src/ on the path and writes server/programs/*.json.
"""
