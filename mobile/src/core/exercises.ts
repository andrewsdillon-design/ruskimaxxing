// Every movement the program uses or tracks (port of src/ruskimaxxing/exercises.py, standard edition).
// A variation names its parent competition lift and a typical strength ratio to it; with no max of its
// own yet, its max is estimated as parent max x ratio.
import { pyRoundTo } from './pyfmt';

export type Category = 'main' | 'variation' | 'accessory' | 'plyo';

export interface Exercise {
  name: string;
  category: Category;
  parent: string | null;
  ratio: number | null;
}

export const MAIN = ['Squat', 'Bench Press', 'Deadlift', 'Overhead Press'] as const;
export const OLY = ['Snatch', 'Clean & Jerk'] as const;

const VARIATIONS: [string, [string, number][]][] = [
  ['Squat', [['Box Squat', 0.9], ['Pause Squat', 0.85], ['Front Squat', 0.8], ['Safety Bar Squat', 0.9], ['Pin Squat', 0.85], ['Tempo Squat', 0.8]]],
  ['Bench Press', [
    ['Close-Grip Bench Press', 0.92], ['1-Board Press', 1.03], ['2-Board Press', 1.06], ['3-Board Press', 1.1],
    ['Pause Bench Press', 0.95], ['Floor Press', 0.95], ['Pin Press', 1.0], ['Spoto Press', 0.93], ['Incline Bench Press', 0.8],
  ]],
  ['Deadlift', [
    ['Romanian Deadlift', 0.7], ['Deficit Deadlift', 0.9], ['Paused Deadlift', 0.85], ['Block Pull', 1.05],
    ['Rack Pull', 1.1], ['Sumo Deadlift', 1.0], ['Snatch-Grip Deadlift', 0.8],
  ]],
  ['Overhead Press', [['Push Press', 1.2], ['Seated Overhead Press', 0.9], ['Z Press', 0.8], ['Behind-the-Neck Press', 0.85]]],
];

export const PLYOS = [
  'Box Jump', 'Broad Jump', 'Vertical Jump', 'Depth Jump', 'Hurdle Hop', 'Lateral Bound', 'Plyo Push-up',
  'Seated Box Jump', 'Med Ball Chest Pass',
];

export const ACCESSORIES = [
  'Barbell Row', 'Face Pull', 'Dumbbell Curl', 'Chin-up', 'Lat Pulldown', 'Back Extension', 'Plank',
  'Incline Dumbbell Press', 'One-Arm Dumbbell Row', 'Triceps Pushdown', 'Walking Lunge', 'Leg Press',
  'Hanging Leg Raise', 'Dip', 'Hammer Curl', 'Lateral Raise', 'Reverse Hyper', 'Good Morning', 'Glute-Ham Raise',
];

/** Insertion-ordered like the Python dict, so lists (PR board, pickers) come out in the same order. */
export const CATALOG = new Map<string, Exercise>();
for (const name of MAIN) CATALOG.set(name, { name, category: 'main', parent: null, ratio: null });
for (const [parent, list] of VARIATIONS)
  for (const [name, ratio] of list) CATALOG.set(name, { name, category: 'variation', parent, ratio });
for (const name of ACCESSORIES) CATALOG.set(name, { name, category: 'accessory', parent: null, ratio: null });
for (const name of PLYOS) CATALOG.set(name, { name, category: 'plyo', parent: null, ratio: null });

export const isPlyo = (name: string) => CATALOG.get(name)?.category === 'plyo';

/** Variations rotated through Day 3, one per 3-week block. */
export const ROTATION: Record<string, string[]> = {
  Squat: ['Box Squat', 'Pause Squat', 'Front Squat', 'Safety Bar Squat', 'Pin Squat'],
  'Bench Press': ['Close-Grip Bench Press', '2-Board Press', 'Pause Bench Press', '1-Board Press', 'Floor Press', '3-Board Press', 'Spoto Press'],
  Deadlift: ['Romanian Deadlift', 'Deficit Deadlift', 'Paused Deadlift', 'Block Pull'],
  Olympic: ['Power Snatch', 'Power Clean', 'Hang Snatch', 'Hang Clean', 'Snatch Balance', 'Push Jerk', 'Block Snatch', 'Split Jerk'],
  Plyo: ['Depth Jump', 'Hurdle Hop', 'Vertical Jump', 'Lateral Bound', 'Plyo Push-up', 'Seated Box Jump'],
};

