# ruskimaxxing

**A free 1-year beginner program for strength, muscle and power, with PR tracking for every lift.**

Conjugate training for beginners. It combines undulating periodization with the
work of Verkhoshansky, Siff and Prilepin, and adds plyometrics. This is
well-established training knowledge, and it should be free for everyone.

> Want the snatch and clean & jerk too? See the sister project
> [**ruskimaxxingsupertotal**](https://github.com/andrewsdillon-design/ruskimaxxingsupertotal).

| Format | Get it |
|---|---|
| Excel spreadsheet | [`spreadsheet/RuskiMaxxing.xlsx`](spreadsheet/RuskiMaxxing.xlsx) |
| Windows app | `RuskiMaxxing-Windows.exe` on the [Releases](../../releases) page |
| macOS app | `RuskiMaxxing-macOS.zip` on the [Releases](../../releases) page |
| Linux app | `RuskiMaxxing-Linux.tar.gz` on the [Releases](../../releases) page |
| iPhone / Android | Planned if there's interest |

## Requirements

### Using the program (no programming needed)

| You're using | What you need | Notes |
|---|---|---|
| **Excel spreadsheet** | Excel 2019, Excel 2021 or Microsoft 365 (Windows or Mac), **or** LibreOffice 5.2+, **or** Google Sheets | Excel 2016 and older **won't work**: they lack the `MAXIFS` function the PR tracking uses. |
| **Windows app** | Windows 10 or 11 (64-bit) | Nothing else to install. It's unsigned, so SmartScreen may warn: click *More info → Run anyway*. |
| **macOS app** | macOS on Apple Silicon (M1 or newer) | Nothing else to install. It's unsigned: the first time, right-click the app → *Open*. On an Intel Mac, run it from source (below). |
| **Linux app** | 64-bit Linux with a desktop (built on Ubuntu 24.04; similar or newer distros) | Nothing else to install. Unpack with `tar -xzf RuskiMaxxing-Linux.tar.gz`, then run `./RuskiMaxxing`. |

### Running from source (any OS)

| Requirement | Windows | macOS | Linux |
|---|---|---|---|
| Python 3.10+ | [python.org](https://www.python.org/downloads/) installer | [python.org](https://www.python.org/downloads/) installer or `brew install python` | Usually preinstalled |
| tkinter (for the desktop app) | Included with the python.org installer | Included with python.org; with Homebrew: `brew install python-tk` | Debian/Ubuntu: `sudo apt install python3-tk`<br>Fedora: `sudo dnf install python3-tkinter`<br>Arch: `sudo pacman -S tk` |
| openpyxl (for Excel export) | `pip install -r requirements.txt` | same | same |

Python packages are listed in [`requirements.txt`](requirements.txt) (for using the program) and
[`requirements-dev.txt`](requirements-dev.txt) (for tests and building the apps).

**Optional, for developers only:** LibreOffice (`soffice`) lets the spreadsheet test recalculate every
formula, and Xvfb (`xvfb-run`, Linux) runs the desktop-app test without a screen. Both tests skip
automatically if these aren't installed.

## Getting started

1. **Intake** (Start Here tab in the app / sheet in Excel): units, plate rounding, your start Monday,
   **height** (sets your box jump standards), bodyweight, and optionally body fat, age and sex.
2. **Starting maxes**, either way works:
   - **Enter what you know.** Any movement or variation, the weight and the reps (1 for a true max, or e.g. 185 × 5).
   - **Test.** Run **Week 0**, an optional test week, and log what you hit.

   Variations you haven't done yet are estimated from the main lift until you log them.
3. Train 3 days a week (e.g. Mon / Wed / Fri). Log your top set of each exercise.

## The year

| Weeks | What happens |
|---|---|
| 0 | Optional baseline test week |
| 1-12, 13-24, 25-36, 37-48 | Four 12-week cycles (below) |
| **12, 24, 36, 48** | **Test weeks**: new maxes on every main lift, the block's variations, and your jumps |
| 49-51 | Transition: lighter volume work |
| 52 | Full deload before the next year |

### Each 12-week cycle

| Cycle week | Phase | Main-lift intensity |
|---|---|---|
| 1-3 | Accumulation: build muscle and work capacity | 60-75% |
| 4 | **Deload** | 60% |
| 5-7 | Transmutation: turn muscle into strength | 65-82.5% |
| 8 | **Deload** | 65% |
| 9-10 | Realization: heavy, low-rep strength | 67.5-90% |
| 11 | **Taper**: volume cut ~50%, intensity kept, so you arrive at the test fresh | 65-80% |
| 12 | **Test** | new maxes |

Every percentage is of that exercise's **own training max**: the best estimated 1RM logged before the
cycle started. So each cycle automatically builds on the last test.

### Each week

| Day | Plyometrics | Main lifts | Accessories |
|---|---|---|---|
| 1 - Heavy | Box jump | Squat (heavy), Bench (heavy) | Row, face pull, curl |
| 2 - Light | Broad jump | Squat (light), Overhead press (heavy), Deadlift (medium) | Chin-up, back extension, plank |
| 3 - Variations | Box jump | Rotating squat / bench / deadlift variations (e.g. box squat, 2-board press, deficit deadlift) | Incline DB press, DB row, pushdown |

Day 3 variations rotate every 3-week block (conjugate style), so over the year you build and test
PRs on many variations.

### Box jump standards (worked out from your height)

| Level | Box height |
|---|---|
| Beginner | 1 step (7.5 in / 19 cm) |
| Intermediate | Above knee height (~30% of height) |
| Proficient | Chest height (~72% of height) |
| Elite | Head height (~93% of height) |

## PR tracking

- **Every movement and every variation** gets its own record: squat, box squat, pause squat, bench,
  1-board, 2-board, 3-board, floor press, deficit deadlift, block pull, and so on, plus accessories and jumps.
- For each one you get the **best estimated 1RM** and **rep maxes for 1, 2, 3, 4, 5, 6, 8, 10 and 12 reps**
  (a rep max is the heaviest weight lifted for *at least* that many reps).
- The app pops up **"New PR!"** when you log one. The spreadsheet flags PRs in red.
- **Box jump**: your best height is tracked and shown against your standard.

## Body tracking and charts

- **Bodyweight: once a week.** Same day, first thing in the morning, before eating.
- **Body fat: once a month**, with the date, %, method and your weight at the test (for lean and fat mass).
  The app and spreadsheet include a guide to getting consistent results from a **Bod Pod**,
  **InBody** or **hydrostatic ("dunk tank")** test.
- **Charts** (app Progress tab, spreadsheet Progress sheet):
  - main lifts' estimated 1RM against bodyweight,
  - box jump and broad jump against the standards,
  - bodyweight and body fat %.

  The app's PRs tab charts any single movement against bodyweight.

## The spreadsheet

| Sheet | What's on it |
|---|---|
| **Start Here** | Intake, starting maxes, PR board, box jump standards, Prilepin's chart, links to every week, instructions |
| **Week 00 … Week 52** | One sheet per week: every weight filled in, yellow cells to log your sets, weekly bodyweight, body fat reminders, previous/next links |
| Log | Anything extra you lift |
| PRs | Every movement and variation: best e1RM plus 1-12 rep maxes |
| Maxes | Each cycle's training max per exercise (estimated ones in grey) |
| Body | Weekly bodyweight, monthly body fat, testing guide |
| Progress | Charts |

## For developers

All training logic is plain Python in `src/ruskimaxxing/`, shared by the spreadsheet, the desktop
apps and (later) mobile apps.

```
edition.py     "standard" or "supertotal" (the only line the supertotal repo changes)
exercises.py   every movement, variation ratios, box jump standards
prilepin.py    Prilepin's chart
program.py     the 52-week program
tracking.py    PRs, rep maxes, training maxes, body measurements
storage.py     local SQLite database for the app
excel.py       builds the formula-driven workbook
gui.py         desktop app (tkinter)
cli.py         command line
```

```bash
pip install -r requirements-dev.txt
ruskimaxxing                                   # desktop app
ruskimaxxing plan --squat 185 5 --bench 135 5 --week 1
ruskimaxxing excel my-program.xlsx
pytest                                         # xvfb-run -a pytest on a headless Linux box
```

The desktop app keeps its data in `~/.ruskimaxxing/data.db` (`C:\Users\<you>\.ruskimaxxing\data.db` on Windows).

**Builds:** GitHub Actions (`.github/workflows/build.yml`) tests on Windows, macOS and Linux, then builds
the three apps and the spreadsheet. To publish a release, go to **Actions → Build apps → Run workflow**
and enter a version (e.g. `v2.0.0`), or push a `v*` tag.

After changing the program, regenerate the checked-in spreadsheet with
`ruskimaxxing excel spreadsheet/RuskiMaxxing.xlsx`.

## License

MIT: free to use, share and modify. This is not medical advice; check with a doctor before starting a new training program.
