import { Archivo_400Regular, Archivo_600SemiBold, Archivo_700Bold } from '@expo-google-fonts/archivo';
import { Cinzel_400Regular, Cinzel_700Bold } from '@expo-google-fonts/cinzel';
import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, SplashScreen, Stack, ThemeProvider as NavThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useState } from 'react';
import { AppProvider } from '../state/app';
import { fonts, ThemeProvider, useTheme } from '../theme';

SplashScreen.preventAutoHideAsync().catch(() => {});

export default function RootLayout() {
  const [fontsLoaded] = useFonts({ Cinzel_400Regular, Cinzel_700Bold, Archivo_400Regular, Archivo_600SemiBold, Archivo_700Bold });
  const [dataLoaded, setDataLoaded] = useState(false);
  const onReady = useCallback(() => setDataLoaded(true), []);
  useEffect(() => {
    if (fontsLoaded && dataLoaded) SplashScreen.hideAsync().catch(() => {});
  }, [fontsLoaded, dataLoaded]);
  return (
    <ThemeProvider>
      <AppProvider onReady={onReady}>{fontsLoaded ? <AppStack /> : null}</AppProvider>
    </ThemeProvider>
  );
}

function AppStack() {
  const { c } = useTheme();
  const base = c.scheme === 'dark' ? DarkTheme : DefaultTheme;
  const navTheme = { ...base, colors: { ...base.colors, background: c.bg, card: c.header, text: c.headerText, border: c.gold, primary: c.gold } };
  return (
    <NavThemeProvider value={navTheme}>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: c.header },
          headerTintColor: c.headerText,
          headerTitleStyle: { fontFamily: fonts.display, fontSize: 18 },
          contentStyle: { backgroundColor: c.bg },
          headerBackButtonDisplayMode: 'minimal',
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="session/[week]/[day]" options={{ title: 'Workout' }} />
        <Stack.Screen name="settings" options={{ title: 'Setup' }} />
        <Stack.Screen name="signed-in" options={{ headerShown: false }} />
      </Stack>
    </NavThemeProvider>
  );
}
