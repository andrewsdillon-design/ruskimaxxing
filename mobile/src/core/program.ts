// The one-year program (port of src/ruskimaxxing/program.py, standard edition): week 0 baseline, four
// 12-week cycles (accumulation, deload, transmutation, deload, realization, taper, test), then a 4-week
// transition. Prilepin's chart sets sets x reps for every loaded session.
import { addDays, addWeeks } from './dates';
import { CATALOG, OLY, PLYO_GUIDE, ROTATION } from './exercises';
import { load, zoneFor } from './prilepin';

export const WEEKS = 52;
export const CYCLE_WEEKS = 12;
export const CYCLES = 4;
export const DAY_OFFSETS = [0, 2, 4]; // Mon / Wed / Fri
export const MONTH_WEEKS = 4;
export const MONTHS = WEEKS / MONTH_WEEKS; // 13

export type Kind = 'main' | 'variation' | 'accessory' | 'plyo' | 'test';

export interface Prescription {
  exercise: string;
  sets: number;
  reps: string;
  percent: number | null; // % of this exercise's training max
  note: string;
  kind: Kind;
}

export interface Session {
  week: number;
  cycle: number; // 0 = baseline, 1-4 = cycles, 5 = transition
  phase: string;
  dayIndex: number;
  day: string;
  exercises: Prescription[];
}

interface Block {
  name: string;
  weeks: number[];
  intensity: Record<string, number[]>;
  repBias: 'high' | 'mid';
  accessorySets: number;
  plyo: [number, number];
}

const BLOCKS: Block[] = [
  { name: 'Accumulation', weeks: [1, 2, 3], intensity: { heavy: [70, 72.5, 75], medium: [65, 67.5, 70], light: [60, 62.5, 65] }, repBias: 'high', accessorySets: 4, plyo: [4, 3] },
  { name: 'Transmutation', weeks: [5, 6, 7], intensity: { heavy: [77.5, 80, 82.5], medium: [72.5, 75, 77.5], light: [65, 67.5, 70] }, repBias: 'high', accessorySets: 3, plyo: [4, 3] },
  { name: 'Realization', weeks: [9, 10], intensity: { heavy: [85, 90], medium: [77.5, 80], light: [67.5, 70] }, repBias: 'mid', accessorySets: 3, plyo: [3, 2] },
];
const DELOAD: Record<number, number> = { 4: 60.0, 8: 65.0 };
const TAPER_WEEK = 11;

const SLOTS: Record<string, string> = { '@squat': 'Squat', '@bench': 'Bench Press', '@deadlift': 'Deadlift', '@olympic': 'Olympic', '@plyo': 'Plyo' };
const TEST_PLYO = ['Box Jump', 'Broad Jump', 'Vertical Jump'];

type Day = [name: string, plyo: string[], lifts: [string, string][], accessories: [string, string][]];
const DAYS: Day[] = [
  ['Day 1 - Heavy', ['Box Jump'], [['Squat', 'heavy'], ['Bench Press', 'heavy']],
    [['Barbell Row', '8-10'], ['Face Pull', '12-15'], ['Dumbbell Curl', '10-12']]],
  ['Day 2 - Light', ['Broad Jump', 'Med Ball Chest Pass'], [['Squat', 'light'], ['Overhead Press', 'heavy'], ['Deadlift', 'medium']],
    [['Chin-up', '6-10'], ['Back Extension', '10-15'], ['Plank', '30-60s']]],
  ['Day 3 - Variations', ['@plyo'], [['@squat', 'medium'], ['@bench', 'medium'], ['@deadlift', 'light']],
    [['Incline Dumbbell Press', '8-12'], ['One-Arm Dumbbell Row', '10-12'], ['Triceps Pushdown', '10-15']]],
];
const TESTED: Record<number, Set<string>> = { 0: new Set(['Squat', 'Bench Press']), 1: new Set(['Deadlift', 'Overhead Press']) };

const ACCESSORY_NOTE = 'Leave 1-2 reps in the tank; add weight when you hit the top of the range';
const TEST_NOTE = 'Work up in small jumps to a new max (1RM, or a 3RM/5RM if you prefer). Log it - it sets next cycle\'s weights';

export const SHOULDER_TIP =
  'SHOULDER TIP - for you malchiki with no shoulder development: 100 reps each of front raises, lateral (medial) raises and ' +
  'rear delt raises EVERY night before bed with 5 lb (2.5 kg) dumbbells. Go buy a pair and keep them by your nightstand.';

export const isLoaded = (p: Prescription) => p.percent !== null;

export function prescribedWeight(p: Prescription, trainingMax: number | null, increment: number): number | null {
  if (p.percent === null || !trainingMax) return null;
  return load(trainingMax, p.percent, increment);
}

export function sessionDate(s: Session, start: string): string {
  return addDays(addWeeks(start, s.week - 1), DAY_OFFSETS[s.dayIndex]);
}

