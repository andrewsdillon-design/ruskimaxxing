// UI-independent workout logic (port of src/ruskimaxxing/workout.py): pre-filled sets for a session,
// extra sets, "all done", saving and the PRs a save sets.
import { boxJumpTargets, CATALOG, isPlyo, STEP_HEIGHT } from './exercises';
import { fmt0, fmtG, pyInt, pyRound } from './pyfmt';
import { cycleStart, isLoaded, prescribedWeight, session, sessionDate, type Prescription } from './program';
import { nextMonday, isValidIso } from './dates';
import type { Store } from './store';
import { maxBy, newPrs, trainingMax, type LogEntry } from './tracking';

export const DEFAULT_INCREMENT: Record<string, number> = { lb: 5.0, kg: 2.5 };

/** Positive number from user text, else null. */
export function number(text: unknown): number | null {
  const s = String(text ?? '').trim();
  if (!s) return null;
  const v = Number(s);
  return Number.isFinite(v) && v > 0 ? v : null;
}

export interface Settings {
  start: string;
  unit: 'lb' | 'kg';
  increment: number;
  height: number | null;
}

export const heightUnit = (cfg: Settings) => (cfg.unit === 'kg' ? 'cm' : 'in');

export function settingsFrom(store: Store): Settings {
  const unit = store.get('units', 'lb') === 'kg' ? 'kg' : 'lb';
  const raw = store.get('start', '');
  return {
    start: isValidIso(raw) ? raw : nextMonday(),
    unit,
    increment: number(store.get('increment', '')) ?? DEFAULT_INCREMENT[unit],
    height: number(store.get('height', '')),
  };
}

/** '6' -> 6, '8-10' -> 8, '30-60s' -> 30, '5RM' -> 5, 'Max' -> 1. */
export function defaultReps(reps: string): string {
  if (reps === 'Max') return '1';
  let digits = '';
  for (const ch of reps) {
    if (ch >= '0' && ch <= '9') digits += ch;
    else if (digits) break;
  }
  return digits;
}

/** [pre-filled weight, where it came from] for one prescription. */
export function expectedWeight(p: Prescription, entries: LogEntry[], cycleStartDate: string, reps: string, cfg: Settings): [string, string] {
  const info = CATALOG.get(p.exercise);
  const inc = cfg.increment;
  const hu = heightUnit(cfg);
  if (info?.category === 'plyo') {
    // like training maxes: only jumps logged before this cycle (or starting values) set the target
    const before = entries.filter((e) => e.kind === 'baseline' || e.date < cycleStartDate);
    const best = Math.max(0, ...before.filter((e) => e.exercise === p.exercise && e.done).map((e) => e.weight));
    if (p.exercise === 'Box Jump') {
      const startBox = best || STEP_HEIGHT[hu];
      let goal = '';
      if (cfg.height) {
        const next = boxJumpTargets(cfg.height, hu).find(([, , t]) => t > best);
        goal = next ? ` - next standard: ${next[0]} ${fmtG(next[2])} ${hu}` : ' - Elite!';
      }
      return [fmtG(startBox), best ? `best ${fmtG(best)} ${hu}${goal}` : `start low${goal}`];
    }
    return best ? [fmtG(best), `beat ${fmtG(best)} ${hu}`] : ['', 'distance'];
  }
  if (info && (info.category === 'main' || info.category === 'variation')) {
    const [tm, estimated] = trainingMax(entries, p.exercise, cycleStartDate);
    if (!tm) return ['', 'enter a starting max'];
    const note = `TM ${fmt0(tm)}${estimated ? ' (est.)' : ''}`;
    if (isLoaded(p)) return [fmtG(prescribedWeight(p, tm, inc) as number), note];
    const r = pyInt(Number(reps || 1)); // test set: the weight you'd expect for that many reps
    const w = r > 1 ? pyRound(tm / (1 + r / 30) / inc) * inc : pyRound(tm / inc) * inc;
    return [fmtG(w), note + ' - try to beat it'];
  }
  const last = maxBy(entries.filter((e) => e.exercise === p.exercise && e.done && e.weight > 0),
    (e) => [Date.parse(e.date), e.id ?? 0]);
  return last ? [fmtG(last.weight), `last time ${fmtG(last.weight)} x ${last.reps}`] : ['', 'pick a weight'];
}

export interface SetRow {
  target: string;
  weight: string;
  reps: string;
  rpe: string;
  done: boolean;
}

export interface WorkoutBlock {
  p: Prescription;
  rows: SetRow[];
  source: string;
  planned: number;
  note: string;
}

