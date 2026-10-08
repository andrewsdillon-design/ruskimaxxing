// The TypeScript training logic must produce exactly what the Python originals produce.
// fixtures.json is written by `python tools/export_mobile_fixtures.py` (the Python tests fail if it's stale).
import fixtures from './fixtures.json';
import { CATALOG, jumpLevel, jumpTargets } from '../exercises';
import { fmt0, fmtG, pyRound, pyRoundTo } from '../pyfmt';
import { bodyfatWeek, buildProgram, cycleStart, MONTHS, monthLabel, monthOf, monthWeeks, sessionDate, WEEKS, weekLabel } from '../program';
import { memoryPersistence, Store } from '../store';
import { bestE1rm, e1rm, e1rmHistory, newPrs, repMaxes, trainingMax, type LogEntry } from '../tracking';
import { addSet, dayProgress, saveWorkout, settingsFrom, workoutModel } from '../workout';

const F = fixtures as any;
const START: string = F.start;

const json = (e: LogEntry) => ({
  date: e.date, exercise: e.exercise, weight: e.weight, reps: e.reps, kind: e.kind, note: e.note,
  week: e.week, day: e.day, setNo: e.setNo, rpe: e.rpe, done: e.done,
});

describe('python number formatting', () => {
  test.each([
    [2.5, 2], [3.5, 4], [-2.5, -2], [262.5, 262], [263.5, 264], [1.4, 1], [1.6, 2],
  ])('round(%p) = %p', (x, want) => expect(pyRound(x)).toBe(want));
  test.each([
    [185, '185'], [62.5, '62.5'], [0.5, '0.5'], [101.6, '101.6'], [1e6, '1e+06'], [123456.7, '123457'], [0.0001, '0.0001'], [0.00001, '1e-05'],
  ])('%p:g = %p', (x, want) => expect(fmtG(x)).toBe(want));
  test.each([[262.5, '262'], [263.5, '264'], [291.6666, '292']])('%p:.0f = %p', (x, want) => expect(fmt0(x)).toBe(want));
  test('round(x, 1)', () => expect(pyRoundTo(70 * 0.72, 1)).toBe(50.4));
});

test('catalog matches, in order', () => {
  expect([...CATALOG.values()]).toEqual(F.catalog);
});

test('the whole program matches, session by session', () => {
  const ours = buildProgram().map((s) => ({
    week: s.week, cycle: s.cycle, phase: s.phase, dayIndex: s.dayIndex, day: s.day, date: sessionDate(s, START),
    exercises: s.exercises,
  }));
  expect(ours.length).toBe(F.program.length);
  ours.forEach((s, i) => expect(s).toEqual(F.program[i]));
});

test('labels match', () => {
  const L = F.labels;
  expect(Array.from({ length: WEEKS + 1 }, (_, w) => weekLabel(w))).toEqual(L.week);
  expect(Array.from({ length: MONTHS + 1 }, (_, m) => monthLabel(m))).toEqual(L.month);
  expect(Array.from({ length: WEEKS + 1 }, (_, w) => monthOf(w))).toEqual(L.monthOf);
  expect(Array.from({ length: MONTHS + 1 }, (_, m) => monthWeeks(m))).toEqual(L.monthWeeks);
  expect(Array.from({ length: MONTHS }, (_, m) => bodyfatWeek(m + 1))).toEqual(L.bodyfatWeek);
  expect(Array.from({ length: 6 }, (_, c) => cycleStart(START, c))).toEqual(L.cycleStart);
});

describe.each(F.scenarios.map((s: any) => [`${s.unit}, ${s.increment} increment, height ${s.height}`, s]) as [string, any][])('scenario %s', (_name: string, sc: any) => {
  async function makeStore() {
    const store = await Store.open(memoryPersistence());
    store.setMany({ units: sc.unit, increment: fmtG(sc.increment), start: START, ...(sc.height ? { height: fmtG(sc.height) } : {}) });
    for (const e of sc.entries) store.addLift({ ...e, id: null });
    return store;
  }

  test('pre-filled workouts', async () => {
    const store = await makeStore();
    const cfg = settingsFrom(store);
    for (const w of sc.workouts) {
      const blocks = workoutModel(store, w.week, w.day, cfg).map((b) => ({
        exercise: b.p.exercise, source: b.source, planned: b.planned, note: b.note, rows: b.rows,
      }));
      expect({ week: w.week, day: w.day, blocks }).toEqual(w);
    }
  });

  test('training maxes', async () => {
    const lifts = (await makeStore()).lifts();
    for (const t of sc.trainingMaxes) {
      const [tm, estimated] = trainingMax(lifts, t.exercise, cycleStart(START, t.cycle));
      expect({ exercise: t.exercise, cycle: t.cycle, tm, estimated }).toEqual(t);
    }
  });

  test('rep maxes, best e1RM and history', async () => {
    const lifts = (await makeStore()).lifts();
    for (const [ex, want] of Object.entries<any>(sc.prs)) {
      const rms = Object.fromEntries([...repMaxes(lifts, ex)].map(([n, e]) => [String(n), json(e)]));
      const best = bestE1rm(lifts, ex);
      expect({ repMaxes: rms, bestE1rm: best ? e1rm(best) : null, history: e1rmHistory(lifts, ex) }).toEqual(want);
    }
  });

  test('jump standards', () => {
    for (const j of sc.jumps) {
      expect(jumpTargets(j.exercise, j.height, j.unit)).toEqual(j.targets);
      expect(jumpLevel(j.exercise, j.best, j.height, j.unit)).toBe(j.level);
    }
  });

  test('saving a workout: sets, PRs, bad sets, reload, progress', async () => {
    const store = await makeStore();
    const cfg = settingsFrom(store);
    const s = sc.save;
    let blocks = workoutModel(store, s.week, s.day, cfg);
    for (const ed of s.edits) {
      const row = blocks[ed.block].rows[ed.row];
      for (const key of ['weight', 'reps', 'rpe', 'done'] as const) if (key in ed) (row as any)[key] = ed[key];
    }
    blocks = addSet(blocks, s.extraSetBlock);
    blocks[s.extraSetBlock] = { ...blocks[s.extraSetBlock], note: s.note };
    const result = saveWorkout(store, s.week, s.day, blocks, cfg);
    expect(result.saved.map(json)).toEqual(s.saved);
    expect(result.prs).toEqual(s.workoutPrs);
    expect(result.bad).toEqual(s.bad);
    const after = workoutModel(store, s.week, s.day, cfg).map((b) => ({ exercise: b.p.exercise, source: b.source, note: b.note, rows: b.rows }));
    expect(after).toEqual(s.after);
    expect([0, 1, 2].map((d) => dayProgress(store, s.week, d))).toEqual(s.progress);
    const lifts = store.lifts();
    const cases = lifts.filter((e) => e.week === s.week && e.day === s.day && e.done).map((e) => ({ entry: json(e), prs: newPrs(lifts, e) }));
    expect(cases).toEqual(s.newPrs);
  });
});
