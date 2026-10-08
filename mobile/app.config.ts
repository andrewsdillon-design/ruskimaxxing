// Expo app config: store identity, icons, splash and the ruskimaxxing:// link the website sends people back on.
import type { ConfigContext, ExpoConfig } from 'expo/config';
import easProject from './eas-project.json';

const PURPLE = '#4A1942';
const PURPLE_DARK = '#2E0C28';

// The EAS project this app builds under (Expo account dandrews91). tools/ship_expo.py creates it the first
// time and saves its ID in eas-project.json; EAS_PROJECT_ID overrides it.
const easProjectId = (): string | undefined => process.env.EAS_PROJECT_ID || easProject.projectId || undefined;

export default ({ config }: ConfigContext): ExpoConfig => {
  const projectId = easProjectId();
  return {
    ...config,
    name: 'RuskiMaxxing',
    slug: 'ruskimaxxing',
    owner: 'dandrews91',
    scheme: 'ruskimaxxing', // the website's "Return to the app" button after signing in
    version: '2.4.0',
    orientation: 'portrait',
    icon: './assets/icon.png',
    userInterfaceStyle: 'automatic',
    backgroundColor: PURPLE_DARK,
    ios: {
      // Same App Store Connect app as the earlier builds (App Store bundle IDs can't contain "_")
      bundleIdentifier: 'io.github.andrewsdillondesign.ruskimaxxing-mobile',
      appleTeamId: 'GA9A5J9A44', // Dillon REA Andrews (Individual)
      supportsTablet: false,
      infoPlist: {
        ITSAppUsesNonExemptEncryption: false, // HTTPS only: exempt, no export-compliance question per build
      },
      // Apple's privacy manifest: no tracking; the "required reason" APIs React Native / Expo use; and what the
      // optional cloud backup collects (see docs/APP_STORE.md, "Privacy nutrition label")
      privacyManifests: {
        NSPrivacyTracking: false,
        NSPrivacyTrackingDomains: [],
        NSPrivacyAccessedAPITypes: [
          { NSPrivacyAccessedAPIType: 'NSPrivacyAccessedAPICategoryUserDefaults', NSPrivacyAccessedAPITypeReasons: ['CA92.1'] },
          { NSPrivacyAccessedAPIType: 'NSPrivacyAccessedAPICategoryFileTimestamp', NSPrivacyAccessedAPITypeReasons: ['C617.1'] },
          { NSPrivacyAccessedAPIType: 'NSPrivacyAccessedAPICategorySystemBootTime', NSPrivacyAccessedAPITypeReasons: ['35F9.1'] },
          { NSPrivacyAccessedAPIType: 'NSPrivacyAccessedAPICategoryDiskSpace', NSPrivacyAccessedAPITypeReasons: ['E174.1'] },
        ],
        NSPrivacyCollectedDataTypes: ['EmailAddress', 'Fitness', 'Health'].map((kind) => ({
          NSPrivacyCollectedDataType: `NSPrivacyCollectedDataType${kind}`,
          NSPrivacyCollectedDataTypeLinked: true,
          NSPrivacyCollectedDataTypeTracking: false,
          NSPrivacyCollectedDataTypePurposes: ['NSPrivacyCollectedDataTypePurposeAppFunctionality'],
        })),
      },
    },
    android: {
      package: 'io.github.andrewsdillondesign.ruskimaxxing_mobile', // unchanged from the earlier Android app
      adaptiveIcon: {
        backgroundColor: PURPLE_DARK,
        foregroundImage: './assets/android-icon-foreground.png',
        backgroundImage: './assets/android-icon-background.png',
        monochromeImage: './assets/android-icon-monochrome.png',
      },
      predictiveBackGestureEnabled: false,
    },
    web: {
      favicon: './assets/favicon.png',
      name: 'RuskiMaxxing',
      shortName: 'RuskiMaxxing',
      backgroundColor: PURPLE_DARK,
      themeColor: PURPLE,
      output: 'single',
    },
    plugins: [
      'expo-router',
      'expo-secure-store',
      'expo-font',
      [
        'expo-splash-screen',
        {
          image: './assets/splash-icon.png',
          imageWidth: 220,
          resizeMode: 'contain',
          backgroundColor: PURPLE_DARK,
          dark: { image: './assets/splash-icon.png', backgroundColor: '#170613' },
        },
      ],
    ],
    experiments: { typedRoutes: true },
    extra: {
      apiUrl: 'https://api.ruskimaxxing.com',
      ...(projectId ? { eas: { projectId } } : {}),
    },
  };
};