export function cycleOf(week: number): number {
  if (week === 0) return 0;
  return Math.min(CYCLES + 1, Math.floor((week - 1) / CYCLE_WEEKS) + 1);
}

/** First day of a cycle; its training maxes use sets logged before this date. */
export function cycleStart(start: string, cycle: number): string {
  return addWeeks(start, Math.max(0, cycle - 1) * CYCLE_WEEKS);
}

export function variation(lift: string, cycle: number, block: number): string {
  const options = ROTATION[lift];
  return options[((Math.max(cycle, 1) - 1) * 3 + block) % options.length];
}

export function isOlympic(exercise: string): boolean {
  const info = CATALOG.get(exercise);
  return (OLY as readonly string[]).includes(exercise) || !!(info?.parent && (OLY as readonly string[]).includes(info.parent));
}

function resolve(slot: string, cycle: number, block: number): [string, Kind] {
  return slot in SLOTS ? [variation(SLOTS[slot], cycle, block), 'variation'] : [slot, 'main'];
}

function setsReps(percent: number, bias: string, lift: string, day: string): [number, number] {
  const zone = zoneFor(percent);
  const [lo, hi] = zone.repsPerSet;
  if (isOlympic(lift)) return [Math.max(3, Math.ceil(zone.totalRange[0] / lo)), lo];
  const reps = bias === 'high' ? hi : Math.floor((lo + hi + 1) / 2);
  const pulls = lift.includes('Deadlift') || lift.includes('Pull');
  const total = day === 'light' || pulls ? zone.totalRange[0] : zone.optimalTotal;
  return [Math.max(3, Math.ceil(total / reps)), reps];
}

const rx = (exercise: string, sets: number, reps: string, percent: number | null = null, note = '', kind: Kind = 'main'): Prescription =>
  ({ exercise, sets, reps, percent, note, kind });

const accessories = (list: [string, string][], sets: number, note = ACCESSORY_NOTE) =>
  list.map(([a, r]) => rx(a, sets, r, null, note, 'accessory'));

const plyo = (name: string, sets: number, reps: number | string, note?: string) =>
  rx(name, sets, String(reps), null, note ?? PLYO_GUIDE[name], 'plyo');

function plyos(slots: string[], cycle: number, block: number, sets: number, reps: number): Prescription[] {
  return slots.map((slot) => {
    const name = resolve(slot, cycle, block)[0];
    return name === 'Med Ball Chest Pass' ? plyo(name, Math.max(2, sets - 1), sets > 2 ? 5 : 3) : plyo(name, sets, reps);
  });
}

function plyoTest(dayIndex: number, baseline = false): Prescription {
  const name = TEST_PLYO[dayIndex];
  const how: Record<string, string> = {
    'Box Jump': 'work up box by box to the highest box you land cleanly',
    'Broad Jump': 'best of 3-5 jumps for distance',
    'Vertical Jump': 'best of 3-5 jumps (jump mark minus standing reach)',
  };
  return plyo(name, 1, 'Max', (baseline ? 'Find your best: ' : 'Test day: ') + how[name] + '. Log it and check the standards on Start Here');
}

