// Python's rounding and number formatting, reproduced exactly, so weights and labels match the Python apps
// (desktop, spreadsheet) to the last digit. Checked against the Python output by src/core/__tests__.

/** Python's round(x): halves go to the even neighbour (round(2.5) == 2, round(3.5) == 4). */
export function pyRound(x: number): number {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : r;
}

/** Python's round(x, n). */
export function pyRoundTo(x: number, n: number): number {
  const m = 10 ** n;
  return pyRound(x * m) / m;
}

function stripZeros(s: string): string {
  return s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s;
}

/** Python's f"{x:g}": up to 6 significant digits, no trailing zeros ("185", "62.5", "1e+06"). */
export function fmtG(x: number): string {
  if (x === 0) return Object.is(x, -0) ? '-0' : '0';
  if (!Number.isFinite(x)) return Number.isNaN(x) ? 'nan' : x > 0 ? 'inf' : '-inf';
  const [mant, expText] = x.toExponential(5).split('e');
  const exp = Number(expText);
  if (exp < -4 || exp >= 6) {
    const sign = exp < 0 ? '-' : '+';
    return `${stripZeros(mant)}e${sign}${String(Math.abs(exp)).padStart(2, '0')}`;
  }
  return stripZeros(x.toFixed(5 - exp));
}

/** Python's f"{x:.0f}" (halves to even): 262.5 -> "262". */
export function fmt0(x: number): string {
  const r = pyRound(x);
  return String(r === 0 ? 0 : r);
}

/** Python's int(float): truncates toward zero. */
export const pyInt = (x: number): number => Math.trunc(x);
