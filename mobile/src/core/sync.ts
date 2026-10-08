// RuskiMaxxing Cloud backup client (port of src/ruskimaxxing/sync.py).
//
//   const link = await cloud.startBrowserSignIn();  // open link.url; the person signs in / signs up there
//   while (!(await cloud.pollSignIn())) wait(link.interval);
//   await cloud.sync();                             // push local changes, pull other devices' changes
//
// Login state lives in the local (never synced) settings: cloud_email, cloud_seq (last server change pulled),
// cloud_pushed (when the last successful push started). The token itself goes in a TokenVault (the phone's
// keychain in the app).
import type { ChangeRecord, Store } from './store';
import { now } from './store';

export const DEFAULT_SERVER = 'https://api.ruskimaxxing.com';
const EDITION = 'standard';
const TIMEOUT_MS = 20000;

export class CloudError extends Error {
  constructor(message: string, public code = 0) {
    super(message);
  }
}

export type Transport = (method: string, url: string, body: unknown, token: string | null) => Promise<[number, any]>;

export interface TokenVault {
  get(): Promise<string | null>;
  set(token: string | null): Promise<void>;
}

export const memoryVault = (): TokenVault => {
  let token: string | null = null;
  return { get: async () => token, set: async (t) => void (token = t) };
};

export const fetchTransport: Transport = async (method, url, body, token) => {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const resp = await fetch(url, {
      method,
      signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined || body === null ? undefined : JSON.stringify(body),
    });
    let data: any = {};
    try {
      data = (await resp.json()) ?? {};
    } catch {
      data = {};
    }
    return [resp.status, data];
  } catch {
    throw new CloudError("Can't reach the server. Check your connection and try again.");
  } finally {
    clearTimeout(timer);
  }
};

export interface SignInLink {
  url: string;
  code: string;
  interval: number;
}

export class Cloud {
  private token: string | null = null;

  constructor(private store: Store, private vault: TokenVault = memoryVault(), private transport: Transport = fetchTransport) {}

  /** Load the saved token (call once at startup). */
  async init(): Promise<void> {
    this.token = await this.vault.get();
  }

  get url(): string {
    return (this.store.get('cloud_url', '') || DEFAULT_SERVER).replace(/\/+$/, '');
  }

  get loggedIn(): boolean {
    return !!this.token;
  }

  get email(): string {
    return this.loggedIn ? this.store.get('cloud_email', '') : '';
  }

  /** The sign-in in progress ('' if not waiting for the website). */
  get pendingCode(): string {
    if (!this.store.get('cloud_link_device', '')) return '';
    if (Date.now() / 1000 > Number(this.store.get('cloud_link_until', '0') || 0)) {
      this.cancelSignIn();
      return '';
    }
    return this.store.get('cloud_link_code', '');
  }

  /** The website page for the sign-in in progress. */
  get pendingUrl(): string {
    return this.store.get('cloud_link_url', '');
  }

  get backupActive(): boolean {
    return this.store.get('cloud_backup_active', '1') !== '0';
  }

  get lastSync(): string {
    return this.store.get('cloud_last_sync', '');
  }

  status(): string {
    if (!this.loggedIn) {
      if (this.pendingCode) return 'Finish on the website, then come back here - it connects by itself';
      return 'Not signed in - your data is only on this phone. Accounts are free.';
    }
    if (!this.backupActive) return `Signed in as ${this.email} - backups aren't active for this account (restore still works)`;
    const last = this.lastSync;
    return `Signed in as ${this.email}` + (last ? ` - last backup ${last.slice(0, 16).replace('T', ' ')} UTC` : '');
  }

  private async setToken(token: string | null) {
    this.token = token;
    await this.vault.set(token);
  }

