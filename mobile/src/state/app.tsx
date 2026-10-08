// The app's data: the local store (training log + settings), the cloud client, and the derived settings.
// Every screen reads it with useApp(); any change to the store re-renders them.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Alert, AppState } from 'react-native';
import { today, daysBetween } from '../core/dates';
import { WEEKS } from '../core/program';
import { Store } from '../core/store';
import { Cloud, CloudError } from '../core/sync';
import { settingsFrom, type Settings } from '../core/workout';
import { storePersistence, tokenVault } from '../lib/storage';

interface AppValue {
  store: Store;
  cloud: Cloud;
  cfg: Settings;
  /** true once the lifter has saved their intake (start date) */
  setUp: boolean;
  /** program week for today (0-52) */
  currentWeek: number;
  rev: number;
  refresh: () => void;
  /** Back up to the cloud in the background if signed in; errors wait for the next save. */
  backupQuietly: () => void;
}

const Ctx = createContext<AppValue | null>(null);

export function useApp(): AppValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useApp outside AppProvider');
  return v;
}

export function currentWeekFor(start: string, on = today()): number {
  return Math.max(0, Math.min(WEEKS, Math.floor(daysBetween(start, on) / 7) + 1));
}

export function AppProvider({ children, onReady }: { children: ReactNode; onReady?: () => void }) {
  const [core, setCore] = useState<{ store: Store; cloud: Cloud } | null>(null);
  const [rev, setRev] = useState(0);
  const refresh = useCallback(() => setRev((r) => r + 1), []);

  useEffect(() => {
    let unsub = () => {};
    (async () => {
      const store = await Store.open(storePersistence);
      const cloud = new Cloud(store, tokenVault);
      await cloud.init();
      unsub = store.subscribe(refresh);
      setCore({ store, cloud });
      onReady?.();
    })();
    return () => unsub();
  }, [refresh, onReady]);

  useSignInWatcher(core?.cloud ?? null, refresh);

  const value = useMemo<AppValue | null>(() => {
    if (!core) return null;
    const cfg = settingsFrom(core.store);
    return {
      ...core,
      cfg,
      setUp: !!core.store.get('start'),
      currentWeek: currentWeekFor(cfg.start),
      rev,
      refresh,
      backupQuietly: () => {
        if (core.cloud.loggedIn) core.cloud.sync().then(refresh, refresh);
      },
    };
    // rev is the store's change counter
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [core, rev, refresh]);

  return value ? <Ctx.Provider value={value}>{children}</Ctx.Provider> : null;
}

/** While a browser sign-in is waiting, check every couple of seconds (and when the app comes back to the front). */
function useSignInWatcher(cloud: Cloud | null, refresh: () => void) {
  const busy = useRef(false);
  useEffect(() => {
    if (!cloud) return;
    const tick = async () => {
      if (busy.current || !cloud.pendingCode) return;
      busy.current = true;
      try {
        if (await cloud.pollSignIn()) {
          refresh();
          try {
            const [sent, received] = await cloud.sync();
            Alert.alert('Cloud backup', `Signed in as ${cloud.email}. Restored ${received} records, backed up ${sent}.`);
          } catch (e) {
            Alert.alert('Cloud backup', e instanceof Error ? e.message : String(e));
          }
          refresh();
        }
      } catch (e) {
        if (e instanceof CloudError && !cloud.pendingCode) {
          refresh();
          Alert.alert('Cloud backup', e.message);
        }
      } finally {
        busy.current = false;
      }
    };
    const id = setInterval(tick, 2000);
    const sub = AppState.addEventListener('change', (s) => s === 'active' && tick());
    return () => {
      clearInterval(id);
      sub.remove();
    };
  }, [cloud, refresh]);
}
