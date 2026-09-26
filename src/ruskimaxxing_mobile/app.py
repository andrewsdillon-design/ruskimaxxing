"""Phone app (Android / iPhone) built with BeeWare Toga.

Same program, tracking and workout logic as the desktop app (ruskimaxxing.*);
this file is only the touch-friendly UI. Five tabs:
  Workout   week/day picker, every set pre-filled - edit, tick Done, Save
  Progress  charts: main lifts vs bodyweight, jumps vs standards, body
  PRs       best e1RM and rep maxes for every movement, jump levels
  Body      weekly bodyweight, monthly body fat + how to test
  Setup     shoulder tip, intake, starting maxes, Prilepin's chart
"""

import asyncio
import os
import textwrap
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import toga
from toga.constants import Baseline
from toga.style import Pack

from ruskimaxxing import workout as wo
from ruskimaxxing.edition import app_name, is_supertotal
from ruskimaxxing.exercises import CATALOG, JUMP_STANDARDS, MAIN, jump_level, jump_targets
from ruskimaxxing.prilepin import ZONES
from ruskimaxxing.program import (MONTHS, SHOULDER_TIP, WEEKS, bodyfat_week, build_program, month_label, month_of,
                                  month_weeks,
                                  next_monday, week_label)
from ruskimaxxing.storage import Store
from ruskimaxxing import __version__
from ruskimaxxing.sync import Cloud, CloudError
from ruskimaxxing.updates import check_for_update, dismiss, dismissed
from ruskimaxxing.tracking import (BODYFAT_GUIDE, BODYFAT_METHODS, BodyFat, BodyWeight, LogEntry,
                                   best_e1rm, e1rm_history, rep_maxes)

PURPLE, PURPLE_DARK, GOLD, GOLD_LIGHT = "#4A1942", "#2E0C28", "#C9A227", "#F2D675"
CRIMSON, IVORY, PARCHMENT, INK, GREEN = "#8B1A1A", "#F6EFDE", "#EDE3CF", "#2B1B24", "#1F6F5C"
SERIES = ("#4A1942", "#8B1A1A", "#B8860B", "#1F6F5C", "#7B4FA0", "#5A5A5A")
ASSETS = Path(__file__).resolve().parent.parent / "ruskimaxxing" / "assets"
RPE_CHOICES = ["", "6", "6.5", "7", "7.5", "8", "8.5", "9", "9.5", "10"]


def col(*children, **style):
    return toga.Box(children=list(children), style=Pack(direction="column", **style))


def row(*children, **style):
    return toga.Box(children=list(children), style=Pack(direction="row", align_items="center", **style))


def wrap(text: str, size: int = 12) -> str:
    """Hard-wrap text for a phone-width column (Toga labels don't wrap on every platform)."""
    width = int(46 * 11 / max(size, 8))
    return "\n".join(textwrap.fill(line, width) if line.strip() else line for line in text.splitlines())


def label(text, size=12, bold=False, color=INK, **style):
    return toga.Label(wrap(text, size + 3 if bold else size), style=Pack(font_size=size, font_weight="bold" if bold else "normal",
                                                   color=color, **style))


def button(text, handler, **style):
    return toga.Button(text, on_press=handler,
                       style=Pack(background_color=PURPLE, color=GOLD_LIGHT, font_weight="bold", **style))


def section(title):
    return label(title, 15, True, PURPLE, margin_top=12)


def number_input(value="", step="1", width=80):
    v = wo.number(value)
    return toga.NumberInput(value=Decimal(str(v)) if v else None, step=Decimal(step), min=0,
                            style=Pack(width=width))


def text_of(number_widget) -> str:
    v = number_widget.value
    return "" if v is None else f"{float(v):g}"