/** Blocks for one session, pre-filled from the plan and overlaid with anything saved. */
export function workoutModel(store: Store, week: number, day: number, cfg: Settings, useSaved = true): WorkoutBlock[] {
  const entries = store.lifts();
  const s = session(week, day);
  const cs = cycleStart(cfg.start, s.cycle);
  const saved = new Map<string, LogEntry[]>();
  if (useSaved) for (const e of store.workout(week, day)) saved.set(e.exercise, [...(saved.get(e.exercise) ?? []), e]);
  return s.exercises.map((p) => {
    const reps = defaultReps(p.reps);
    const [weight, source] = expectedWeight(p, entries, cs, reps, cfg);
    const planned = Math.max(p.sets, 1);
    const mine = [...(saved.get(p.exercise) ?? [])].sort((a, b) => (a.setNo ?? 0) - (b.setNo ?? 0));
    const rows: SetRow[] = [];
    for (let k = 0; k < Math.max(planned, mine.length); k++) {
      const e = k < mine.length ? mine[k] : null;
      rows.push({
        target: k < planned ? `${weight || '-'} x ${reps || p.reps}` : 'extra set',
        weight: e ? (e.weight ? fmtG(e.weight) : '') : weight,
        reps: e ? (e.reps ? String(e.reps) : '') : reps,
        rpe: e ? (e.rpe ? fmtG(e.rpe) : '') : '',
        done: e ? e.done : false,
      });
    }
    return { p, rows, source, planned, note: mine.length ? mine[0].note : '' };
  });
}

/** Append an extra set to block `index`, copying the last set's numbers. */
export function addSet(blocks: WorkoutBlock[], index: number): WorkoutBlock[] {
  return blocks.map((b, i) => {
    if (i !== index) return b;
    const last = b.rows[b.rows.length - 1];
    const extra: SetRow = { ...(last ?? { weight: '', reps: '' }), target: 'extra set', done: false, rpe: '' } as SetRow;
    return { ...b, rows: [...b.rows, extra] };
  });
}

export function markAllDone(blocks: WorkoutBlock[]): WorkoutBlock[] {
  return blocks.map((b) => ({ ...b, rows: b.rows.map((r) => (r.reps ? { ...r, done: true } : r)) }));
}

/** Best new PR per exercise and type, e.g. 'Squat: 5RM 210'. */
export function workoutPrs(others: LogEntry[], doneSets: LogEntry[]): string[] {
  const best = new Map<string, [string, string, number]>();
  for (const e of doneSets) {
    const plyo = isPlyo(e.exercise);
    for (let label of newPrs([...others, e], e)) {
      if (plyo) {
        if (!label.startsWith('1RM')) continue;
        label = `Best ${fmtG(e.weight)}`;
      }
      const cut = label.lastIndexOf(' ');
      const kind = label.slice(0, cut);
      const value = Number(label.slice(cut + 1));
      const key = `${e.exercise}\u0000${kind}`;
      const prev = best.get(key);
      if (!prev || value > prev[2]) best.set(key, [e.exercise, kind, value]);
    }
  }
  return [...best.values()].map(([ex, kind, value]) => `${ex}: ${kind} ${fmtG(value)}`);
}

export interface SaveResult {
  saved: LogEntry[];
  prs: string[];
  /** sets ticked done without reps (saved as not done) */
  bad: string[];
}

/** Save every set of a session. */
export function saveWorkout(store: Store, week: number, day: number, blocks: WorkoutBlock[], cfg: Settings): SaveResult {
  const s = session(week, day);
  const when = sessionDate(s, cfg.start);
  const entries: LogEntry[] = [];
  const bad: string[] = [];
  for (const b of blocks) {
    const p = b.p;
    const kind = p.kind === 'test' || p.reps === 'Max' ? 'test' : 'training';
    b.rows.forEach((row, i) => {
      const k = i + 1;
      const reps = number(row.reps);
      if (row.done && !reps) bad.push(`${p.exercise} set ${k}`);
      entries.push({
        date: when, exercise: p.exercise, weight: number(row.weight) ?? 0, reps: pyInt(reps ?? 0), kind, note: b.note ?? '',
        id: null, week: null, day: null, setNo: k, rpe: number(row.rpe), done: !!(row.done && reps),
      });
    });
  }
  const others = store.lifts().filter((e) => !(e.week === week && e.day === day));
  const saved = store.saveWorkout(week, day, entries);
  return { saved, prs: workoutPrs(others, saved.filter((e) => e.done)), bad };
}

/** [sets done, sets planned] for a session. */
export function dayProgress(store: Store, week: number, day: number): [number, number] {
  const planned = session(week, day).exercises.reduce((n, p) => n + Math.max(p.sets, 1), 0);
  return [store.workout(week, day).filter((e) => e.done).length, planned];
}
