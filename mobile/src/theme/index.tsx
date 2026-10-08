// The RuskiMaxxing look: the Byzantine palette (imperial purple, gold, crimson on parchment and ivory),
// Cinzel for display type and Archivo for body text. Shared with the Orthodox Barbell Club app.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useColorScheme } from 'react-native';
import { getJson, KEYS, setJson } from '../lib/storage';

export const BYZ = {
  purple: '#4A1942',
  purpleDark: '#2E0C28',
  gold: '#C9A227',
  goldLight: '#F2D675',
  crimson: '#8B1A1A',
  ivory: '#F6EFDE',
  parchment: '#EDE3CF',
  ink: '#2B1B24',
  field: '#FFF8E1',
  oxblood: '#7A1F2B',
  gilt: '#9A7424',
  teal: '#1F6F5C',
  slate: '#5A5A5A',
};

export const fonts = {
  display: 'Cinzel_700Bold',
  displayRegular: 'Cinzel_400Regular',
  body: 'Archivo_400Regular',
  bodySemi: 'Archivo_600SemiBold',
  bodyBold: 'Archivo_700Bold',
};

const light = {
  scheme: 'light' as 'light' | 'dark',
  bg: BYZ.parchment,
  card: BYZ.ivory,
  field: BYZ.field,
  text: BYZ.ink,
  muted: '#6E5A66',
  header: BYZ.purple,
  headerText: BYZ.goldLight,
  border: BYZ.gold,
  borderSoft: '#D9C9A3',
  accent: BYZ.purple,
  onAccent: BYZ.goldLight,
  gold: BYZ.gold,
  danger: BYZ.crimson,
  success: BYZ.teal,
  tabBar: BYZ.purpleDark,
  tabActive: BYZ.goldLight,
  tabInactive: '#B9A2B3',
  chartLine: BYZ.purple,
  chartFill: 'rgba(74,25,66,0.10)',
  chartGrid: '#D9C9A3',
  kinds: {
    main: BYZ.purple,
    variation: BYZ.gilt,
    accessory: BYZ.slate,
    plyo: BYZ.teal,
    test: BYZ.crimson,
    strongman: BYZ.oxblood,
  } as Record<string, string>,
};

export type Colors = typeof light;

const dark: Colors = {
  scheme: 'dark',
  bg: '#170613',
  card: '#2A0F25',
  field: '#3A1734',
  text: BYZ.ivory,
  muted: '#C4B1A6',
  header: BYZ.purpleDark,
  headerText: BYZ.goldLight,
  border: BYZ.gilt,
  borderSoft: '#4A2A42',
  accent: BYZ.gold,
  onAccent: BYZ.purpleDark,
  gold: BYZ.gold,
  danger: '#E0605A',
  success: '#4FB89A',
  tabBar: '#120410',
  tabActive: BYZ.goldLight,
  tabInactive: '#8E7486',
  chartLine: BYZ.goldLight,
  chartFill: 'rgba(242,214,117,0.12)',
  chartGrid: '#4A2A42',
  kinds: {
    main: '#B07BA6',
    variation: BYZ.gold,
    accessory: '#9C9C9C',
    plyo: '#4FB89A',
    test: '#E0605A',
    strongman: '#D2687A',
  },
};

export type ThemePref = 'system' | 'light' | 'dark';

interface ThemeValue {
  c: Colors;
  pref: ThemePref;
  setPref: (p: ThemePref) => void;
}

const ThemeContext = createContext<ThemeValue>({ c: light, pref: 'system', setPref: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const system = useColorScheme();
  const [pref, setPrefState] = useState<ThemePref>('system');
  useEffect(() => {
    getJson<ThemePref>(KEYS.theme).then((p) => p && setPrefState(p));
  }, []);
  const value = useMemo<ThemeValue>(() => {
    const scheme = pref === 'system' ? (system === 'dark' ? 'dark' : 'light') : pref;
    return {
      c: scheme === 'dark' ? dark : light,
      pref,
      setPref: (p) => {
        setPrefState(p);
        setJson(KEYS.theme, p);
      },
    };
  }, [pref, system]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);