class Chart:
    """Line chart on a toga Canvas: series on left / right axes, x = dates."""

    def __init__(self, height=230):
        self.canvas = toga.Canvas(style=Pack(height=height, flex=1, margin_top=8), on_resize=self._resized)
        self.title, self.series, self.hlines, self.size = "", [], [], (0, 0)

    def plot(self, title, series, hlines=()):
        self.title, self.series, self.hlines = title, [s for s in series if s[1]], list(hlines)
        self.draw()

    def _resized(self, canvas, width, height, **kw):
        self.size = (width, height)
        self.draw()

    def draw(self):
        c = self.canvas
        w, h = self.size
        c.root_state.drawing_actions.clear()
        if w < 60 or h < 60:
            c.redraw()
            return
        left, top, right, bottom = 38, 24, 38, 30
        c.fill_style = IVORY
        c.begin_path()
        c.rect(0, 0, w, h)
        c.fill()
        c.fill_style = PURPLE
        c.fill_text(self.title, 6, 4, font=toga.Font("sans-serif", 11, weight="bold"), baseline=Baseline.TOP)
        if not self.series:
            c.fill_style = "#888888"
            c.fill_text("No data yet", w / 2 - 30, h / 2)
            c.redraw()
            return
        xs = [d.toordinal() for s in self.series for d, _ in s[1]]
        x0, x1 = min(xs), max(xs)
        if x0 == x1:
            x0, x1 = x0 - 3, x1 + 3

        def px(x):
            return left + (x - x0) / (x1 - x0) * (w - left - right)

        c.stroke_style, c.line_width = GOLD, 1
        c.begin_path()
        c.rect(left, top, w - left - right, h - top - bottom)
        c.stroke()
        small = toga.Font("sans-serif", 8)
        for side in ("left", "right"):
            vals = [v for s in self.series if s[3] == side for _, v in s[1]]
            if side == "left":
                vals += [v for _, v in self.hlines]
            if not vals:
                continue
            lo, hi = min(vals), max(vals)
            span = (hi - lo) or max(1.0, abs(hi) * 0.1)
            lo, hi = lo - span * 0.1, hi + span * 0.1

            def py(y, lo=lo, hi=hi):
                return h - bottom - (y - lo) / (hi - lo) * (h - top - bottom)

            c.fill_style = "#555555"
            for i in range(3):
                v = lo + (hi - lo) * i / 2
                c.fill_text(f"{v:.0f}", 2 if side == "left" else w - right + 3, py(v), font=small,
                            baseline=Baseline.MIDDLE)
            if side == "left":
                for text, v in self.hlines:
                    c.stroke_style, c.line_width = "#BBBBBB", 1
                    c.begin_path()
                    c.move_to(left, py(v))
                    c.line_to(w - right, py(v))
                    c.stroke()
                    c.fill_style = "#999999"
                    c.fill_text(text, w - right - 70, py(v) - 9, font=small, baseline=Baseline.TOP)
            for _, points, color, s_side in self.series:
                if s_side != side:
                    continue
                c.stroke_style, c.line_width = color, 2
                c.begin_path()
                for k, (d, v) in enumerate(points):
                    (c.move_to if k == 0 else c.line_to)(px(d.toordinal()), py(v))
                c.stroke()
        c.fill_style = "#555555"
        lx = left
        for text, _, color, side in self.series:
            c.fill_style = color
            c.fill_text(text + (" (R)" if side == "right" else ""), lx, h - 14, font=small, baseline=Baseline.TOP)
            lx += 8 + 6 * len(text)
        c.redraw()


