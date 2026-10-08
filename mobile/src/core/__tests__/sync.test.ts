// Store change tracking and the cloud client, against a fake server that behaves like server/ruskimaxxing_cloud.
import { memoryPersistence, Store, type ChangeRecord } from '../store';
import { Cloud, CloudError, memoryVault, type Transport } from '../sync';
import { entry } from '../tracking';

async function newStore() {
  return Store.open(memoryPersistence());
}

test('changes and tombstones round-trip between two phones', async () => {
  const a = await newStore();
  const b = await newStore();
  a.set('units', 'kg');
  a.set('cloud_email', 'local@only'); // never synced
  const squat = a.addLift(entry({ date: '2026-01-05', exercise: 'Squat', weight: 100, reps: 5 }));
  a.setBodyweight({ week: 1, date: '2026-01-05', weight: 80 });
  a.setBodyfat({ month: 1, date: '2026-01-05', percent: 15, method: 'InBody', weight: 80 });
  expect(b.apply(a.changes())).toBe(4);
  expect(b.get('units')).toBe('kg');
  expect(b.get('cloud_email')).toBeUndefined();
  expect(b.lifts().map((e) => [e.exercise, e.weight])).toEqual([['Squat', 100]]);
  expect(b.bodyfats()[0].percent).toBe(15);

  const since = a.changes().reduce((m, r) => (r.updated > m ? r.updated : m), '');
  await new Promise((r) => setTimeout(r, 2));
  a.deleteLift(squat.id as number);
  a.deleteBodyweight(1);
  const delta = a.changes(since);
  expect(delta.map((r) => [r.kind, r.deleted])).toEqual([['lift', true], ['bodyweight', true]]);
  b.apply(delta);
  expect(b.lifts()).toEqual([]);
  expect(b.bodyweights()).toEqual([]);
  // an older edit never overwrites a newer one
  expect(b.apply(a.changes().map((r) => ({ ...r, updated: '2000-01-01T00:00:00.000000Z' })))).toBe(0);
});

test('records use the desktop app field names', async () => {
  const s = await newStore();
  s.saveWorkout(1, 0, [entry({ date: '2026-01-05', exercise: 'Squat', weight: 185, reps: 6, setNo: 1, rpe: 8 })]);
  const [rec] = s.changes();
  expect(rec.uid).toBe('set:1:0:Squat:1');
  expect(rec.data).toEqual({ date: '2026-01-05', exercise: 'Squat', weight: 185, reps: 6, kind: 'training', note: '',
    week: 1, day: 0, set_no: 1, rpe: 8, done: true });
  expect(rec.updated).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/);
});

test('re-saving a session with fewer sets tombstones the removed ones', async () => {
  const s = await newStore();
  const set = (n: number) => entry({ date: '2026-01-05', exercise: 'Squat', weight: 185, reps: 6, setNo: n });
  s.saveWorkout(1, 0, [set(1), set(2), set(3)]);
  s.saveWorkout(1, 0, [set(1)]);
  expect(s.workout(1, 0)).toHaveLength(1);
  expect(s.changes().filter((r) => r.deleted).map((r) => r.uid).sort()).toEqual(['set:1:0:Squat:2', 'set:1:0:Squat:3']);
});

test('the store survives a restart', async () => {
  const disk = memoryPersistence();
  const s = await Store.open(disk);
  s.set('start', '2026-01-05');
  s.addLift(entry({ date: '2026-01-05', exercise: 'Bench Press', weight: 155, reps: 6 }));
  await s.flush();
  const again = await Store.open(disk);
  expect(again.get('start')).toBe('2026-01-05');
  expect(again.lifts()[0].exercise).toBe('Bench Press');
});

/** A tiny in-memory RuskiMaxxing Cloud. */
function fakeServer(opts: { active?: boolean } = {}) {
  const records: (ChangeRecord & { seq: number })[] = [];
  let seq = 0;
  let linked = false;
  const calls: string[] = [];
  const transport: Transport = async (method, url, body: any, token) => {
    const path = url.replace(/^https?:\/\/[^/]+/, '');
    calls.push(`${method} ${path}`);
    if (path === '/api/link/start') return [200, { device_code: 'dev', code: 'ABCD-EFGH', url: 'https://x/link?code=ABCDEFGH&app=1', interval: 2, expires_in: 900 }];
    if (path === '/api/link/poll') return linked ? [200, { token: 'tok', email: 'me@x.com' }] : [202, { pending: true }];
    if (token !== 'tok') return [401, { detail: 'Please log in again' }];
    if (path === '/api/sync') {
      if (body.changes.length && opts.active === false) return [402, { detail: "Cloud backup isn't active for this account." }];
      for (const c of body.changes) records.push({ ...c, seq: ++seq });
      return [200, { changes: records.filter((r) => r.seq > body.since), seq, plan: { active: opts.active !== false } }];
    }
    if (path === '/api/account' && method === 'DELETE') return body.password === 'pw' ? [200, { deleted: true }] : [401, { detail: 'Wrong password' }];
    if (path === '/api/logout') return [200, {}];
    return [404, {}];
  };
  return { transport, calls, records, link: () => void (linked = true) };
}

test('browser sign-in, then sync both ways', async () => {
  const server = fakeServer();
  const phone = await newStore();
  const vault = memoryVault();
  const cloud = new Cloud(phone, vault, server.transport);
  await cloud.init();
  const link = await cloud.startBrowserSignIn();
  expect(link.url).toContain('app=1');
  expect(cloud.status()).toMatch(/Finish on the website/);
  expect(await cloud.pollSignIn()).toBe(false);
  server.link();
  expect(await cloud.pollSignIn()).toBe(true);
  expect(cloud.email).toBe('me@x.com');
  expect(await vault.get()).toBe('tok');

  phone.addLift(entry({ date: '2026-01-05', exercise: 'Squat', weight: 200, reps: 5 }));
  const [sent] = await cloud.sync();
  expect(sent).toBe(1);
  expect(cloud.status()).toMatch(/last backup/);

  // a second phone signs in and restores it
  const other = await newStore();
  const vault2 = memoryVault();
  await vault2.set('tok');
  const cloud2 = new Cloud(other, vault2, server.transport);
  await cloud2.init();
  const [, received] = await cloud2.sync();
  expect(received).toBe(1);
  expect(other.lifts()[0].weight).toBe(200);
  expect(cloud.page('/privacy')).toBe('https://api.ruskimaxxing.com/privacy?app=1');
});

test('inactive backups still restore, and say so', async () => {
  const server = fakeServer({ active: false });
  const phone = await newStore();
  const vault = memoryVault();
  await vault.set('tok');
  const cloud = new Cloud(phone, vault, server.transport);
  await cloud.init();
  phone.addLift(entry({ date: '2026-01-05', exercise: 'Squat', weight: 200, reps: 5 }));
  await expect(cloud.sync()).rejects.toMatchObject({ code: 402 });
  expect(cloud.status()).toMatch(/backups aren't active/);
});

test('deleting the account signs out; a wrong password keeps you signed in', async () => {
  const server = fakeServer();
  const phone = await newStore();
  const vault = memoryVault();
  await vault.set('tok');
  const cloud = new Cloud(phone, vault, server.transport);
  await cloud.init();
  await expect(cloud.deleteAccount('nope')).rejects.toBeInstanceOf(CloudError);
  await cloud.deleteAccount('pw');
  expect(cloud.loggedIn).toBe(false);
  expect(await vault.get()).toBeNull();
});
