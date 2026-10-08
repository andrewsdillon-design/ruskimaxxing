// Local storage for settings, the lift log and body measurements (port of src/ruskimaxxing/storage.py).
// Every record has a stable uid and an `updated` timestamp, and deletions leave a tombstone, so cloud backup
// sends only what changed and resolves edits from two devices by keeping the newest. The records sent to
// the server use the same field names as the desktop app's, so both can share one account.
//
// The whole store is one JSON document saved through a Persistence (AsyncStorage in the app, memory in tests).
import type { BodyFat, BodyWeight, EntryKind, LogEntry } from './tracking';

export const SYNCED_SETTINGS = ['name', 'units', 'increment', 'start', 'height', 'bodyweight_start', 'bodyfat_start', 'bodyfat_method', 'age', 'sex'];

export interface Persistence {
  load(): Promise<string | null>;
  save(json: string): Promise<void>;
}

export const memoryPersistence = (initial: string | null = null): Persistence & { data: string | null } => {
  const p = {
    data: initial,
    load: async () => p.data,
    save: async (json: string) => {
      p.data = json;
    },
  };
  return p;
};

/** A cloud record: {uid, kind, updated, deleted, data} with the desktop app's field names in data. */
export interface ChangeRecord {
  uid: string;
  kind: 'lift' | 'bodyweight' | 'bodyfat' | 'setting';
  updated: string;
  deleted: boolean;
  data: Record<string, unknown> | null;
}

interface LiftRow {
  id: number;
  uid: string;
  updated: string;
  date: string;
  exercise: string;
  weight: number;
  reps: number;
  kind: EntryKind;
  note: string;
  week: number | null;
  day: number | null;
  set_no: number | null;
  rpe: number | null;
  done: boolean;
}

interface Doc {
  version: 1;
  nextId: number;
  settings: Record<string, { value: string; updated: string }>;
  lifts: LiftRow[];
  bodyweight: Record<string, BodyWeight & { updated: string }>;
  bodyfat: Record<string, BodyFat & { updated: string }>;
  tombstones: Record<string, { kind: string; updated: string }>;
}

const emptyDoc = (): Doc => ({ version: 1, nextId: 1, settings: {}, lifts: [], bodyweight: {}, bodyfat: {}, tombstones: {} });

/** UTC timestamp in the desktop app's format (microseconds), so timestamps from both compare as text. */
export function now(): string {
  return new Date().toISOString().replace(/\.(\d{3})Z$/, '.$1000Z');
}

export const setUid = (week: number, day: number, exercise: string, setNo: number) => `set:${week}:${day}:${exercise}:${setNo}`;

function randomUid(): string {
  let s = '';
  for (let i = 0; i < 32; i++) s += Math.floor(Math.random() * 16).toString(16);
  return s;
}

const toEntry = (r: LiftRow): LogEntry => ({
  date: r.date, exercise: r.exercise, weight: r.weight, reps: r.reps, kind: r.kind, note: r.note, id: r.id,
  week: r.week, day: r.day, setNo: r.set_no, rpe: r.rpe, done: r.done,
});

export class Store {
  private doc: Doc;
  private persistence: Persistence;
  private saving: Promise<void> = Promise.resolve();
  private listeners = new Set<() => void>();
  /** Bumps on every change; screens re-render on it. */
  revision = 0;

  private constructor(doc: Doc, persistence: Persistence) {
    this.doc = doc;
    this.persistence = persistence;
  }

