"""Build the standalone Excel workbook.

Everything is driven by formulas, so the file works on its own in Excel 2019+,
Microsoft 365, LibreOffice or Google Sheets. Sheet order:

  Start Here      step 1 intake (height, bodyweight...), step 2 starting maxes,
                  PR board, jump standards, plyometrics guide, Prilepin's chart,
                  links to every month, instructions
  Baseline        week 0 - optional test week
  Month 01-13     four training weeks per sheet (3 months = one 12-week cycle).
                  Every set has its own row, pre-filled with the target weight
                  and reps - overwrite what differed and mark Done. Bodyweight
                  on each week's header row, body fat at the top of the month.
  Log             any extra sets (off-program work, extra variations, re-tests)
  PRs             best e1RM and 1-12 rep maxes for every movement and variation
  Maxes           training max per exercise per cycle (best e1RM before the cycle)
  Body            weekly bodyweight + monthly body fat (collected from the month sheets)
  Progress        charts: strength vs bodyweight, bodyweight, body fat / lean mass
"""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink

from ruskimaxxing.edition import app_name
from ruskimaxxing.exercises import CATALOG, JUMP_STANDARDS, LEVELS, MAIN, PLYO_GUIDE
from ruskimaxxing.prilepin import ZONES
from ruskimaxxing.program import (CYCLE_WEEKS, CYCLES, MONTHS, SHOULDER_TIP, WEEKS, build_program, month_of,
                                  month_weeks, next_monday, week_label)
from ruskimaxxing.tracking import BODYFAT_GUIDE, BODYFAT_METHODS, REP_MAX_COUNTS

# Byzantine palette: imperial purple, gold, crimson, ivory
PURPLE, GOLD, CRIMSON, IVORY = "4A1942", "C9A227", "8B1A1A", "F6EFDE"
HEADER_FILL = PatternFill("solid", fgColor=PURPLE)
HEADER_FONT = Font(bold=True, color="F2D675")
SECTION_FONT = Font(bold=True, size=13, color=PURPLE)
STEP_FONT = Font(bold=True, size=14, color=CRIMSON)
INPUT_FILL = PatternFill("solid", fgColor="FFF4CC")
DAY_FILL = PatternFill("solid", fgColor="EDE3F0")
EX_FILL = PatternFill("solid", fgColor=IVORY)
LINK_FONT = Font(color="5B2C83", underline="single", bold=True)
PR_FONT = Font(bold=True, color=CRIMSON)
PHASE_FILLS = {
    "Baseline": "E4D9EC", "Accumulation": "E3EFD9", "Transmutation": "F7E6C4", "Realization": "F2D0CC",
    "Deload": "E6E2DA", "Taper": "E4D9EC", "Test": "F2D675", "Transition": "DCEBEA",
}
THIN = Side(style="thin", color="C8BBA0")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HIDE_ZERO = '#,##0.#;-#,##0.#;""'
LOGO = Path(__file__).resolve().parent / "assets" / "logo.png"

INTAKE = [  # (label, key, default) - rows 5..14 of Start Here, column B
    ("Name (optional)", "name", None),
    ("Units (lb or kg)", "units", "lb"),
    ("Round weights to nearest", "increment", 5),
    ("Start date (a Monday)", "start", None),
    ("HEIGHT (inches if lb, cm if kg)", "height", None),
    ("STARTING BODYWEIGHT", "bodyweight_start", None),
    ("Starting body fat % (optional)", "bodyfat_start", None),
    ("Body fat method", "bodyfat_method", None),
    ("Age (optional)", "age", None),
    ("Sex (optional)", "sex", None),
]
INTAKE_FIRST = 5
SH = "'Start Here'"


def _intake_ref(key: str) -> str:
    return f"{SH}!$B${INTAKE_FIRST + [k for _, k, _ in INTAKE].index(key)}"


UNITS, ROUNDING, START, HEIGHT = (_intake_ref(k) for k in ("units", "increment", "start", "height"))
START_BW, START_BF, BF_METHOD = (_intake_ref(k) for k in ("bodyweight_start", "bodyfat_start", "bodyfat_method"))
BASE_FIRST, BASE_ROWS = 19, 40
LOG_ROWS = 1000
JUMPS = tuple(JUMP_STANDARDS)  # Box Jump, Broad Jump, Vertical Jump
# month sheet columns
COLS = ["Day", "Date", "Exercise / set", "Scheme", "Target reps", "% TM", "Training max", "Target",
        "Actual weight / height", "Actual reps", "RPE", "Done", "Est. 1RM", "PR", "Notes / guidance"]
BF_CELLS = {"date": "D3", "pct": "F3", "method": "H3", "weight": "J3"}

INSTRUCTIONS = [
    "How to use this workbook",
    "1. STEP 1 (left): fill in the intake - especially HEIGHT (sets your jump standards) and bodyweight.",
    "2. STEP 2: enter starting maxes you know (any movement, weight and reps), OR run the Baseline sheet (week 0).",
    "   Variations you haven't done yet are estimated from the main lift until you log them.",
    "3. Each month has its own sheet (Month 01-13, links above). Every set has its own row, already filled in",
    "   with the target weight and reps. Overwrite anything that was different, pick RPE if you like, and",
    "   put a mark (the dropdown's check) in Done. Only sets marked Done count toward PRs and maxes.",
    "4. Bodyweight: once a week, on each week's purple header row. Body fat: once a month, at the top of each",
    "   month sheet (see the Body sheet for how to prepare for a Bod Pod, InBody or hydrostatic test).",
    "5. Every 12th week (end of months 3, 6, 9, 12) is a test week. Those numbers become next cycle's maxes.",
    "6. PR board and jump standards below update as you log. PRs sheet = every movement and variation.",
    "   Progress sheet charts strength next to bodyweight and body fat.",
    "7. Train 3 days a week (Mon/Wed/Fri). Warm up before every main lift: empty bar x 10, then 3-4 sets up.",
    "",
    "Eat enough to grow: a small calorie surplus and ~0.7-1 g protein per lb bodyweight (1.6-2.2 g/kg). Sleep 7-9 h.",
    "Free for everyone - MIT license. Not medical advice; check with a doctor before starting.",
]


