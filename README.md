# ruskimaxxing

**A free 12-week beginner program for building strength and muscle.**

Conjugate training for beginners. It combines undulating periodization with the
work of Verkhoshansky, Siff, and Prilepin. This is well-established training
knowledge, and it should be free for everyone.

Available as:

| Format | Get it |
|---|---|
| Excel spreadsheet (Excel, Google Sheets, LibreOffice, Numbers) | [`spreadsheet/RuskiMaxxing-Program.xlsx`](spreadsheet/RuskiMaxxing-Program.xlsx) |
| Windows app | `RuskiMaxxing-Windows.exe` on the [Releases](../../releases) page |
| macOS app | `RuskiMaxxing-macOS.zip` on the [Releases](../../releases) page |
| Linux app | `RuskiMaxxing-Linux.tar.gz` on the [Releases](../../releases) page |
| iPhone / Android | Planned if there's interest |

> The apps aren't code-signed yet. **Windows:** if SmartScreen appears, click *More info → Run anyway*.
> **macOS:** right-click the app → *Open* the first time.

## How it works

1. Enter a recent set for each main lift: the weight and the reps you did.
   New to lifting? Work up to a set of 5 you could just barely complete.
2. The app or spreadsheet estimates your 1-rep max (Epley formula) and fills in every weight.
3. Train **3 days a week** with a rest day between sessions (e.g. Mon / Wed / Fri).

### The 12 weeks

| Weeks | Phase | Focus | Main-lift intensity |
|---|---|---|---|
| 1-3 | Accumulation | Build muscle and work capacity | 60-75% |
| 4 | Deload | Recover | 60% |
| 5-7 | Transmutation | Turn new muscle into strength | 65-82.5% |
| 8 | Deload | Recover | 65% |
| 9-11 | Realization | Heavier, lower-rep strength | 67.5-90% |
| 12 | Test | AMRAP sets to estimate new maxes | 85% |

Then enter your new maxes and run it again.

### The week

| Day | Main lifts | Accessories (muscle) |
|---|---|---|
| Day 1 - Heavy | Squat (heavy), Bench Press (heavy) | Barbell Row, Face Pull, Dumbbell Curl |
| Day 2 - Light | Squat (light), Overhead Press (heavy), Deadlift (medium) | Chin-up / Lat Pulldown, Back Extension, Plank |
| Day 3 - Medium | Squat (medium), Bench Press (medium) | Romanian Deadlift, Incline DB Press, One-Arm DB Row, Triceps Pushdown |

### The principles behind it

- **Prilepin's chart** sets the sets and reps for every main-lift session based on its intensity,
  so volume stays in the range that builds strength without burning you out.
- **Undulating periodization**: each lift rotates through heavy, medium and light days during the week.
- **Block periodization (Verkhoshansky / Siff)**: accumulation, then transmutation, then realization,
  with volume shifting toward intensity and a deload between blocks.
- **Accessory work** adds the hypertrophy volume a beginner needs to gain mass.
  Leave 1-2 reps in the tank, and add weight once you hit the top of the rep range.

Eat in a small calorie surplus with about 0.7-1 g of protein per lb of bodyweight (1.6-2.2 g/kg),
and sleep 7-9 hours.

## For developers

All the training logic lives in one plain-Python package (`src/ruskimaxxing/`).
The spreadsheet and the desktop apps are built from it, and future mobile apps can reuse it too.

```
src/ruskimaxxing/
  prilepin.py   Prilepin's chart
  program.py    the 12-week program (single source of truth)
  excel.py      builds the formula-driven .xlsx
  gui.py        desktop app (tkinter - ships with Python on Windows/macOS/Linux)
  cli.py        command line
packaging/launcher.py   PyInstaller entry point
spreadsheet/            prebuilt blank spreadsheet
```

### Run from source

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

ruskimaxxing                                     # open the desktop app
ruskimaxxing plan --squat 185 5 --bench 135 5 --week 1
ruskimaxxing excel my-program.xlsx
pytest
```

### Build the apps

GitHub Actions (`.github/workflows/build.yml`) builds the Windows, macOS and Linux apps plus the
spreadsheet on every push to `main`. You can download them from the workflow run's *Artifacts*.
To publish a release:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

To build locally for your own OS:

```bash
pyinstaller --onefile --windowed --name RuskiMaxxing packaging/launcher.py
```

If you change the program, regenerate the checked-in spreadsheet:

```bash
ruskimaxxing excel spreadsheet/RuskiMaxxing-Program.xlsx
```

## License

MIT - free to use, share and modify. This is not medical advice; check with a doctor before starting a new training program.