function weekSessions(week: number): Session[] {
  const cycle = cycleOf(week);
  return DAYS.map(([name, plyoSlots, lifts, acc], i) => {
    let phase: string;
    let exercises: Prescription[];
    if (week === 0) {
      phase = 'Baseline';
      exercises = [plyoTest(i, true)];
      for (const [s] of lifts) {
        const [ex] = resolve(s, 1, 0);
        if (ex === 'Squat' && i === 1) continue;
        const oly = isOlympic(ex);
        const note = oly ? 'Work up to a technically clean heavy single' : "Work up to a hard set of 5 (or a 1RM if you're experienced)";
        exercises.push(rx(ex, 1, oly ? '1RM' : '5RM', null, 'Optional - skip if you entered maxes. ' + note, 'test'));
      }
      exercises.push(...accessories(acc, 2, 'Find a weight you can do for the top of the range'));
    } else if (cycle === CYCLES + 1) {
      const weekIn = week - CYCLES * CYCLE_WEEKS;
      const resolved = lifts.map(([s]) => resolve(s, cycle, 0));
      if (weekIn < 4) {
        phase = 'Transition';
        const pct = [60, 62.5, 65][weekIn - 1];
        exercises = plyos(plyoSlots, cycle, 0, 3, 3);
        exercises.push(...resolved.map(([ex, kind]) => rx(ex, 3, isOlympic(ex) ? '3' : '8', pct, 'Easy volume - stay 3+ reps from failure', kind)));
        exercises.push(...accessories(acc, 4));
      } else {
        phase = 'Deload';
        exercises = plyos(plyoSlots, cycle, 0, 2, 3);
        exercises.push(...resolved.map(([ex, kind]) => rx(ex, 2, isOlympic(ex) ? '2' : '5', 55.0, 'Full recovery week before the next year', kind)));
        exercises.push(...accessories(acc, 2, 'Easy'));
      }
    } else {
      const w = ((week - 1) % CYCLE_WEEKS) + 1;
      const blockIdx = w <= 4 ? 0 : w <= 8 ? 1 : 2;
      const block = BLOCKS.find((b) => b.weeks.includes(w));
      const resolved = lifts.map(([s, intensity]) => [...resolve(s, cycle, blockIdx), intensity] as [string, Kind, string]);
      if (block) {
        phase = block.name;
        const idx = block.weeks.indexOf(w);
        exercises = plyos(plyoSlots, cycle, blockIdx, ...block.plyo);
        for (const [ex, kind, intensity] of resolved) {
          const pct = block.intensity[intensity][idx];
          const [sets, reps] = setsReps(pct, block.repBias, ex, intensity);
          exercises.push(rx(ex, sets, String(reps), pct, '', kind));
        }
        exercises.push(...accessories(acc, block.accessorySets));
      } else if (w in DELOAD) {
        phase = 'Deload';
        exercises = plyos(plyoSlots, cycle, blockIdx, 2, 3);
        exercises.push(...resolved.map(([ex, kind]) => rx(ex, 2, isOlympic(ex) ? '2' : '5', DELOAD[w], 'Easy week - move fast, recover', kind)));
        exercises.push(...accessories(acc, 2, 'Easy - stop well short of failure'));
      } else if (w === TAPER_WEEK) {
        phase = 'Taper';
        exercises = plyos(plyoSlots, cycle, blockIdx, 2, 2);
        for (const [ex, kind, intensity] of resolved) {
          if (kind === 'variation') exercises.push(rx(ex, 2, isOlympic(ex) ? '2' : '3', 75.0, 'Crisp and fast', kind));
          else if (intensity === 'light') exercises.push(rx(ex, 2, '3', 65.0, 'Easy', kind));
          else exercises.push(rx(ex, i === 0 ? 3 : 2, isOlympic(ex) ? '1' : '2', 80.0, 'Keep it heavy but short - no grinding', kind));
        }
        exercises.push(...accessories(acc, 2, 'Light - save energy for test week'));
      } else {
        phase = 'Test';
        const tested = TESTED[i] ?? new Set<string>();
        exercises = [plyoTest(i)];
        for (const [ex, kind] of resolved) {
          if (kind === 'variation') {
            const reps = isOlympic(ex) ? '1RM' : '3RM';
            exercises.push(rx(ex, 1, reps, null, `Work up to a ${reps} - tracked as its own PR`, 'test'));
          } else if (tested.has(ex)) {
            exercises.push(rx(ex, 1, 'Max', null, TEST_NOTE, 'test'));
          } else {
            exercises.push(rx(ex, 2, '3', 60.0, 'Light technique work', kind));
          }
        }
        exercises.push(...accessories(acc, 2, 'Light'));
      }
    }
    return { week, cycle, phase, dayIndex: i, day: name, exercises };
  });
}

/** Every session of the year, week 0 (baseline) through week 52. */
export function buildProgram(): Session[] {
  const out: Session[] = [];
  for (let week = 0; week <= WEEKS; week++) out.push(...weekSessions(week));
  return out;
}

export const PROGRAM = buildProgram();

export function session(week: number, day: number): Session {
  const s = PROGRAM.find((x) => x.week === week && x.dayIndex === day);
  if (!s) throw new Error(`no session for week ${week} day ${day}`);
  return s;
}

export function weekLabel(week: number): string {
  const phase = session(week, 0).phase;
  if (week === 0) return 'Week 0 - Baseline test (optional)';
  const cycle = cycleOf(week);
  if (cycle > CYCLES) return `Week ${week} - Transition` + (phase === 'Deload' ? ' - Deload' : '');
  return `Week ${week} - Cycle ${cycle} - ${phase}`;
}

export function monthOf(week: number): number {
  return week === 0 ? 0 : Math.floor((week - 1) / MONTH_WEEKS) + 1;
}

export function monthWeeks(month: number): number[] {
  if (month === 0) return [0];
  return Array.from({ length: MONTH_WEEKS }, (_, k) => (month - 1) * MONTH_WEEKS + 1 + k);
}

export function monthLabel(month: number): string {
  if (month === 0) return 'Baseline - Week 0 (optional test)';
  const weeks = monthWeeks(month);
  const cycle = cycleOf(weeks[0]);
  return `Month ${month} - Weeks ${weeks[0]}-${weeks[weeks.length - 1]} - ` + (cycle > CYCLES ? 'Transition' : `Cycle ${cycle}`);
}

/** Program week of the monthly body-fat test: the first week of each training month. */
export const bodyfatWeek = (month: number) => (month - 1) * MONTH_WEEKS + 1;