def month_sheet(month: int) -> str:
    return "Baseline" if month == 0 else f"Month {month:02d}"


def _header(ws, row, headers, first_col=1):
    for col, text in enumerate(headers, start=first_col):
        c = ws.cell(row, col, text)
        c.fill, c.font, c.border = HEADER_FILL, HEADER_FONT, BOX
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _widths(ws, widths, first_col=1):
    for i, w in enumerate(widths, start=first_col):
        ws.column_dimensions[get_column_letter(i)].width = w


def _input(cell, value=None):
    if value is not None:
        cell.value = value
    cell.fill, cell.border = INPUT_FILL, BOX
    return cell


def _link(cell, text, sheet):
    # In-workbook link via `location`. A "#Sheet!A1" string would be stored as an external
    # URL relationship, which Excel rejects as corrupt when the sheet name has spaces.
    cell.value = text
    cell.hyperlink = Hyperlink(ref=cell.coordinate, location=f"'{sheet}'!A1", display=str(text))
    cell.font = LINK_FONT
    return cell


def _show_axes(chart):
    # openpyxl 3.1 writes axes as deleted unless told otherwise; Excel then hides them
    chart.x_axis.delete = False
    chart.y_axis.delete = False


def _e1rm(w, r):
    return f'=IF(OR({w}="",{r}=""),"",IF({r}=1,{w},ROUND({w}*(1+{r}/30),1)))'


def _reps_number(reps: str) -> int | None:
    """'6' -> 6, '8-10' -> 8, '30-60s' -> 30, '5RM' -> 5, 'Max' -> 1."""
    if reps == "Max":
        return 1
    digits = ""
    for ch in reps:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


