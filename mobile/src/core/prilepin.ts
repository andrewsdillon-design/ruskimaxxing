// Prilepin's chart: recommended reps per set and total reps by intensity zone (port of prilepin.py).
import { pyRound } from './pyfmt';

export interface Zone {
  low: number; // % of 1RM, inclusive
  high: number; // % of 1RM, exclusive (except the top zone)
  repsPerSet: [number, number];
  optimalTotal: number;
  totalRange: [number, number];
}

export const ZONES: Zone[] = [
  { low: 0, high: 70, repsPerSet: [3, 6], optimalTotal: 24, totalRange: [18, 30] },
  { low: 70, high: 80, repsPerSet: [3, 6], optimalTotal: 18, totalRange: [12, 24] },
  { low: 80, high: 90, repsPerSet: [2, 4], optimalTotal: 15, totalRange: [10, 20] },
  { low: 90, high: 100.01, repsPerSet: [1, 2], optimalTotal: 7, totalRange: [4, 10] },
];

export function zoneFor(percent: number): Zone {
  if (!(percent > 0 && percent <= 100)) throw new Error(`percent must be in (0, 100], got ${percent}`);
  const zone = ZONES.find((z) => z.low <= percent && percent < z.high);
  if (!zone) throw new Error('unreachable');
  return zone;
}

/** Working weight for a percentage of 1RM, rounded to the nearest plate increment. */
export function load(oneRepMax: number, percent: number, increment = 2.5): number {
  return pyRound((oneRepMax * percent) / 100 / increment) * increment;
}