class RuskiMaxxing(toga.App):
    def startup(self):
        # RUSKIMAXXING_DATA_DIR lets tests and screenshots use a scratch database
        data_dir = Path(os.environ.get("RUSKIMAXXING_DATA_DIR") or self.paths.data)
        data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(data_dir / "data.db")
        self.cloud = Cloud(self.store)
        self.sessions = build_program()
        self.dirty = False
        self.blocks = []
        self.week, self.day = self._current_week(), 0

        # phone-width header: short title; the edition goes on the subtitle line
        subtitle = ("SUPERTOTAL \u2022 " if is_supertotal() else "") + "STRENGTH \u2022 MASS \u2022 POWER"
        header = row(style_logo(), col(label("RUSKIMAXXING", 18, True, GOLD),
                                       label(subtitle, 9, True, GOLD_LIGHT)),
                     toga.Box(style=Pack(flex=1)), background_color=PURPLE_DARK, gap=8)
        self.tabs = toga.OptionContainer(
            content=[("Workout", self._workout_tab()), ("Progress", self._progress_tab()),
                     ("PRs", self._prs_tab()), ("Body", self._body_tab()), ("Setup", self._setup_tab())],
            on_select=self._tab_changed, style=Pack(flex=1))
        self.update_row = col()   # filled in when a newer version is out
        self.main_window = toga.MainWindow(title=app_name())
        self.main_window.content = col(header, self.update_row, self.tabs, background_color=PARCHMENT, flex=1)
        self.refresh_all()
        self.main_window.show()
        if self.cloud.pending_code:     # the app was closed while signing in: keep waiting
            self._watch_sign_in()
        if toga.platform.current_platform == "android" and not os.environ.get("RUSKIMAXXING_NO_UPDATE_CHECK"):
            asyncio.get_event_loop().create_task(self._check_updates(force=False))

    # ----- helpers ----------------------------------------------------------------
    def cfg(self) -> wo.Settings:
        return wo.Settings.from_store(self.store)

    def _current_week(self) -> int:
        start = self.cfg().start
        return max(0, min(WEEKS, (date.today() - start).days // 7 + 1))

    async def info(self, title, message):
        await self.main_window.dialog(toga.InfoDialog(title, message))

    def _tab_changed(self, widget, **kw):
        self.autosave()
        self.refresh_all(rebuild_workout=False)

    def refresh_all(self, rebuild_workout=True):
        if rebuild_workout:
            self.render_workout()
        self.refresh_progress()
        self.refresh_prs()
        self.refresh_body()
        self.refresh_setup()

    # ----- Workout ----------------------------------------------------------------
    def _workout_tab(self):
        self.week_label = label("", 12, True, PURPLE, flex=1, text_align="center")
        self.month_items = [month_label(m) for m in range(0, MONTHS + 1)]
        self.month_select = toga.Selection(items=self.month_items,
                                           on_change=self._month_changed, style=Pack(flex=1))
        self.week_select = toga.Selection(on_change=self._week_changed, style=Pack(flex=1))
        self.day_select = toga.Selection(on_change=self._day_changed, style=Pack(flex=1))
        self.bf_due = label("", 11, True, CRIMSON)
        self.status = label("", 10, color="#666666")
        self.bw_input = number_input(step="0.1", width=90)
        self.wo_scroll = toga.ScrollContainer(horizontal=False, content=toga.Box(), style=Pack(flex=1))
        return col(
            row(self.week_label, button("This week", self._this_week, width=100), gap=6),
            row(label("Month", 11, True, width=56), self.month_select, gap=6, margin_top=6),
            row(label("Week", 11, True, width=56), self.week_select, gap=6, margin_top=4),
            row(label("Day", 11, True, width=56), self.day_select, gap=6, margin_top=4),
            row(label("Bodyweight this week", 11), self.bw_input, button("Save", self._save_bw), gap=6,
                margin_top=6),
            self.bf_due,
            row(button("Save workout", self._save_workout, flex=1),
                button("All done", self._all_done, flex=1), gap=6, margin_top=6),
            self.status,
            self.wo_scroll, margin=8, gap=2, flex=1)

    def _go(self, week):
        self.autosave()
        self.week = min(WEEKS, max(0, week))
        self.render_workout()

    def _this_week(self, widget=None):
        self._go(self._current_week())

    def _month_changed(self, widget, **kw):
        if getattr(self, "_filling_days", False) or widget.value is None:
            return
        month = self.month_items.index(widget.value)
        if month_of(self.week) != month:
            self._go(month_weeks(month)[0])

    def _week_changed(self, widget, **kw):
        if getattr(self, "_filling_days", False) or widget.value is None:
            return
        week = month_weeks(month_of(self.week))[self.week_items.index(widget.value)]
        if week != self.week:
            self._go(week)

    def _day_changed(self, widget, **kw):
        if getattr(self, "_filling_days", False) or widget.value is None:
            return
        self.autosave()
        self.day = self.day_items.index(widget.value)
        self.render_workout(fill_days=False)

    def _mark_dirty(self, *args, **kw):
        if not getattr(self, "_building", False):
            self.dirty = True
            self.status.text = "Unsaved changes - tap Save workout"

    def render_workout(self, blocks=None, fill_days=True):
        cfg = self.cfg()
        month = month_of(self.week)
        self.week_label.text = ("Baseline test - Week 0" if self.week == 0 else
                                f"Month {month} of {MONTHS}  -  Week {self.week} of {WEEKS}")
        bw = {b.week: b.weight for b in self.store.bodyweights()}
        self.bw_input.value = Decimal(str(bw[self.week])) if self.week in bw else None
        bf_month = next((m for m in range(1, MONTHS + 1) if bodyfat_week(m) == self.week), None)
        self.bf_due.text = f"Body fat test due (month {bf_month}) - Body tab" if bf_month else ""
        if fill_days:
            self._filling_days = True
            self.month_select.value = self.month_items[month]
            weeks = month_weeks(month)
            self.week_items = [f"{short_week(w)} - {wo.session(w, 0).date(cfg.start):%b %d}" for w in weeks]
            self.week_select.items = self.week_items
            self.week_select.value = self.week_items[weeks.index(self.week)]
            items = []
            for i in range(3):
                s = wo.session(self.week, i)
                done, planned = wo.day_progress(self.store, self.week, i)
                items.append(f"{s.day} - {s.date(cfg.start):%a %b %d} - {done}/{planned}"
                             + (" ✓" if done >= planned else ""))
            self.day_items = items
            self.day_select.items = items
            self.day_select.value = items[self.day]
            self._filling_days = False
        self.blocks = blocks if blocks is not None else wo.workout_model(self.store, self.week, self.day, cfg)
        self._building = True
        content = col(gap=2, margin_bottom=40)
        for bi, b in enumerate(self.blocks):
            p = b["p"]
            info = CATALOG.get(p.exercise)
            plyo = bool(info and info.category == "plyo")
            color = GREEN if plyo else PURPLE if p.kind != "accessory" else INK
            scheme = f"{p.sets} x {p.reps}" if p.sets else p.reps
            if p.percent:
                scheme += f" @ {p.percent:g}%"
            content.add(label(p.exercise, 14, True, color, margin_top=10))
            content.add(label(f"{scheme}  -  {b['source']}", 10, color="#444444"))
            if p.note:
                content.add(label(p.note, 9, color="#777777"))
            unit = cfg.height_unit if plyo else cfg.unit
            content.add(row(label("Set", 9, True, width=28), label(unit, 9, True, width=86),
                            label("Reps", 9, True, width=66), label("RPE", 9, True, width=66),
                            label("Done", 9, True), gap=4))
            b["widgets"] = []
            for k, r in enumerate(b["rows"], start=1):
                wt = number_input(r["weight"], "0.5", 86)
                rp = number_input(r["reps"], "1", 66)
                rpe = toga.Selection(items=RPE_CHOICES, value=r["rpe"] if r["rpe"] in RPE_CHOICES else "",
                                     style=Pack(width=66))
                done = toga.Switch("", value=r["done"])
                for widget in (wt, rp, rpe, done):
                    widget.on_change = self._mark_dirty
                b["widgets"].append({"weight": wt, "reps": rp, "rpe": rpe, "done": done, "target": r["target"]})
                content.add(row(label(str(k), 11, width=28), wt, rp, rpe, done, gap=4))
            note = toga.TextInput(value=b.get("note", ""), placeholder="Notes", on_change=self._mark_dirty,
                                  style=Pack(flex=1))
            b["note_widget"] = note
            content.add(row(note, button("+ set", lambda w, bi=bi: self._add_set(bi), width=70), gap=6))
            content.add(toga.Divider(style=Pack(margin_top=6)))
        self.wo_scroll.content = content
        self._building = False
        self.dirty = False

    def _collect(self):
        out = []
        for b in self.blocks:
            rows = [{"target": w["target"], "weight": text_of(w["weight"]), "reps": text_of(w["reps"]),
                     "rpe": w["rpe"].value or "", "done": bool(w["done"].value)} for w in b.get("widgets", [])]
            out.append({"p": b["p"], "rows": rows, "source": b["source"], "planned": b["planned"],
                        "note": b["note_widget"].value if "note_widget" in b else b.get("note", "")})
        return out

    def _add_set(self, bi):
        blocks = self._collect()
        wo.add_set(blocks, bi)
        self.render_workout(blocks, fill_days=False)
        self._mark_dirty()

    def _all_done(self, widget):
        blocks = self._collect()
        wo.mark_all_done(blocks)
        self.render_workout(blocks, fill_days=False)
        self._mark_dirty()

    def autosave(self):
        """Never lose edits when moving to another day, week or tab."""
        if self.dirty and self.blocks:
            wo.save_workout(self.store, self.week, self.day, self._collect(), self.cfg())
            self.dirty = False

    async def _save_workout(self, widget):
        saved, prs, bad = wo.save_workout(self.store, self.week, self.day, self._collect(), self.cfg())
        done = sum(e.done for e in saved)
        self.render_workout()
        self.status.text = f"Saved: {done} set{'s' * (done != 1)} done"
        self.refresh_all(rebuild_workout=False)
        if bad:
            await self.info("Check reps", "Ticked Done but no reps - saved as not done:\n" + "\n".join(bad))
        if prs:
            await self.info("New PR!", "\n".join(prs))
        if self.cloud.logged_in:  # quiet background backup; errors just wait for the next save
            try:
                await asyncio.get_running_loop().run_in_executor(None, self.cloud.sync)
                self.cloud_status.text = wrap(self.cloud.status(), 10)
            except CloudError:
                pass

    def _save_bw(self, widget):
        weight = wo.number(text_of(self.bw_input))
        if weight:
            self.store.set_bodyweight(BodyWeight(self.week, self.cfg().start + timedelta(weeks=self.week - 1),
                                                 weight))
        else:
            self.store.delete_bodyweight(self.week)
        self.status.text = "Bodyweight saved"
        self.refresh_body()
        self.refresh_progress()

    # ----- Progress ---------------------------------------------------------------
    def _progress_tab(self):
        self.lift_chart, self.plyo_chart, self.body_chart = Chart(), Chart(), Chart()
        return toga.ScrollContainer(horizontal=False, content=col(
            self.lift_chart.canvas, self.plyo_chart.canvas, self.body_chart.canvas, margin=8))

    def refresh_progress(self):
        entries = self.store.lifts()
        cfg = self.cfg()
        bw = [(b.date, b.weight) for b in self.store.bodyweights()]
        lifts = [(lift, e1rm_history(entries, lift), SERIES[i % len(SERIES)], "left") for i, lift in enumerate(MAIN)]
        self.lift_chart.plot(f"Main lifts (est. 1RM, {cfg.unit}) vs bodyweight", lifts + [("BW", bw, "#555555", "right")])
        done = [e for e in entries if e.done and e.weight > 0]

        def best_by_day(name):
            days = {}
            for e in done:
                if e.exercise == name:
                    days[e.date] = max(days.get(e.date, 0), e.weight)
            return sorted(days.items())

        jumps = [(short, best_by_day(name), color, side) for short, name, color, side in (
            ("Box", "Box Jump", SERIES[2], "left"), ("Vertical", "Vertical Jump", SERIES[3], "left"),
            ("Broad", "Broad Jump", SERIES[1], "right"))]
        standards = [(f"{lvl} {t:g}", t) for lvl, _, t in jump_targets("Box Jump", cfg.height, cfg.height_unit)
                     if t is not None]
        self.plyo_chart.plot(f"Jumps ({cfg.height_unit}) - box standards dotted", jumps, standards)
        fats = sorted(self.store.bodyfats(), key=lambda f: f.date)
        self.body_chart.plot("Bodyweight and body fat %", [("BW", bw, SERIES[1], "left"),
                                                            ("BF %", [(f.date, f.percent) for f in fats], SERIES[3],
                                                             "right")])

    # ----- PRs --------------------------------------------------------------------
    def _prs_tab(self):
        self.prs_box = col(margin=8, gap=2)
        return toga.ScrollContainer(horizontal=False, content=self.prs_box)

    def refresh_prs(self):
        entries = self.store.lifts()
        cfg = self.cfg()
        box = self.prs_box
        box.clear()
        box.add(section("PR board"))
        total = 0.0
        logged = {e.exercise for e in entries if e.done}
        for name in [n for n in CATALOG if n in logged or n in MAIN]:
            info = CATALOG[name]
            if info.category == "plyo":
                continue
            best, rms = best_e1rm(entries, name), rep_maxes(entries, name)
            if name in MAIN and best:
                total += best.e1rm
            reps = "  ".join(f"{n}RM {rms[n].weight:g}" for n in (1, 3, 5, 10) if n in rms) or "no sets yet"
            box.add(label(name, 12, True, PURPLE if info.category == "main" else INK, margin_top=4))
            box.add(label((f"e1RM {best.e1rm:.0f}   " if best else "") + reps, 10))
        box.add(label(f"Total (e1RM): {total:.0f} {cfg.unit}" if total else "Total: -", 12, True, CRIMSON,
                      margin_top=6))
        box.add(section("Jump standards"))
        for jump in JUMP_STANDARDS:
            best = max((e.weight for e in entries if e.exercise == jump and e.done), default=None)
            targets = ",  ".join(f"{lvl} {t:g}" if t is not None else f"{lvl} (enter height)"
                                 for lvl, _, t in jump_targets(jump, cfg.height, cfg.height_unit))
            box.add(label(f"{jump}: {jump_level(jump, best, cfg.height, cfg.height_unit)}"
                          + (f" (best {best:g} {cfg.height_unit})" if best else ""), 12, True, CRIMSON, margin_top=4))
            box.add(label(targets, 10))
        others = sorted(n for n in logged if CATALOG.get(n) and CATALOG[n].category == "plyo"
                        and n not in JUMP_STANDARDS)
        for n in others:
            best = max(e.weight for e in entries if e.exercise == n and e.done)
            box.add(label(f"{n}: best {best:g} {cfg.height_unit}", 11))

    # ----- Body -------------------------------------------------------------------
    def _body_tab(self):
        self.body_box = col(margin=8, gap=4)
        self.bf_month = toga.Selection(items=[str(m) for m in range(1, MONTHS + 1)], style=Pack(width=70))
        self.bf_date = toga.TextInput(value=date.today().isoformat(), style=Pack(width=120))
        self.bf_pct = number_input(step="0.1", width=80)
        self.bf_method = toga.Selection(items=list(BODYFAT_METHODS), style=Pack(flex=1))
        self.bf_weight = number_input(step="0.1", width=90)
        self.bw_list = col(gap=1)
        self.bf_list = col(gap=1)
        self.body_box.add(
            section("Body fat - once a month"),
            row(label("Month", 11), self.bf_month, label("Date", 11), self.bf_date, gap=6),
            row(label("Body fat %", 11), self.bf_pct, label("Weight", 11), self.bf_weight, gap=6),
            row(label("Method", 11), self.bf_method, gap=6),
            row(button("Save body fat", self._save_bf, flex=1)),
            self.bf_list,
            section("Bodyweight - weekly"),
            label("Enter it on the Workout tab each week.", 10),
            self.bw_list,
            section("How to measure body fat"),
            label(BODYFAT_GUIDE, 10))
        return toga.ScrollContainer(horizontal=False, content=self.body_box)

    async def _save_bf(self, widget):
        pct, day = wo.number(text_of(self.bf_pct)), None
        try:
            day = date.fromisoformat(self.bf_date.value.strip())
        except ValueError:
            pass
        if not pct or not day:
            await self.info("Body fat", "Enter the date (YYYY-MM-DD) and body fat %")
            return
        self.store.set_bodyfat(BodyFat(int(self.bf_month.value), day, pct, self.bf_method.value,
                                       wo.number(text_of(self.bf_weight))))
        self.bf_pct.value = None
        self.refresh_body()
        self.refresh_progress()

    def refresh_body(self):
        cfg = self.cfg()
        self.bw_list.clear()
        for b in sorted(self.store.bodyweights(), key=lambda b: -b.week)[:12]:
            self.bw_list.add(label(f"Week {b.week}  ({b.date:%b %d}):  {b.weight:g} {cfg.unit}", 11))
        self.bf_list.clear()
        fats = {f.month: f for f in self.store.bodyfats()}
        for m in range(1, MONTHS + 1):
            due = cfg.start + timedelta(weeks=bodyfat_week(m) - 1)
            f = fats.get(m)
            text = (f"M{m}: {f.percent:g}%  {f.date:%b %d}  {f.method}"
                    + (f"  lean {f.lean_mass:g}" if f.lean_mass else "")) if f else f"M{m}: due {due:%b %d}"
            self.bf_list.add(label(text, 11, bold=bool(f)))

    # ----- Setup ------------------------------------------------------------------
    def _setup_tab(self):
        s = self.store
        self.units = toga.Selection(items=["lb", "kg"], value=s.get("units", "lb"), style=Pack(width=80))
        self.increment = number_input(s.get("increment", "5"), "0.5", 80)
        self.start = toga.TextInput(value=s.get("start", "") or next_monday().isoformat(), style=Pack(width=120))
        self.height = number_input(s.get("height", ""), "0.5", 80)
        self.bw_start = number_input(s.get("bodyweight_start", ""), "0.1", 90)
        self.bf_start = number_input(s.get("bodyfat_start", ""), "0.1", 80)
        self.method = toga.Selection(items=list(BODYFAT_METHODS), style=Pack(flex=1))
        if s.get("bodyfat_method", "") in BODYFAT_METHODS:
            self.method.value = s.get("bodyfat_method")
        self.base_ex = toga.Selection(items=list(CATALOG), style=Pack(flex=1))
        self.base_w = number_input(step="0.5", width=86)
        self.base_r = number_input("1", "1", 60)
        self.base_list = col(gap=2)
        prilepin = col(gap=1)
        for text, z in zip(("Under 70%", "70-80%", "80-90%", "90%+"), ZONES):
            prilepin.add(label(f"{text}:  {z.reps_per_set[0]}-{z.reps_per_set[1]} reps/set,  "
                               f"{z.optimal_total} optimal ({z.total_range[0]}-{z.total_range[1]})", 11))
        self.cloud_status = label(Cloud(s).status(), 10, color="#6b5a45")
        self.cloud_box = col(gap=4)
        self.update_status = label(f"Version {__version__}", 10, color="#6b5a45", flex=1)
        tip = toga.Label(wrap(SHOULDER_TIP, 10), style=Pack(font_size=10, font_weight="bold", color=IVORY,
                                                            background_color=CRIMSON, margin=6))
        return toga.ScrollContainer(horizontal=False, content=col(
            tip,
            section("1. Intake"),
            row(label("Units", 11, width=110), self.units, gap=6),
            row(label("Round to", 11, width=110), self.increment, gap=6),
            row(label("Start (Monday)", 11, width=110), self.start, gap=6),
            row(label("Height", 11, True, PURPLE, width=110), self.height, gap=6),
            row(label("Bodyweight", 11, True, PURPLE, width=110), self.bw_start, gap=6),
            row(label("Body fat %", 11, width=110), self.bf_start, gap=6),
            row(label("BF method", 11, width=110), self.method, gap=6),
            row(button("Save intake", self._save_intake, flex=1)),
            section("2. Starting maxes"),
            label("Enter what you know (any movement, weight and reps) - or run Week 0 to test.", 10),
            row(self.base_ex, gap=6),
            row(label("Weight", 11), self.base_w, label("Reps", 11), self.base_r, gap=6),
            row(button("Add starting max", self._add_base, flex=1)),
            self.base_list,
            section("3. Cloud backup (optional)"),
            label("Back up to the cloud so you can log in on a new phone and get everything back.", 10),
            self.cloud_status,
            self.cloud_box,
            section("App updates"),
            row(self.update_status, button("Check for updates", self._check_updates_now, width=150), gap=6),
            section("Prilepin's chart"),
            prilepin,
            margin=8, gap=4))

    async def _save_intake(self, widget):
        try:
            date.fromisoformat(self.start.value.strip())
        except ValueError:
            await self.info("Start date", "Use the format YYYY-MM-DD (a Monday)")
            return
        s = self.store
        s.set("units", self.units.value)
        s.set("increment", text_of(self.increment) or "5")
        s.set("start", self.start.value.strip())
        s.set("height", text_of(self.height))
        s.set("bodyweight_start", text_of(self.bw_start))
        s.set("bodyfat_start", text_of(self.bf_start))
        s.set("bodyfat_method", self.method.value or "")
        bw = wo.number(text_of(self.bw_start))
        if bw and not any(b.week == 0 for b in s.bodyweights()):
            s.set_bodyweight(BodyWeight(0, self.cfg().start - timedelta(weeks=1), bw))
        self.week = self._current_week()
        self.refresh_all()
        await self.info("Saved", "Intake saved.")

    def _add_base(self, widget):
        weight, reps = wo.number(text_of(self.base_w)), wo.number(text_of(self.base_r))
        if not weight or not reps:
            return
        self.store.add_lift(LogEntry(self.cfg().start - timedelta(weeks=1), self.base_ex.value, weight, int(reps),
                                     "baseline", "starting max"))
        self.base_w.value = None
        self.refresh_all()

    def _delete_base(self, entry_id):
        self.store.delete_lift(entry_id)
        self.refresh_all()

    async def _cloud(self, work, done=None):
        """Run a network call in the background, then report."""
        self.cloud_status.text = "Working..."
        try:
            result = await asyncio.get_running_loop().run_in_executor(None, work)
        except CloudError as e:
            self.refresh_cloud()
            if e.code == 402:  # signed in, backups just aren't active for this account
                self.refresh_all()
                await self.info("Cloud backup", str(e))
            else:
                await self.main_window.dialog(toga.ErrorDialog("Cloud backup", str(e)))
            return
        self.refresh_all()
        message = done(result) if callable(done) else done
        if message:
            await self.info("Cloud backup", message)

    # ----- updates --------------------------------------------------------------------
    async def _check_updates_now(self, widget):
        await self._check_updates(force=True)

    async def _check_updates(self, force):
        platform = "android" if toga.platform.current_platform == "android" else "ios"
        if force:
            self.update_status.text = "Checking..."
        update = await asyncio.get_running_loop().run_in_executor(
            None, lambda: check_for_update(self.store, platform, force=force))
        self.show_update(update, asked=force)

    def show_update(self, update, asked=False):
        self.update_row.clear()
        if not update:
            self.update_status.text = f"Version {__version__}" + (" - the latest" if asked else "")
            return
        self.update_status.text = f"Version {__version__} - {update.version} is out"
        if dismissed(self.store, update) and not asked:
            return

        def later(widget):
            dismiss(self.store, update)
            self.update_row.clear()
        self.update_row.add(row(label(f"Update: version {update.version}", 11, True, PURPLE_DARK, flex=1),
                                button("Download", lambda w: open_url(update.url), width=100),
                                button("Later", later, width=70),
                                background_color=GOLD, margin=4, gap=6))

    def refresh_cloud(self):
        """Cloud section: one big Sign in button, or the waiting state, or the signed-in actions."""
        self.cloud_status.text = wrap(self.cloud.status(), 10)
        self.cloud_box.clear()
        if self.cloud.logged_in:
            self.cloud_box.add(row(button("Back up now", self._cloud_sync, flex=1),
                                   button("Log out", self._cloud_logout, flex=1), gap=6))
            self.cloud_box.add(row(button("Delete account (website)", self._cloud_delete, flex=1)))
        elif self.cloud.pending_code:
            self.cloud_box.add(label(f"Code: {self.cloud.pending_code}", 16, True, PURPLE))
            self.cloud_box.add(label("Sign in or create your account in the browser page that opened, then come "
                                     "back here. This finishes by itself.", 10))
            # in case the browser didn't open: the link can be copied from here
            self.cloud_box.add(toga.TextInput(value=self.store.get("cloud_link_url", ""), readonly=True,
                                              style=Pack(flex=1)))
            self.cloud_box.add(row(button("Open sign-in page again", self._cloud_reopen, flex=1),
                                   button("Cancel", self._cloud_cancel, width=90), gap=6))
        else:
            self.cloud_box.add(row(button("Sign up or log in on the website", self._cloud_sign_in, flex=1)))
            self.cloud_box.add(label("Accounts are free. Your browser opens ruskimaxxing.com, then you come back here.", 10,
                                     color="#6b5a45"))

    async def _cloud_sign_in(self, widget):
        self.cloud_status.text = "Opening your browser..."
        try:
            link = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.cloud.start_browser_sign_in(phone=True))
        except CloudError as e:
            self.refresh_cloud()
            await self.main_window.dialog(toga.ErrorDialog("Cloud backup", str(e)))
            return
        self.refresh_cloud()
        open_url(link["url"])
        self._watch_sign_in()

    def _cloud_reopen(self, widget):
        open_url(self.store.get("cloud_link_url", ""))

    def _cloud_cancel(self, widget):
        self.cloud.cancel_sign_in()
        self.refresh_cloud()

    def _watch_sign_in(self):
        if not getattr(self, "_watching", False):
            self._watching = True
            asyncio.get_event_loop().create_task(self._poll_sign_in())

    async def _poll_sign_in(self):
        """Check every 2 seconds until the person finishes on the website (or the link expires)."""
        loop = asyncio.get_running_loop()
        try:
            while self.cloud.pending_code:
                await asyncio.sleep(2)
                try:
                    done = await loop.run_in_executor(None, self.cloud.poll_sign_in)
                except CloudError as e:
                    if self.cloud.pending_code:
                        continue            # no signal for a moment: keep waiting
                    self.refresh_cloud()
                    await self.info("Cloud backup", str(e))
                    return
                if done:
                    self.refresh_cloud()
                    await self._cloud(self.cloud.sync, lambda r: f"Signed in as {self.cloud.email}. Restored "
                                                                 f"{r[1]} records, backed up {r[0]}.")
                    return
        finally:
            self._watching = False
            self.refresh_cloud()

    async def _cloud_sync(self, widget):
        self.autosave()
        await self._cloud(self.cloud.sync, lambda r: f"Backed up {r[0]}, received {r[1]} records.")

    async def _cloud_logout(self, widget):
        await self._cloud(self.cloud.logout, "Logged out. Your data stays on this phone.")

    def _cloud_delete(self, widget):
        open_url(self.cloud.account_page("/account/delete"))

    def refresh_setup(self):
        self.refresh_cloud()
        self.base_list.clear()
        for e in (e for e in self.store.lifts() if e.kind == "baseline"):
            self.base_list.add(row(label(f"{e.exercise}: {e.weight:g} x {e.reps}  (e1RM {e.e1rm:.0f})", 11, flex=1),
                                   button("X", lambda w, i=e.id: self._delete_base(i), width=40), gap=6))


def open_url(url: str) -> None:
    """Open a web page in the phone's browser (Android / iOS), or the default browser on a computer."""
    if not url:
        return
    platform = toga.platform.current_platform
    try:
        if platform == "android":
            from java import jclass
            Intent, Uri = jclass("android.content.Intent"), jclass("android.net.Uri")
            activity = jclass("org.beeware.android.MainActivity").singletonThis
            activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            return
        if platform == "iOS":
            from rubicon.objc import ObjCClass
            app = ObjCClass("UIApplication").sharedApplication
            app.openURL(ObjCClass("NSURL").URLWithString(url), options=ObjCClass("NSDictionary").dictionary(),
                        completionHandler=None)
            return
    except Exception:  # fall back to the standard library
        pass
    import webbrowser
    webbrowser.open(url)


def short_week(week: int) -> str:
    """'Wk 13 - C2 - Accumulation': fits a phone header."""
    return (week_label(week).replace("Week ", "Wk ").replace("Cycle ", "C")
            .replace("Baseline test (optional)", "Baseline test"))


def style_logo():
    try:
        return toga.ImageView(toga.Image(ASSETS / "logo_96.png"), style=Pack(width=56, height=56, margin=4))
    except Exception:  # missing asset should never stop the app
        return toga.Box(style=Pack(width=4))


def main():
    # must match pyproject's [tool.briefcase] bundle + app name, per edition, so both can be installed
    bundle = "io.github.andrewsdillondesign" + (".supertotal" if is_supertotal() else "")
    return RuskiMaxxing(app_name(), f"{bundle}.ruskimaxxing_mobile")