// Jump standards: a ratio is a fraction of standing height; an absolute value is [inches, cm].
type Rule = ['abs', number, number] | ['ratio', number];
export const JUMP_STANDARDS: Record<string, [string, string, Rule][]> = {
  'Box Jump': [
    ['Beginner', '1 step', ['abs', 7.5, 19.0]],
    ['Intermediate', 'above knee height', ['ratio', 0.3]],
    ['Proficient', 'chest height', ['ratio', 0.72]],
    ['Elite', 'head height', ['ratio', 0.93]],
  ],
  'Broad Jump': [
    ['Beginner', '3/4 of your height', ['ratio', 0.75]],
    ['Intermediate', 'your height', ['ratio', 1.0]],
    ['Proficient', '1.25 x your height', ['ratio', 1.25]],
    ['Elite', '1.5 x your height', ['ratio', 1.5]],
  ],
  'Vertical Jump': [
    ['Beginner', '12 in / 30 cm', ['abs', 12.0, 30.0]],
    ['Intermediate', '18 in / 46 cm', ['abs', 18.0, 46.0]],
    ['Proficient', '24 in / 61 cm', ['abs', 24.0, 61.0]],
    ['Elite', '30 in / 76 cm', ['abs', 30.0, 76.0]],
  ],
};
export const STEP_HEIGHT: Record<string, number> = { in: 7.5, cm: 19.0 };

export const PLYO_GUIDE: Record<string, string> = {
  'Box Jump': 'Two-foot jump onto a box, land soft in a quarter squat, STEP down. Log the box height (floor to top of box).',
  'Broad Jump': 'Standing two-foot jump forward, stick the landing. Measure toe line to the back of the nearest heel.',
  'Vertical Jump': 'Stand side-on to a wall, reach up and mark it; jump and touch as high as you can. Log jump mark minus standing reach.',
  'Depth Jump': 'Step off a low box (12-18 in / 30-45 cm), land and rebound straight up as fast as possible. Log the drop-box height.',
  'Hurdle Hop': 'Continuous two-foot hops over a row of 4-6 low hurdles or cones, minimal ground contact. Log the hurdle height.',
  'Lateral Bound': 'Single-leg bound sideways, stick the landing on the other leg, then back. Log distance (each side counts as a rep).',
  'Plyo Push-up': 'Explosive push-up so the hands leave the floor. Log reps (distance/height = 1).',
  'Seated Box Jump': 'Sit on a box, feet flat, then jump from seated onto a second box. Log the landing-box height.',
  'Med Ball Chest Pass': 'Kneeling or standing chest pass for distance with a 6-10 lb / 3-5 kg ball. Log the distance.',
};

export type JumpTarget = [level: string, description: string, target: number | null];

/** [level, description, target] for a jump with standards (in the same unit as height). */
export function jumpTargets(exercise: string, height: number | null, unit = 'in'): JumpTarget[] {
  return (JUMP_STANDARDS[exercise] ?? []).map(([level, desc, rule]) => {
    const value = rule[0] === 'abs' ? (unit === 'in' ? rule[1] : rule[2]) : height ? pyRoundTo(height * rule[1], 1) : null;
    return [level, desc, value];
  });
}

export function jumpLevel(exercise: string, best: number | null, height: number | null, unit = 'in'): string {
  if (!best) return 'Not tested';
  let level = 'Below beginner';
  for (const [name, , target] of jumpTargets(exercise, height, unit)) {
    if (target === null) return 'Enter your height';
    if (best >= target) level = name;
  }
  return level;
}

export function boxJumpTargets(height: number, unit = 'in'): [string, string, number][] {
  return jumpTargets('Box Jump', height, unit).map(([l, d, t]) => [l, d, t ?? 0]);
}
