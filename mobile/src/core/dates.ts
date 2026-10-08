// Calendar dates as ISO "YYYY-MM-DD" strings (they sort and compare correctly as text). All arithmetic is done
// in UTC so daylight-saving changes never shift a day.

const pad = (n: number) => String(n).padStart(2, '0');

export function toUtc(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(Date.UTC(y, (m || 1) - 1, d || 1));
}

export function fromUtc(d: Date): string {
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

export function addDays(iso: string, days: number): string {
  const d = toUtc(iso);
  d.setUTCDate(d.getUTCDate() + days);
  return fromUtc(d);
}

export const addWeeks = (iso: string, weeks: number) => addDays(iso, weeks * 7);

/** Today in the phone's own calendar. */
export function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Monday = 0 ... Sunday = 6, like Python's date.weekday(). */
export function weekday(iso: string): number {
  return (toUtc(iso).getUTCDay() + 6) % 7;
}

/** Python's next_monday(): the next Monday after today (a week ahead if today is Monday). */
export function nextMonday(from: string = today()): string {
  return addDays(from, (7 - weekday(from)) % 7 || 7);
}

export function isValidIso(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(s) && fromUtc(toUtc(s)) === s;
}

export function daysBetween(a: string, b: string): number {
  return Math.round((toUtc(b).getTime() - toUtc(a).getTime()) / 86400000);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** "Jan 05" (Python's %b %d). */
export const fmtMonDay = (iso: string) => `${MONTHS[toUtc(iso).getUTCMonth()]} ${pad(toUtc(iso).getUTCDate())}`;
/** "Mon Jan 05". */
export const fmtDayMonDay = (iso: string) => `${DAYS[weekday(iso)]} ${fmtMonDay(iso)}`;
/** "Jan 5, 2026" for headings. */
export function fmtLong(iso: string): string {
  const d = toUtc(iso);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
}
/** "Jan 5" for chart axes. */
export function fmtShort(iso: string): string {
  const d = toUtc(iso);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}