  static async open(persistence: Persistence): Promise<Store> {
    let doc = emptyDoc();
    try {
      const raw = await persistence.load();
      if (raw) doc = { ...emptyDoc(), ...(JSON.parse(raw) as Doc) };
    } catch {
      // unreadable data: start fresh rather than crash (the cloud backup can restore it)
    }
    return new Store(doc, persistence);
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** Saves are queued in order; await this to know everything is on disk. */
  flush(): Promise<void> {
    return this.saving;
  }

  private changed(): void {
    this.revision++;
    const json = JSON.stringify(this.doc);
    this.saving = this.saving.then(() => this.persistence.save(json)).catch(() => {});
    this.listeners.forEach((fn) => fn());
  }

  private tombstone(uid: string, kind: string, stamp?: string) {
    this.doc.tombstones[uid] = { kind, updated: stamp ?? now() };
  }

  private clearTombstone(uid: string) {
    delete this.doc.tombstones[uid];
  }

  // ----- settings -------------------------------------------------------------------
  get(key: string): string | undefined;
  get(key: string, fallback: string): string;
  get(key: string, fallback?: string): string | undefined {
    return this.doc.settings[key]?.value ?? fallback;
  }

  set(key: string, value: unknown, stamp?: string): void {
    const text = String(value);
    if (this.get(key) === text && stamp === undefined) return; // unchanged: not a new edit
    this.doc.settings[key] = { value: text, updated: stamp ?? now() };
    this.changed();
  }

  /** Several settings in one save. */
  setMany(values: Record<string, unknown>): void {
    let any = false;
    for (const [key, value] of Object.entries(values)) {
      const text = String(value);
      if (this.get(key) === text) continue;
      this.doc.settings[key] = { value: text, updated: now() };
      any = true;
    }
    if (any) this.changed();
  }

  // ----- lifts ----------------------------------------------------------------------
  private insert(e: LogEntry, uid?: string, stamp?: string): LogEntry {
    const id = uid ?? (e.week !== null && e.day !== null && e.setNo ? setUid(e.week, e.day, e.exercise, e.setNo) : randomUid());
    this.doc.lifts = this.doc.lifts.filter((r) => r.uid !== id);
    this.clearTombstone(id);
    const row: LiftRow = {
      id: this.doc.nextId++, uid: id, updated: stamp ?? now(), date: e.date, exercise: e.exercise, weight: e.weight,
      reps: e.reps, kind: e.kind, note: e.note, week: e.week, day: e.day, set_no: e.setNo, rpe: e.rpe, done: e.done,
    };
    this.doc.lifts.push(row);
    return toEntry(row);
  }

  addLift(e: LogEntry): LogEntry {
    const saved = this.insert(e);
    this.changed();
    return saved;
  }

  deleteLift(id: number): void {
    const row = this.doc.lifts.find((r) => r.id === id);
    this.doc.lifts = this.doc.lifts.filter((r) => r.id !== id);
    if (row?.uid) this.tombstone(row.uid, 'lift');
    this.changed();
  }

  /** Every set, ordered by date then the order they were saved (like the desktop app's SQL). */
  lifts(): LogEntry[] {
    return [...this.doc.lifts].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.id - b.id)).map(toEntry);
  }

  /** Every set saved for one program session, done or not. */
  workout(week: number, day: number): LogEntry[] {
    return this.lifts().filter((e) => e.week === week && e.day === day);
  }

  /** Replace everything saved for one session with `entries`. */
  saveWorkout(week: number, day: number, entries: LogEntry[]): LogEntry[] {
    const old = new Set(this.doc.lifts.filter((r) => r.week === week && r.day === day).map((r) => r.uid));
    this.doc.lifts = this.doc.lifts.filter((r) => !(r.week === week && r.day === day));
    const saved = entries.map((e) => this.insert({ ...e, week, day }));
    const fresh = new Set(saved.map((e) => setUid(week, day, e.exercise, e.setNo ?? 0)));
    for (const uid of old) if (uid && !fresh.has(uid)) this.tombstone(uid, 'lift');
    this.changed();
    return saved;
  }

  // ----- body: bodyweight once per program week, body fat once per month ---------------
  setBodyweight(bw: BodyWeight, stamp?: string): void {
    this.doc.bodyweight[bw.week] = { ...bw, updated: stamp ?? now() };
    this.clearTombstone(`bw:${bw.week}`);
    this.changed();
  }

  deleteBodyweight(week: number): void {
    if (this.doc.bodyweight[week]) {
      delete this.doc.bodyweight[week];
      this.tombstone(`bw:${week}`, 'bodyweight');
      this.changed();
    }
  }

  bodyweights(): BodyWeight[] {
    return Object.values(this.doc.bodyweight)
      .sort((a, b) => a.week - b.week)
      .map(({ week, date, weight }) => ({ week, date, weight }));
  }

  setBodyfat(bf: BodyFat, stamp?: string): void {
    this.doc.bodyfat[bf.month] = { ...bf, updated: stamp ?? now() };
    this.clearTombstone(`bf:${bf.month}`);
    this.changed();
  }

  deleteBodyfat(month: number): void {
    if (this.doc.bodyfat[month]) {
      delete this.doc.bodyfat[month];
      this.tombstone(`bf:${month}`, 'bodyfat');
      this.changed();
    }
  }

  bodyfats(): BodyFat[] {
    return Object.values(this.doc.bodyfat)
      .sort((a, b) => a.month - b.month)
      .map(({ month, date, percent, method, weight }) => ({ month, date, percent, method, weight }));
  }

  // ----- cloud sync -------------------------------------------------------------------
  /** Records changed after `since` (all when null). */
  changes(since: string | null = null): ChangeRecord[] {
    const after = since ?? '';
    const out: ChangeRecord[] = [];
    for (const r of [...this.doc.lifts].sort((a, b) => a.id - b.id)) {
      if (r.updated > after) {
        const { date, exercise, weight, reps, kind, note, week, day, set_no, rpe, done } = r;
        out.push({ uid: r.uid, kind: 'lift', updated: r.updated, deleted: false,
          data: { date, exercise, weight, reps, kind, note, week, day, set_no, rpe, done } });
      }
    }
    for (const b of Object.values(this.doc.bodyweight))
      if (b.updated > after)
        out.push({ uid: `bw:${b.week}`, kind: 'bodyweight', updated: b.updated, deleted: false, data: { week: b.week, date: b.date, weight: b.weight } });
    for (const f of Object.values(this.doc.bodyfat))
      if (f.updated > after)
        out.push({ uid: `bf:${f.month}`, kind: 'bodyfat', updated: f.updated, deleted: false,
          data: { month: f.month, date: f.date, percent: f.percent, method: f.method, weight: f.weight } });
    for (const [key, s] of Object.entries(this.doc.settings))
      if (s.updated > after && SYNCED_SETTINGS.includes(key))
        out.push({ uid: `setting:${key}`, kind: 'setting', updated: s.updated, deleted: false, data: { key, value: s.value } });
    for (const [uid, t] of Object.entries(this.doc.tombstones))
      if (t.updated > after) out.push({ uid, kind: t.kind as ChangeRecord['kind'], updated: t.updated, deleted: true, data: null });
    return out;
  }

  private localUpdated(uid: string, kind: string): string {
    const stamps: (string | undefined)[] = [this.doc.tombstones[uid]?.updated];
    if (kind === 'lift') stamps.push(this.doc.lifts.find((r) => r.uid === uid)?.updated);
    else if (kind === 'bodyweight') stamps.push(this.doc.bodyweight[Number(uid.slice(3))]?.updated);
    else if (kind === 'bodyfat') stamps.push(this.doc.bodyfat[Number(uid.slice(3))]?.updated);
    else stamps.push(this.doc.settings[uid.slice(8)]?.updated);
    return stamps.reduce<string>((m, s) => (s && s > m ? s : m), '');
  }

  /** Apply records from the cloud where they're newer than ours. Returns how many changed. */
  apply(records: ChangeRecord[]): number {
    let applied = 0;
    for (const rec of records) {
      const { uid, kind, updated: stamp } = rec;
      if (stamp <= this.localUpdated(uid, kind)) continue;
      const data = (rec.data ?? {}) as Record<string, any>;
      if (rec.deleted) {
        if (kind === 'lift') this.doc.lifts = this.doc.lifts.filter((r) => r.uid !== uid);
        else if (kind === 'bodyweight') delete this.doc.bodyweight[Number(uid.slice(3))];
        else if (kind === 'bodyfat') delete this.doc.bodyfat[Number(uid.slice(3))];
        this.tombstone(uid, kind, stamp);
      } else if (kind === 'lift') {
        this.insert({
          date: data.date, exercise: data.exercise, weight: data.weight, reps: data.reps, kind: data.kind, note: data.note ?? '',
          id: null, week: data.week, day: data.day, setNo: data.set_no, rpe: data.rpe, done: !!data.done,
        }, uid, stamp);
      } else if (kind === 'bodyweight') {
        this.doc.bodyweight[data.week] = { week: data.week, date: data.date, weight: data.weight, updated: stamp };
        this.clearTombstone(uid);
      } else if (kind === 'bodyfat') {
        this.doc.bodyfat[data.month] = { month: data.month, date: data.date, percent: data.percent, method: data.method, weight: data.weight, updated: stamp };
        this.clearTombstone(uid);
      } else if (kind === 'setting' && SYNCED_SETTINGS.includes(data.key)) {
        this.doc.settings[data.key] = { value: String(data.value), updated: stamp };
      }
      applied++;
    }
    if (applied) this.changed();
    return applied;
  }

  /** Forget everything on this phone (Setup -> Start over). */
  reset(): void {
    this.doc = emptyDoc();
    this.changed();
  }
}
