// Where things live on the phone: the cloud sign-in token in the keychain (expo-secure-store), everything
// else (the training log, settings, preferences) in AsyncStorage.
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import type { Persistence } from '../core/store';
import type { TokenVault } from '../core/sync';

const TOKEN_KEY = 'ruskimaxxing.cloudToken';
const web = Platform.OS === 'web'; // the web preview has no keychain

export const KEYS = {
  store: 'ruskimaxxing.store.v1',
  theme: 'ruskimaxxing.theme',
};

export const tokenVault: TokenVault = {
  async get() {
    try {
      return web ? (globalThis.localStorage?.getItem(TOKEN_KEY) ?? null) : await SecureStore.getItemAsync(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  async set(token) {
    if (web) {
      if (token) globalThis.localStorage?.setItem(TOKEN_KEY, token);
      else globalThis.localStorage?.removeItem(TOKEN_KEY);
    } else if (token) await SecureStore.setItemAsync(TOKEN_KEY, token);
    else await SecureStore.deleteItemAsync(TOKEN_KEY);
  },
};

export const storePersistence: Persistence = {
  load: () => AsyncStorage.getItem(KEYS.store),
  save: (json) => AsyncStorage.setItem(KEYS.store, json),
};

export async function getJson<T>(key: string): Promise<T | null> {
  try {
    const raw = await AsyncStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export async function setJson(key: string, value: unknown): Promise<void> {
  if (value === null || value === undefined) await AsyncStorage.removeItem(key);
  else await AsyncStorage.setItem(key, JSON.stringify(value));
}
