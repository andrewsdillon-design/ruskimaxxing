// PRs, training maxes and body measurements (port of src/ruskimaxxing/tracking.py).
// Every logged set feeds rep maxes (1RM-12RM), the best estimated 1RM (Epley) and each cycle's training max.
import { CATALOG } from './exercises';
import { fmt0, fmtG, pyRoundTo } from './pyfmt';
import { toUtc } from './dates';

export const REP_MAX_COUNTS = [1, 2, 3, 4, 5, 6, 8, 10, 12];
export const BODYFAT_METHODS = ['Bod Pod', 'InBody', 'Hydrostatic (dunk tank)', 'DEXA', 'Calipers', 'Other'];

export type EntryKind = 'baseline' | 'training' | 'test';

export interface LogEntry {
  date: string; // ISO YYYY-MM-DD
  exercise: string;
  weight: number;
  reps: number;
  kind: EntryKind;
  note: string;
  id: number | null;
  week: number | null; // program week / day / set this belongs to (null = off-program)
  day: number | null;
  setNo: number | null;
  rpe: number | null;
  done: boolean; // only completed sets count toward PRs and maxes
}

export function entry(fields: Partial<LogEntry> & Pick<LogEntry, 'date' | 'exercise' | 'weight' | 'reps'>): LogEntry {
  return { kind: 'training', note: '', id: null, week: null, day: null, setNo: null, rpe: null, done: true, ...fields };
}

export interface BodyWeight {
  week: number;
  date: string;
  weight: number;
}

export interface BodyFat {
  month: number;
  date: string;
  percent: number;
  method: string;
  weight: number | null;
}

export const leanMass = (bf: BodyFat): number | null =>
  bf.weight === null ? null : pyRoundTo(bf.weight * (1 - bf.percent / 100), 1);

/** Epley estimate of a one-rep max. */
export function estimate1rm(weight: number, reps: number): number {
  if (weight < 0 || reps < 1) throw new Error('weight must be >= 0 and reps >= 1');
  return reps === 1 ? weight : weight * (1 + reps / 30);
}

export const e1rm = (e: LogEntry) => estimate1rm(e.weight, e.reps);

const forExercise = (entries: LogEntry[], exercise: string) =>
  entries.filter((e) => e.exercise === exercise && e.done && e.weight > 0 && e.reps > 0);

/** Python's max(items, key=...): the first item with the largest key (keys compared element by element). */
export function maxBy<T>(items: T[], key: (t: T) => number[]): T | null {
  let best: T | null = null;
  let bestKey: number[] = [];
  for (const item of items) {
    const k = key(item);
    if (best === null || compare(k, bestKey) > 0) {
      best = item;
      bestKey = k;
    }
  }
  return best;
}

function compare(a: number[], b: number[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return a.length - b.length;
}

const ordinal = (iso: string) => toUtc(iso).getTime() / 86400000; // like date.toordinal(): only order matters

/** Heaviest set with at least N reps, for each N in REP_MAX_COUNTS. */
export function repMaxes(entries: LogEntry[], exercise: string): Map<number, LogEntry> {
  const mine = forExercise(entries, exercise);
  const out = new Map<number, LogEntry>();
  for (const n of REP_MAX_COUNTS) {
    const best = maxBy(mine.filter((e) => e.reps >= n), (e) => [e.weight, -ordinal(e.date)]);
    if (best) out.set(n, best);
  }
  return out;
}

/** Best estimated-1RM set. With `before`, only baseline sets and sets dated earlier count. */
export function bestE1rm(entries: LogEntry[], exercise: string, before: string | null = null): LogEntry | null {
  const mine = forExercise(entries, exercise).filter((e) => before === null || e.kind === 'baseline' || e.date < before);
  return maxBy(mine, (e) => [e1rm(e)]);
}

/** The max a cycle's percentages are based on: [value, isEstimate]. Variations with no data use parent x ratio. */
export function trainingMax(entries: LogEntry[], exercise: string, cycleStart: string | null = null): [number | null, boolean] {
  const best = bestE1rm(entries, exercise, cycleStart);
  if (best) return [e1rm(best), false];
  const info = CATALOG.get(exercise);
  if (info?.parent && info.ratio !== null) {
    const parent = bestE1rm(entries, info.parent, cycleStart);
    if (parent) return [e1rm(parent) * info.ratio, true];
  }
  return [null, false];
}

/** PRs `entry` sets against all earlier logged sets of the same exercise. */
export function newPrs(entries: LogEntry[], e: LogEntry): string[] {
  const previous = forExercise(entries, e.exercise).filter((x) => x !== e && (e.id === null || x.id !== e.id));
  const prs: string[] = [];
  const bestBefore = Math.max(0, ...previous.map(e1rm));
  if (e1rm(e) > bestBefore) prs.push(`Estimated 1RM ${fmt0(e1rm(e))}`);
  for (const n of REP_MAX_COUNTS) {
    if (e.reps >= n) {
      const prior = Math.max(0, ...previous.filter((x) => x.reps >= n).map((x) => x.weight));
      if (e.weight > prior) prs.push(`${n}RM ${fmtG(e.weight)}`);
    }
  }
  return prs;
}

/** Running best estimated 1RM over time, one point per training date. */
export function e1rmHistory(entries: LogEntry[], exercise: string): [string, number][] {
  const points: [string, number][] = [];
  let best = 0;
  const sorted = [...forExercise(entries, exercise)].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  for (const e of sorted) {
    best = Math.max(best, e1rm(e));
    if (points.length && points[points.length - 1][0] === e.date) points[points.length - 1] = [e.date, best];
    else points.push([e.date, best]);
  }
  return points;
}

export const BODYFAT_GUIDE = `Pick ONE method and stick with it - different methods disagree by several percent, so the trend from a single method matters far more than any one number.

Bod Pod (air displacement)
• Find one at a university kinesiology/exercise-science lab, sports-medicine clinic or larger gym; search "Bod Pod near me". Usually $25-$60 per test.
• Wear tight, minimal clothing (compression shorts / sports bra) and a swim cap.
• Test fasted (no food 2-3 h), no exercise that day, empty bladder.

InBody (bioelectrical impedance scale)
• Many gyms, chiropractors, physical therapists and nutrition clinics have one; often free or $10-$30.
• Hydration changes the reading a lot: test first thing in the morning, before eating, drinking large amounts, caffeine or training. Empty bladder, no lotion, stand barefoot on clean electrodes.

Hydrostatic / underwater weighing ("dunk tank")
• Offered by university labs, sports-performance centers and mobile body-fat trucks that visit gyms; usually $40-$75.
• Fasted 3-4 h, no training that day. You exhale fully while submerged, so practice a slow, complete exhale; the tester usually takes 3 readings.

For every method
• Same method, same place, same time of day, same pre-test routine each month.
• Test in a deload week if you can, not right after a hard session.
• Record the date, your body-fat %, the method, and the weight the test measured.`;
