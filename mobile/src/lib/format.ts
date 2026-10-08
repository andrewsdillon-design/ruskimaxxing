// Display helpers.

/** 1 decimal at most, no trailing ".0": 182.5 -> "182.5", 180 -> "180". */
export function fmtNum(x: number): string {
  const r = Math.round(x * 10) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}

/** "1 set" / "3 sets". */
export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** A readable message from anything thrown. */
export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * Group a save's PR lines per exercise and merge rep maxes at the same weight:
 * ["Squat: Estimated 1RM 282", "Squat: 3RM 235", "Squat: 4RM 235"] -> ["Squat: e1RM 282 · 3-4RM 235"].
 */
export function groupPrs(prs: string[]): string[] {
  const byExercise = new Map<string, { e1rm?: string; best?: string; rms: [number, string][] }>();
  for (const line of prs) {
    const cut = line.indexOf(': ');
    const ex = line.slice(0, cut);
    const what = line.slice(cut + 2);
    const g = byExercise.get(ex) ?? { rms: [] };
    const rm = /^(\d+)RM (.+)$/.exec(what);
    if (rm) g.rms.push([Number(rm[1]), rm[2]]);
    else if (what.startsWith('Estimated 1RM ')) g.e1rm = what.slice('Estimated 1RM '.length);
    else g.best = what;
    byExercise.set(ex, g);
  }
  return [...byExercise].map(([ex, g]) => {
    const parts: string[] = [];
    if (g.best) parts.push(g.best);
    if (g.e1rm) parts.push(`e1RM ${g.e1rm}`);
    const rms = [...g.rms].sort((a, b) => a[0] - b[0]);
    for (let i = 0; i < rms.length; ) {
      let j = i;
      while (j + 1 < rms.length && rms[j + 1][1] === rms[i][1]) j++;
      parts.push(`${rms[i][0]}${j > i ? `-${rms[j][0]}` : ''}RM ${rms[i][1]}`);
      i = j + 1;
    }
    return `${ex}: ${parts.join(' · ')}`;
  });
}