  private async call(method: string, path: string, body?: unknown, auth = true): Promise<any> {
    const [code, data] = await this.transport(method, this.url + path, body ?? null, auth ? this.token : null);
    // 401 means the session ended - except DELETE /api/account's "Wrong password", which keeps you signed in
    if (code === 401 && auth && data?.detail !== 'Wrong password') await this.setToken(null);
    if (code >= 400) throw new CloudError(typeof data?.detail === 'string' ? data.detail : `Server error (${code})`, code);
    if (data?.plan && typeof data.plan === 'object') this.store.set('cloud_backup_active', data.plan.active ? '1' : '0');
    return data ?? {};
  }

  private async signedIn(data: { token: string; email: string }) {
    await this.setToken(data.token);
    this.store.setMany({ cloud_email: data.email, cloud_seq: '0', cloud_pushed: '' }); // pull everything once, push everything
  }

  /** Ask the server for a one-time sign-in link; open link.url in the browser. */
  async startBrowserSignIn(): Promise<SignInLink> {
    const data = await this.call('POST', '/api/link/start', { edition: EDITION, phone: true }, false);
    this.store.setMany({
      cloud_link_device: data.device_code,
      cloud_link_code: data.code,
      cloud_link_url: data.url,
      cloud_link_until: String(Date.now() / 1000 + Number(data.expires_in ?? 900)),
    });
    return { url: data.url, code: data.code, interval: Number(data.interval ?? 2) };
  }

  /** True once the person has finished signing in on the website (this phone is then signed in). */
  async pollSignIn(): Promise<boolean> {
    const device = this.store.get('cloud_link_device', '');
    if (!device || !this.pendingCode) throw new CloudError('Sign-in expired. Tap Sign in again.');
    let data: any;
    try {
      data = await this.call('POST', '/api/link/poll', { device_code: device }, false);
    } catch (e) {
      if (e instanceof CloudError && (e.code === 404 || e.code === 410)) this.cancelSignIn();
      throw e;
    }
    if (!data?.token) return false;
    this.cancelSignIn();
    await this.signedIn(data);
    return true;
  }

  cancelSignIn(): void {
    this.store.setMany({ cloud_link_device: '', cloud_link_code: '', cloud_link_url: '', cloud_link_until: '' });
  }

  /** A website page; ?app=1 tells the site the visitor came from the phone app (nothing to buy is shown). */
  page(path: string): string {
    return `${this.url}${path}${path.includes('?') ? '&' : '?'}app=1`;
  }

  async logout(): Promise<void> {
    try {
      await this.call('POST', '/api/logout');
    } catch {
      // offline: forget the token on this phone anyway
    }
    await this.setToken(null);
  }

  /** Delete the cloud account and every backup (the data on this phone stays). */
  async deleteAccount(password: string): Promise<void> {
    await this.call('DELETE', '/api/account', { password });
    await this.setToken(null);
    this.store.setMany({ cloud_email: '' });
  }

  /** Push local changes and pull remote ones. Returns [sent, received]. */
  async sync(): Promise<[number, number]> {
    if (!this.loggedIn) throw new CloudError('Sign in first');
    const started = now();
    const changes = this.store.changes(this.store.get('cloud_pushed', '') || null);
    const since = Number(this.store.get('cloud_seq', '0') || 0);
    let sent = 0;
    let inactive: CloudError | null = null;
    let data: { changes: ChangeRecord[]; seq: number } = { changes: [], seq: since };
    try {
      for (let i = 0; i < Math.max(changes.length, 1); i += 2000) {
        const chunk = changes.slice(i, i + 2000);
        data = await this.call('POST', '/api/sync', { edition: EDITION, since, changes: chunk });
        sent += chunk.length;
      }
    } catch (e) {
      if (!(e instanceof CloudError) || e.code !== 402) throw e;
      // backups aren't active for this account: still restore what's saved, keep local edits queued
      inactive = e;
      data = await this.call('POST', '/api/sync', { edition: EDITION, since, changes: [] });
    }
    const received = this.store.apply(data.changes ?? []);
    this.store.set('cloud_seq', String(data.seq));
    if (inactive) throw new CloudError(`${inactive.message} Received ${received} updates.`, 402);
    this.store.setMany({ cloud_pushed: started, cloud_last_sync: started });
    return [sent, received];
  }
}