class _Book:
    def __init__(self, data: dict | None):
        self.data = data or {}
        self.wb = Workbook()
        self.lists = self.wb.active
        self.lists.title = "Lists"
        names = list(CATALOG)
        for i, name in enumerate(names, start=1):
            self.lists.cell(i, 1, name)
        for i, m in enumerate(BODYFAT_METHODS, start=1):
            self.lists.cell(i, 2, m)
        self.lists.sheet_state = "hidden"
        self.ex_list = f"Lists!$A$1:$A${len(names)}"
        self.method_list = f"Lists!$B$1:$B${len(BODYFAT_METHODS)}"
        self.row_of = {name: 2 + i for i, name in enumerate(names)}  # same row on PRs and Maxes
        self.sets_refs = []   # (sheet, set row, day row, exercise, plyo) for every loggable set
        self.bw_refs = {}     # week -> "'Month 05'!$I$12"
        self.log_rows = max(LOG_ROWS, len(self.data.get("log", [])) + 200)
        self.sessions = build_program()
        self.jump_targets = {}  # (jump, level) -> Start Here cell
        self.cycle_first_set = {}  # cycle -> index into sets_refs of its first set

    @property
    def sets_rows(self) -> int:
        return len(self.sets_refs)

    def dv(self, ws, formula):
        dv = DataValidation(type="list", formula1=formula, allow_blank=True, showErrorMessage=False)
        ws.add_data_validation(dv)
        return dv

    # -- MAXIFS over every place a set can be logged ---------------------------------
    def _sources(self, cols, ex_ref, extra=None, sets_end=None):
        """MAX of MAXIFS over Start Here baseline, the month sheets (via Sets) and Log.

        `sets_end` limits the Sets range to rows logged before a cycle starts. Training
        maxes MUST use that limit: the month sheets' pre-filled weights depend on them,
        so scanning the whole range would be a circular reference.
        """
        extra = extra or {}
        base_end, log_end = BASE_FIRST + BASE_ROWS - 1, self.log_rows + 1
        sets_end = self.sets_rows + 1 if sets_end is None else sets_end
        sh, st, lg = cols
        parts = [
            (f"{SH}!${sh}${BASE_FIRST}:${sh}${base_end}", f"{SH}!$A${BASE_FIRST}:$A${base_end}", extra.get("base")),
            (f"Log!${lg}$2:${lg}${log_end}", f"Log!$B$2:$B${log_end}", extra.get("log")),
        ]
        if sets_end >= 2:
            parts.insert(1, (f"Sets!${st}$2:${st}${sets_end}", f"Sets!$B$2:$B${sets_end}", extra.get("sets")))
        return "MAX(" + ",".join(
            f"_xlfn.MAXIFS({v},{n},{ex_ref}{',' + more if more else ''})" for v, n, more in parts) + ")"

    def _rep_max(self, ex_ref, n):
        return self._sources(("B", "C", "C"), ex_ref, {
            "base": f"{SH}!$C${BASE_FIRST}:$C${BASE_FIRST + BASE_ROWS - 1},\">={n}\"",
            "sets": f'Sets!$D$2:$D${self.sets_rows + 1},">={n}"',
            "log": f'Log!$D$2:$D${self.log_rows + 1},">={n}"'})

    # -- Start Here ----------------------------------------------------------------
    def start_sheet(self):
        ws = self.wb.create_sheet("Start Here", 0)
        ws.sheet_properties.tabColor = PURPLE
        ws["A1"] = f"{app_name().upper()}"
        ws["A1"].font = Font(bold=True, size=22, color=PURPLE)
        ws["A2"] = "1-year strength, mass & power program  -  yellow cells are yours to fill in"
        ws["A2"].font = Font(italic=True, color=CRIMSON)
        if LOGO.exists():
            try:
                from openpyxl.drawing.image import Image
                logo = Image(str(LOGO))
                logo.width = logo.height = 150
                ws.add_image(logo, "N1")
            except ImportError:  # Pillow not installed - skip the picture, keep the workbook
                pass

        ws["A3"] = SHOULDER_TIP
        ws["A3"].font = Font(bold=True, color=IVORY)
        ws["A3"].fill = PatternFill("solid", fgColor=CRIMSON)
        for col in range(2, 14):
            ws.cell(3, col).fill = PatternFill("solid", fgColor=CRIMSON)
        ws.cell(4, 1, "STEP 1 - INTAKE (fill in first)").font = STEP_FONT
        keys = [k for _, k, _ in INTAKE]
        for i, (label, key, default) in enumerate(INTAKE):
            r = INTAKE_FIRST + i
            value = self.data.get(key, default)
            if key == "start":
                value = value or next_monday()
            c = ws.cell(r, 1, label)
            c.border = BOX
            if label.isupper() or label.startswith(("HEIGHT", "STARTING")):
                c.font = Font(bold=True, color=PURPLE)
            c = _input(ws.cell(r, 2), value)
            if key == "start":
                c.number_format = "yyyy-mm-dd"
        ws.cell(INTAKE_FIRST + len(INTAKE), 1,
                "Height sets your box / broad jump standards. Bodyweight is then logged weekly on the month sheets.")
        for key, formula in (("units", '"lb,kg"'), ("sex", '"Male,Female"'), ("bodyfat_method", self.method_list)):
            self.dv(ws, formula).add(f"B{INTAKE_FIRST + keys.index(key)}")

        ws.cell(BASE_FIRST - 2, 1, "STEP 2 - STARTING MAXES (any movement or variation)").font = STEP_FONT
        _header(ws, BASE_FIRST - 1, ["Exercise", "Weight / height", "Reps", "Est. 1RM"])
        dv = self.dv(ws, self.ex_list)
        seed = list(self.data.get("baseline", []))
        defaults = [*MAIN, "Box Squat", "Close-Grip Bench Press", "Romanian Deadlift", *JUMPS]
        for i in range(BASE_ROWS):
            r = BASE_FIRST + i
            if i < len(seed):
                ex, w, reps = seed[i]
            else:
                ex, w, reps = (defaults[i] if not seed and i < len(defaults) else None), None, None
            _input(ws.cell(r, 1), ex)
            _input(ws.cell(r, 2), w)
            _input(ws.cell(r, 3), reps)
            c = ws.cell(r, 4, _e1rm(f"B{r}", f"C{r}"))
            c.border, c.font = BOX, Font(bold=True)
            dv.add(f"A{r}")
        ws.cell(BASE_FIRST + BASE_ROWS, 1, "Jumps: enter the height or distance as 'Weight / height' with reps = 1.")

        # PR board (F:K)
        ws["F4"] = "PR BOARD"
        ws["F4"].font = STEP_FONT
        _header(ws, 5, ["Lift", "Best est. 1RM", "1RM", "3RM", "5RM", "10RM"], first_col=6)
        rm_col = {n: get_column_letter(4 + REP_MAX_COUNTS.index(n)) for n in (1, 3, 5, 10)}
        r = 6
        for lift in MAIN:
            pr = self.row_of[lift]
            ws.cell(r, 6, lift).font = Font(bold=True)
            c = ws.cell(r, 7, f"=PRs!C{pr}")
            c.number_format, c.font = HIDE_ZERO, Font(bold=True, color=PURPLE)
            for j, n in enumerate((1, 3, 5, 10)):
                ws.cell(r, 8 + j, f"=PRs!{rm_col[n]}{pr}").number_format = HIDE_ZERO
            for col in range(6, 12):
                ws.cell(r, col).border = BOX
            r += 1
        ws.cell(r, 6, "Total (e1RM)").font = Font(bold=True)
        c = ws.cell(r, 7, "=" + "+".join(f"G{6 + i}" for i in range(len(MAIN))))
        c.number_format, c.font = HIDE_ZERO, Font(bold=True, color=CRIMSON)

        # Jump standards (F:I)
        top = r + 2
        ws.cell(top, 6, "PLYOMETRIC STANDARDS (from your height)").font = STEP_FONT
        _header(ws, top + 1, ["Level", *JUMPS], first_col=6)
        for i, level in enumerate(LEVELS):
            rr = top + 2 + i
            ws.cell(rr, 6, level).font = Font(bold=True)
            ws.cell(rr, 6).border = BOX
            for j, jump in enumerate(JUMPS):
                desc, rule = next((d, rl) for lv, d, rl in JUMP_STANDARDS[jump] if lv == level)
                if rule[0] == "abs":
                    f = f'=IF({UNITS}="kg",{rule[2]},{rule[1]})'
                else:
                    f = f'=IF({HEIGHT}="","enter height",ROUND({HEIGHT}*{rule[1]},1))'
                c = ws.cell(rr, 7 + j, f)
                c.border, c.alignment = BOX, Alignment(horizontal="center")
                self.jump_targets[(jump, level)] = f"{SH}!${get_column_letter(7 + j)}${rr}"
        rr = top + 2 + len(LEVELS)
        ws.cell(rr, 6, "Your best").font = Font(bold=True, color=PURPLE)
        ws.cell(rr + 1, 6, "Your level").font = Font(bold=True, color=PURPLE)
        for j, jump in enumerate(JUMPS):
            col = get_column_letter(7 + j)
            best = f"PRs!D{self.row_of[jump]}"
            ws.cell(rr, 7 + j, f"={best}").number_format = HIDE_ZERO
            t = [f"{col}{top + 2 + i}" for i in range(len(LEVELS))]
            level = f'=IF({best}=0,"Not tested",IF(NOT(ISNUMBER({t[3]})),"Enter height",' \
                    f'IF({best}>={t[3]},"Elite",IF({best}>={t[2]},"Proficient",IF({best}>={t[1]},"Intermediate",' \
                    f'IF({best}>={t[0]},"Beginner","Below beginner"))))))'
            c = ws.cell(rr + 1, 7 + j, level)
            c.font, c.alignment = Font(bold=True, color=CRIMSON), Alignment(horizontal="center")
        ws.cell(rr + 2, 6, "Box: 1 step / above knee / chest / head height.  Broad: 3/4, 1x, 1.25x, 1.5x your "
                           "height.  Vertical: 12 / 18 / 24 / 30 in (rules of thumb).")

        # Plyometrics guide
        top = rr + 4
        ws.cell(top, 6, "PLYOMETRICS GUIDE - how to do and measure each move").font = STEP_FONT
        for i, (name, text) in enumerate(PLYO_GUIDE.items()):
            ws.cell(top + 1 + i, 6, name).font = Font(bold=True, color="2E7D32")
            ws.cell(top + 1 + i, 8, text)

        # Prilepin's chart
        top += 2 + len(PLYO_GUIDE)
        ws.cell(top, 6, "PRILEPIN'S CHART").font = STEP_FONT
        _header(ws, top + 1, ["% of max", "Reps per set", "Optimal total", "Total range"], first_col=6)
        for i, (label, z) in enumerate(zip(("Under 70%", "70-80%", "80-90%", "90%+"), ZONES)):
            for col, val in enumerate((label, f"{z.reps_per_set[0]}-{z.reps_per_set[1]}", z.optimal_total,
                                       f"{z.total_range[0]}-{z.total_range[1]}"), start=6):
                c = ws.cell(top + 2 + i, col, val)
                c.border, c.alignment = BOX, Alignment(horizontal="center")
        ws.cell(top + 6, 6, "Every loaded session's sets x reps come from this chart.")

        # Month links and instructions
        top += 8
        ws.cell(top, 6, "GO TO MONTH").font = STEP_FONT
        for m in range(0, MONTHS + 1):
            weeks = month_weeks(m)
            label = "Baseline (wk 0)" if m == 0 else f"Month {m:02d} (wk {weeks[0]}-{weeks[-1]})"
            c = _link(ws.cell(top + 1 + m // 4, 6 + (m % 4) * 2), label, month_sheet(m))
            phase = next(s.phase for s in self.sessions if s.week == weeks[-1])
            c.fill = PatternFill("solid", fgColor=PHASE_FILLS[phase])
        top += 3 + MONTHS // 4
        for i, line in enumerate(INSTRUCTIONS):
            ws.cell(top + i, 6, line).font = STEP_FONT if i == 0 else Font()
        _widths(ws, [34, 14, 8, 11, 3, 18, 15, 15, 15, 10, 10, 10, 10, 10])

    # -- Month sheets -------------------------------------------------------------------
    def month_sheets(self):
        bodyweights = self.data.get("bodyweight", {})
        fats = self.data.get("bodyfat", {})
        for m in range(0, MONTHS + 1):
            ws = self.wb.create_sheet(month_sheet(m))
            weeks = month_weeks(m)
            cycle = (weeks[-1] - 1) // CYCLE_WEEKS + 1 if m else 0
            where = "Baseline test (optional)" if m == 0 else (
                f"Transition" if cycle > CYCLES else f"Cycle {cycle}")
            ws.sheet_properties.tabColor = PHASE_FILLS[next(s.phase for s in self.sessions if s.week == weeks[-1])]
            ws["A1"] = f"{month_sheet(m).upper()}  -  weeks {weeks[0]}-{weeks[-1]}  -  {where}" if m else \
                "BASELINE  -  week 0  -  optional test week (skip it if you entered starting maxes)"
            ws["A1"].font = Font(bold=True, size=15, color=PURPLE)
            if m > 0:
                _link(ws["A2"], f"< {month_sheet(m - 1)}", month_sheet(m - 1))
            _link(ws["C2"], "Start Here", "Start Here")
            if m < MONTHS:
                _link(ws["E2"], f"{month_sheet(m + 1)} >", month_sheet(m + 1))
            if m > 0:
                ws["A3"] = "BODY FAT (once this month)"
                ws["A3"].font = Font(bold=True, color=CRIMSON)
                d, pct, method, weight = fats.get(m, (None,) * 4)
                for label_col, key, value in (("C3", "date", d), ("E3", "pct", pct), ("G3", "method", method),
                                              ("I3", "weight", weight)):
                    ws[label_col] = {"date": "Date", "pct": "Body fat %", "method": "Method",
                                     "weight": "Weight at test"}[key]
                    ws[label_col].alignment = Alignment(horizontal="right")
                    cell = _input(ws[BF_CELLS[key]], value)
                    if key == "date":
                        cell.number_format = "yyyy-mm-dd"
                self.dv(ws, self.method_list).add(BF_CELLS["method"])
                _link(ws["L3"], "How to test", "Body")
            ws["A4"] = ("Every set is filled in with the plan. Change what was different, mark Done. "
                        "Enter bodyweight once per week on the purple week rows.")
            ws["A4"].font = Font(italic=True, color="666666")
            _header(ws, 5, COLS)
            ws.freeze_panes = "D6"
            done_dv = self.dv(ws, '"✓"')
            rpe_dv = self.dv(ws, '"6,6.5,7,7.5,8,8.5,9,9.5,10"')
            row = 6
            for week in weeks:
                sessions = [s for s in self.sessions if s.week == week]
                self.cycle_first_set.setdefault(sessions[0].cycle, len(self.sets_refs))
                fill = PatternFill("solid", fgColor=PHASE_FILLS[sessions[0].phase])
                c = ws.cell(row, 1, week_label(week).upper())
                c.font = Font(bold=True, size=12, color=PURPLE)
                for col in range(1, len(COLS) + 1):
                    ws.cell(row, col).fill = fill
                ws.cell(row, 8, "Bodyweight:").font = Font(bold=True, color=PURPLE)
                ws.cell(row, 8).alignment = Alignment(horizontal="right")
                bw = bodyweights.get(week)
                if bw is None and week == 0:
                    bw = f'=IF({START_BW}="","",{START_BW})'
                _input(ws.cell(row, 9), bw)
                self.bw_refs[week] = f"'{ws.title}'!$I${row}"
                row += 1
                for s in sessions:
                    row = self._session_rows(ws, s, row, done_dv, rpe_dv)
                row += 1
            _widths(ws, [15, 11, 26, 10, 7, 6, 9, 9, 12, 8, 6, 6, 9, 5, 60])
            ws.page_setup.orientation = "landscape"
            ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
            ws.sheet_properties.pageSetUpPr.fitToPage = True

    def _session_rows(self, ws, s, row, done_dv, rpe_dv):
        offset = (s.week - 1) * 7 + (0, 2, 4)[s.day_index]
        day_row = row
        ws.cell(row, 1, s.day).font = Font(bold=True)
        c = ws.cell(row, 2, f"={START}+{offset}")
        c.number_format, c.font = "ddd mmm d", Font(bold=True)
        for col in range(1, len(COLS) + 1):
            ws.cell(row, col).fill = DAY_FILL
        row += 1
        cycle_col = get_column_letter(4 + (s.cycle or 1))  # Maxes: E = cycle 1 ... I = transition
        for p in s.exercises:
            info = CATALOG.get(p.exercise)
            pr_row = self.row_of.get(p.exercise)
            plyo = bool(info and info.category == "plyo")
            lifting = bool(info and info.category in ("main", "variation"))
            reps = _reps_number(p.reps)
            hdr = row
            baseline = s.week == 0  # finding maxes: nothing to base a target on yet
            tracked = (lifting or plyo) and not baseline
            tm = f"=Maxes!{cycle_col}{pr_row}" if tracked and lifting else None
            if p.is_loaded:
                target = f'=IF(OR(G{hdr}="",F{hdr}=""),"",MROUND(G{hdr}*F{hdr}/100,{ROUNDING}))'
            elif lifting and reps and not baseline:  # test set: the weight you'd expect for that many reps
                div = "1" if reps == 1 else f"(1+{reps}/30)"
                target = f'=IF(G{hdr}="","",MROUND(G{hdr}/{div},{ROUNDING}))'
            elif plyo:  # start from your best before this cycle (box jump: one step if untested)
                step = self.jump_targets[("Box Jump", "Beginner")]
                if baseline:
                    target = f"={step}" if p.exercise == "Box Jump" else None
                else:
                    best = f"Maxes!{cycle_col}{pr_row}"
                    target = (f'=IF(N({best})>0,{best},{step})' if p.exercise == "Box Jump"
                              else f'=IF(N({best})>0,{best},"")')
            else:
                target = None
            scheme = f"{p.sets} x {p.reps}" if p.sets else p.reps
            values = {3: p.exercise, 4: scheme, 6: p.percent, 7: tm, 8: target, 15: p.note}
            for col in range(1, len(COLS) + 1):
                c = ws.cell(hdr, col, values.get(col))
                c.fill, c.border = EX_FILL, BOX
            ws.cell(hdr, 3).font = Font(bold=True, color="2E7D32" if plyo else PURPLE if p.kind != "accessory"
                                        else "333333")
            ws.cell(hdr, 7).number_format = "0"
            ws.cell(hdr, 8).font = Font(bold=True)
            ws.cell(hdr, 15).alignment = Alignment(wrap_text=False)
            row += 1
            for k in range(1, max(p.sets, 1) + 1):
                ws.cell(row, 3, f"      Set {k}")
                ws.cell(row, 5, reps if reps is not None else p.reps)
                ws.cell(row, 8, f'=IF(H{hdr}="","",H{hdr})').font = Font(color="888888")
                _input(ws.cell(row, 9), f'=IF(H{hdr}="","",H{hdr})')      # pre-filled, overwrite if different
                _input(ws.cell(row, 10), reps)                              # pre-filled target reps
                _input(ws.cell(row, 11))
                _input(ws.cell(row, 12))
                ws.cell(row, 12).alignment = Alignment(horizontal="center")
                done = f'L{row}<>""'
                if plyo:
                    ws.cell(row, 14, f'=IF(AND({done},N(I{row})>0),IF(I{row}>=PRs!D{pr_row},"PR!",""),"")')
                elif pr_row:
                    ws.cell(row, 13, f'=IF(AND({done},N(I{row})>0,N(J{row})>0),'
                                     f'IF(J{row}=1,I{row},ROUND(I{row}*(1+J{row}/30),1)),"")')
                    ws.cell(row, 14, f'=IF(M{row}="","",IF(M{row}>=PRs!C{pr_row},"PR!",""))')
                ws.cell(row, 14).font = PR_FONT
                _input(ws.cell(row, 15))
                rpe_dv.add(f"K{row}")
                done_dv.add(f"L{row}")
                self.sets_refs.append((ws.title, row, day_row, p.exercise))
                row += 1
        return row

    def sets_sheet(self):
        """Hidden list of every completed set on the month sheets, so PR formulas scan one range."""
        ws = self.wb.create_sheet("Sets")
        ws.append(["Date", "Exercise", "Weight", "Reps", "Est. 1RM"])
        for i, (sheet, r, day_row, exercise) in enumerate(self.sets_refs, start=2):
            q = f"'{sheet}'!"
            done = f'{q}L{r}<>""'
            ws.cell(i, 1, f"={q}B{day_row}")
            ws.cell(i, 2, exercise)
            ws.cell(i, 3, f'=IF(AND({done},N({q}I{r})>0),{q}I{r},"")')
            ws.cell(i, 4, f'=IF(C{i}="","",IF(N({q}J{r})>0,{q}J{r},1))')  # jumps count as 1 rep
            ws.cell(i, 5, _e1rm(f"C{i}", f"D{i}"))
        ws.sheet_state = "hidden"

    # -- Log -------------------------------------------------------------------------
    def log_sheet(self):
        ws = self.wb.create_sheet("Log")
        ws.sheet_properties.tabColor = GOLD
        _header(ws, 1, ["Date", "Exercise", "Weight / height", "Reps", "Est. 1RM", "Notes"])
        ws.freeze_panes = "A2"
        entries = list(self.data.get("log", []))
        for i in range(self.log_rows):
            r = 2 + i
            d, ex, w, reps, note = entries[i] if i < len(entries) else (None,) * 5
            for col, val in enumerate((d, ex, w, reps), start=1):
                _input(ws.cell(r, col), val)
            ws.cell(r, 1).number_format = "yyyy-mm-dd"
            ws.cell(r, 5, _e1rm(f"C{r}", f"D{r}")).border = BOX
            _input(ws.cell(r, 6), note or None)
        self.dv(ws, self.ex_list).add(f"B2:B{self.log_rows + 1}")
        _widths(ws, [12, 26, 14, 7, 10, 40])

    # -- PRs -------------------------------------------------------------------------
    def prs_sheet(self):
        ws = self.wb.create_sheet("PRs")
        ws.sheet_properties.tabColor = GOLD
        _header(ws, 1, ["Exercise", "Type", "Best est. 1RM", *[f"{n}RM" for n in REP_MAX_COUNTS]])
        ws.freeze_panes = "C2"
        for name, r in self.row_of.items():
            info = CATALOG[name]
            ws.cell(r, 1, name).font = Font(bold=info.category == "main")
            ws.cell(r, 2, info.category)
            if info.category != "plyo":
                c = ws.cell(r, 3, "=" + self._sources(("D", "E", "E"), f"$A{r}"))
                c.number_format, c.font = HIDE_ZERO, Font(bold=True)
            for j, n in enumerate(REP_MAX_COUNTS):
                if info.category == "plyo" and n > 1:
                    break
                ws.cell(r, 4 + j, "=" + self._rep_max(f"$A{r}", n)).number_format = HIDE_ZERO
        ws.cell(len(self.row_of) + 3, 1,
                "NRM = heaviest weight lifted for at least N reps (a 5-rep set also counts toward your 3RM). "
                "Plyos: the 1RM column is your best height / distance. Only sets marked Done count.")
        _widths(ws, [26, 10, 13] + [8] * len(REP_MAX_COUNTS))

    # -- Maxes -----------------------------------------------------------------------
    def maxes_sheet(self):
        ws = self.wb.create_sheet("Maxes")
        ws.sheet_properties.tabColor = GOLD
        labels = [f"Cycle {c}\n(weeks {(c - 1) * 12 + 1}-{c * 12})" for c in range(1, CYCLES + 1)]
        _header(ws, 1, ["Exercise", "Type", "Parent lift", "Ratio", *labels, "Transition\n(weeks 49-52)", "Source"])
        ws.row_dimensions[1].height = 32
        ws.freeze_panes = "E2"
        for name, r in self.row_of.items():
            info = CATALOG[name]
            ws.cell(r, 1, name).font = Font(bold=info.category == "main")
            ws.cell(r, 2, info.category)
            ws.cell(r, 3, info.parent)
            ws.cell(r, 4, info.ratio)
            if info.category not in ("main", "variation", "plyo"):
                continue
            plyo = info.category == "plyo"
            for k in range(1, CYCLES + 2):
                col = 4 + k
                cs = f"{START}+{(k - 1) * CYCLE_WEEKS * 7}"
                sets_end = self.cycle_first_set[k] + 1  # last Sets row logged before cycle k
                own = self._sources(("B", "C", "C") if plyo else ("D", "E", "E"), f"$A{r}", {
                    "log": f'Log!$A$2:$A${self.log_rows + 1},"<"&({cs})'}, sets_end=sets_end)
                if info.parent:
                    parent = f"{get_column_letter(col)}{self.row_of[info.parent]}"
                    formula = f'=IF({own}>0,ROUND({own},1),IF(N({parent})>0,ROUND({parent}*$D{r},1),""))'
                else:
                    formula = f'=IF({own}>0,ROUND({own},1),"")'
                ws.cell(r, col, formula).number_format = "0"
            if not plyo:
                ws.cell(r, 10, f'=IF(PRs!C{r}>0,"logged",IF($B{r}="variation","estimated",""))')
        # same-sheet condition only (cross-sheet references in conditional formats upset older Excel)
        ws.conditional_formatting.add(
            f"E2:I{1 + len(self.row_of)}",
            FormulaRule(formula=['$J2="estimated"'], font=Font(italic=True, color="888888")))
        ws.cell(len(self.row_of) + 3, 1,
                "Training max = best estimated 1RM logged before the cycle starts (plyos: best height / "
                "distance). Grey italics = estimated from the parent lift x ratio (no sets logged yet).")
        _widths(ws, [26, 10, 15, 7, 12, 12, 12, 12, 13, 10])

    # -- Body ------------------------------------------------------------------------
    def body_sheet(self):
        ws = self.wb.create_sheet("Body")
        ws.sheet_properties.tabColor = CRIMSON
        ws["A1"] = "BODYWEIGHT - weekly"
        ws["A1"].font = SECTION_FONT
        ws["A2"] = "Collected from each week's row on the month sheets."
        _header(ws, 3, ["Week", "Week of", "Bodyweight"])
        for week in range(0, WEEKS + 1):
            r = 4 + week
            _link(ws.cell(r, 1), week, month_sheet(month_of(week))).border = BOX
            c = ws.cell(r, 2, f"={START}+{(week - 1) * 7}")
            c.number_format, c.border = "yyyy-mm-dd", BOX
            ref = self.bw_refs[week]
            ws.cell(r, 3, f'=IF({ref}="","",{ref})').border = BOX

        ws["E1"] = "BODY FAT - monthly"
        ws["E1"].font = SECTION_FONT
        ws["E2"] = "Entered at the top of each month sheet. Same method, place and time of day every month."
        _header(ws, 3, ["Month", "Test around", "Date tested", "Body fat %", "Method", "Weight at test",
                        "Lean mass", "Fat mass"], first_col=5)
        for month in range(0, MONTHS + 1):
            r = 4 + month
            ws.cell(r, 6, f"={START}+{(max(month, 1) - 1) * 28}").number_format = "yyyy-mm-dd"
            if month == 0:  # from the intake
                ws.cell(r, 5, "Start")
                refs = {"pct": START_BF, "method": BF_METHOD, "weight": START_BW}
                ws.cell(r, 7, f"={START}").number_format = "yyyy-mm-dd"
            else:
                _link(ws.cell(r, 5), month, month_sheet(month))
                q = f"'{month_sheet(month)}'!"
                refs = {k: q + v for k, v in BF_CELLS.items()}
                ws.cell(r, 7, f'=IF({refs["date"]}="","",{refs["date"]})').number_format = "yyyy-mm-dd"
            ws.cell(r, 8, f'=IF({refs["pct"]}="","",{refs["pct"]})')
            ws.cell(r, 9, f'=IF({refs["method"]}="","",{refs["method"]})')
            ws.cell(r, 10, f'=IF({refs["weight"]}="","",{refs["weight"]})')
            ws.cell(r, 11, f'=IF(OR(H{r}="",J{r}=""),"",ROUND(J{r}*(1-H{r}/100),1))')
            ws.cell(r, 12, f'=IF(OR(H{r}="",J{r}=""),"",ROUND(J{r}*H{r}/100,1))')
            for col in range(5, 13):
                ws.cell(r, col).border = BOX
        headings = {"How to measure body fat once a month", "For every method"}
        for i, line in enumerate(BODYFAT_GUIDE.splitlines()):
            c = ws.cell(20 + i, 5, line)
            if line in headings or line.endswith(")"):
                c.font = Font(bold=True, color=PURPLE)
        _widths(ws, [7, 12, 12, 3, 7, 12, 12, 11, 22, 13, 11, 10])

    # -- Progress --------------------------------------------------------------------
    def progress_sheet(self):
        ws = self.wb.create_sheet("Progress")
        ws.sheet_properties.tabColor = CRIMSON
        ws["A1"] = "PROGRESS - strength vs bodyweight and body fat"
        ws["A1"].font = Font(bold=True, size=14, color=PURPLE)
        n = len(MAIN)
        _header(ws, 3, ["Checkpoint", "Week", *MAIN, "Bodyweight", "Body fat %"])
        points = [("Start", 1)] + [(f"After cycle {c}", c * CYCLE_WEEKS + 1) for c in range(1, CYCLES + 1)]
        last_bw, last_bf = 4 + WEEKS, 4 + MONTHS
        for i, (label, week) in enumerate(points):
            r = 4 + i
            ws.cell(r, 1, label).border = BOX
            ws.cell(r, 2, week).border = BOX
            for j, lift in enumerate(MAIN):
                ref = f"Maxes!{get_column_letter(5 + i)}{self.row_of[lift]}"
                c = ws.cell(r, 3 + j, f'=IF({ref}="",NA(),{ref})')
                c.number_format, c.border = "0", BOX
            bw = (f'=IFERROR(LOOKUP(2,1/((Body!$A$4:$A${last_bw}<=B{r})*(Body!$C$4:$C${last_bw}<>"")),'
                  f'Body!$C$4:$C${last_bw}),IF({START_BW}="",NA(),{START_BW}))')
            ws.cell(r, 3 + n, bw).border = BOX
            month = month_of(week)
            bf = (f'=IFERROR(LOOKUP(2,1/((ROW(Body!$H$4:$H${last_bf})-4<={month})*(Body!$H$4:$H${last_bf}<>"")),'
                  f'Body!$H$4:$H${last_bf}),NA())')
            ws.cell(r, 4 + n, bf).border = BOX
        ws.cell(10, 1, "Strength = training max at each checkpoint (best estimated 1RM so far). "
                       "#N/A just means no data yet.")

        strength = LineChart()
        strength.title = "Strength (est. 1RM) vs bodyweight"
        strength.y_axis.title = "Estimated 1RM"
        strength.add_data(Reference(ws, min_col=3, max_col=2 + n, min_row=3, max_row=8), titles_from_data=True)
        strength.set_categories(Reference(ws, min_col=1, min_row=4, max_row=8))
        body = LineChart()
        body.add_data(Reference(ws, min_col=3 + n, min_row=3, max_row=8), titles_from_data=True)
        body.y_axis.axId = 200
        body.y_axis.title = "Bodyweight"
        body.y_axis.crosses = "max"
        _show_axes(strength)
        _show_axes(body)
        strength += body
        strength.height, strength.width = 9, 18
        ws.add_chart(strength, "A12")

        body_ws = self.wb["Body"]
        bw = LineChart()
        bw.title = "Bodyweight (weekly)"
        bw.y_axis.title = "Bodyweight"
        bw.x_axis.title = "Week"
        bw.add_data(Reference(body_ws, min_col=3, min_row=3, max_row=last_bw), titles_from_data=True)
        bw.set_categories(Reference(body_ws, min_col=1, min_row=4, max_row=last_bw))
        _show_axes(bw)
        bw.height, bw.width = 9, 18
        ws.add_chart(bw, "L3")

        bf = LineChart()
        bf.title = "Body fat % and lean mass (monthly)"
        bf.y_axis.title = "Body fat %"
        bf.x_axis.title = "Month"
        bf.add_data(Reference(body_ws, min_col=8, min_row=3, max_row=last_bf), titles_from_data=True)
        bf.set_categories(Reference(body_ws, min_col=5, min_row=4, max_row=last_bf))
        lean = LineChart()
        lean.add_data(Reference(body_ws, min_col=11, min_row=3, max_row=last_bf), titles_from_data=True)
        lean.y_axis.axId = 300
        lean.y_axis.title = "Lean mass"
        lean.y_axis.crosses = "max"
        _show_axes(bf)
        _show_axes(lean)
        bf += lean
        bf.height, bf.width = 9, 18
        ws.add_chart(bf, "L22")
        _widths(ws, [16, 7] + [11] * n + [12, 11])


# Schema order of <font> children (CT_Font). openpyxl writes them in a different order,
# which Microsoft's validator reports; rewrite them so the file matches the schema exactly.
_FONT_ORDER = ("b", "i", "strike", "condense", "extend", "outline", "shadow", "u", "vertAlign", "sz",
               "color", "name", "family", "charset", "scheme")


def _order_font(match: re.Match) -> str:
    children = re.findall(r"<(\w+)\b[^>]*/>", match.group(1))
    elements = re.findall(r"<\w+\b[^>]*/>", match.group(1))
    ordered = sorted(zip(children, elements),
                     key=lambda ce: _FONT_ORDER.index(ce[0]) if ce[0] in _FONT_ORDER else len(_FONT_ORDER))
    return "<font>" + "".join(e for _, e in ordered) + "</font>"


def _fix_font_order(path: Path) -> None:
    tmp = Path(tempfile.mkstemp(suffix=".xlsx")[1])
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/styles.xml":
                data = re.sub(r"<font>(.*?)</font>", _order_font, data.decode("utf-8")).encode("utf-8")
            dst.writestr(item, data)
    shutil.move(tmp, path)


def build_workbook(path: str | Path, data: dict | None = None) -> Path:
    """Write the workbook to `path`.

    `data` optionally pre-fills it:
      intake keys: name, units, increment, start, height, bodyweight_start,
                   bodyfat_start, bodyfat_method, age, sex
      baseline:    [(exercise, weight, reps), ...]           -> Start Here
      log:         [(date, exercise, weight, reps, note)]    -> Log
      bodyweight:  {week: weight}                            -> month sheets (week rows)
      bodyfat:     {month: (date, percent, method, weight)}  -> month sheets (top)
    """
    book = _Book(data)
    book.start_sheet()
    book.month_sheets()  # must run before formulas that scan the Sets mirror
    book.log_sheet()
    book.prs_sheet()
    book.maxes_sheet()
    book.body_sheet()
    book.progress_sheet()
    book.sets_sheet()
    wb = book.wb
    wb.move_sheet("Lists", offset=len(wb.sheetnames))
    wb.active = 0
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    _fix_font_order(path)
    return path
