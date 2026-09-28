# How Years 2 and 3 are built

Year 1 is a fixed beginner template - everyone gets the same 52 weeks. Years
2 and 3 aren't: they're built from *your* logged Year-1 (or Year-2) training,
so this page explains exactly what data goes in, what rules turn it into a
program, and where those rules come from. Nothing here is a black box.

## 1. What we read from your log

Every set you've logged - weight, reps, RPE, which week/day it was, whether
you marked it done - feeds a `LifterProfile` (`analysis.py`):

- **Training max per lift** - your best estimated 1RM (Epley formula:
  `weight x (1 + reps/30)`) logged before "now", same rule Year 1 already
  uses to set cycle percentages.
- **Year-over-year gain** - final tested e1RM minus your baseline e1RM, per
  main lift.
- **Strength ratios vs published norms** - see below.
- **Weak points** - any lift whose ratio to another falls below the norm,
  ranked worst first, each with a plain-English reason.
- **Stalled lifts** - a main lift with no e1RM PR between your last two test
  weeks.
- **RPE drift** - the trend line through your last 8 logged RPEs for a lift.
  A rising slope means sessions are getting harder for the same plan, i.e.
  fatigue is building.
- **Adherence** - the share of Year-1 sessions where you logged at least one
  completed set.

## 2. Strength ratio norms (and where they come from)

These are coaching rules of thumb used to catch an obvious imbalance, not a
diagnosis or a lab-measured standard:

| Ratio | Typical range | Source |
|---|---|---|
| Squat / Deadlift | 0.80 - 0.90 | Common powerlifting coaching rule of thumb (e.g. Juggernaut Training Systems) |
| Bench Press / Squat | 0.65 - 0.80 | Same |
| Overhead Press / Bench Press | 0.60 - 0.70 | Same |
| Snatch / Clean & Jerk (supertotal) | 0.78 - 0.84 | USAW-style weightlifting coaching literature |
| Clean & Jerk / Front Squat (supertotal) | 0.80 - 0.90 | Same |

If a ratio comes in below its range, that lift becomes a "weak point" and
gets extra attention (below). Coming in *above* range isn't flagged - a big
squat relative to deadlift isn't a problem.

## 3. Year 2: heavy/light/medium daily undulation

After a beginner year, lifters respond well to *daily* undulating
periodization rather than one long block - Zourdos et al. (2016, Journal of
Strength & Conditioning Research) found an HLM (Heavy/Light/Medium) weekly
squat protocol out-performed a comparable linear progression for 1RM gains.
So Year 2 keeps Year 1's three-day-a-week, same-lift-per-day layout, but:

- Each day keeps a fixed role (Day 1 Heavy, Day 2 Light-for-squat/Heavy-for-
  press, Day 3 Variations), and %TM for each role rises across three-week
  "waves" inside each 12-week cycle - the same wave shape Year 1 uses.
- Every loaded set carries an **RPE target** (heavy 8-9, medium 7-8, light
  6-7), using the Helms/Zourdos RIR-based RPE scale (RPE 10 = 0 reps in
  reserve, 9 = 1, 8 = 2, ...), so the plan and the lifter's own effort can be
  reconciled session to session (see autoreg.py).
- Every working set is still capped by **Prilepin's chart / INOL** - reps
  per set and total reps stay inside the ranges Year 1 already respects for
  each %1RM zone.
- Planned deloads sit at weeks 4 and 8 of each cycle, a taper at week 11, a
  test week at 12, and the year ends the same way Year 1 does: three
  transition weeks (49-51) and a full deload (52).

## 4. Year 3: block periodization

By Year 3 a lifter has two years of tested maxes, so the plan moves to
classic Verkhoshansky block sequencing within each 12-week cycle:

| Weeks | Block | Intensity |
|---|---|---|
| 1-4 | Accumulation | 65-75% - higher volume, builds work capacity |
| 5-8 | Transmutation | 75-85% - turns that volume into strength |
| 9-11 | Realization | 85-95% - heavy, low-rep, peaking |
| 12 | Test | New maxes |

Same day layout, same Prilepin caps, same RPE-target idea (now attached per
block: 6-7 in Accumulation, 8-9 in Transmutation, 9-10 in Realization,
reflecting how each phase is meant to feel).

## 5. Individualizing on top of the base plan

Two mechanisms run on top of either year's base plan, both from your
`LifterProfile`:

- **Weak-point priority.** Your single worst-ranked weak point gets one
  extra working set on its main lift every loading week, plus a dedicated
  extra conjugate variation slot on Day 3 - more volume for that lift
  without crowding out the rest of the week.
- **Stalled-lift rotation.** Any main lift flagged as stalled stops being
  trained as the straight barbell lift and instead rotates through
  `exercises.ROTATION` for that lift, a new variation every 3-week block -
  the same conjugate-style rotation Year 1 already uses on Day 3, applied to
  a lift that's stopped producing PRs.

Every Prescription these mechanisms touch carries a `reason` string, so the
app can always show *why* a set looks different from the base plan.

## 6. Autoregulation (`autoreg.py`)

- **`next_load`** nudges a load toward its RPE target: about 2-2.5% per RPE
  point off target (a standard powerlifting coaching adjustment), rounded to
  your plate increment.
- **`readiness_adjust`** is a JuggernautAI-style daily check-in: rate
  yourself 1-5 before a session and the plan adjusts - 5 a little heavier,
  4 as planned, 3 a bit lighter, 2 lighter with a cut accessory set, 1 swaps
  to a light technique day.
- **`deload_due`** is a Renaissance Periodization-style performance-based
  deload, on top of the plan's own scheduled ones: it fires if RPE has
  drifted up a full point at the same load across two sessions, or you've
  missed your target rep count two sessions running.
- **`reflow_week`** handles a missed session: if Heavy didn't happen, it
  moves into the next open day and that week's Light day is dropped rather
  than crammed in alongside it, so you're never doing two hard days back to
  back.

## What's simplified (and honestly flagged)

- RPE drift is a straight-line slope through recent logged RPEs, not
  adjusted for whether the load was actually comparable session to session -
  a real fatigue signal, but a blunt one.
- Volume-landmark thinking (MEV/MAV/MRV) shows up as the wave/block volume
  ramps, not as full per-muscle-group tracking.
- Plyometric prescriptions increase slightly year over year but aren't yet
  wired to the lifter's actual jump-standard tier (`exercises.jump_level`) -
  that's a natural next step for the app layer.
