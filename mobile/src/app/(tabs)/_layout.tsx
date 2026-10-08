import { router, Tabs } from 'expo-router';
import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Icon } from '../../components/brand';
import { fonts, useTheme } from '../../theme';

export default function TabsLayout() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: c.header },
        headerBackground: () => <View style={{ flex: 1, backgroundColor: c.header, borderBottomWidth: 2, borderBottomColor: c.gold }} />,
        headerTintColor: c.headerText,
        headerTitleStyle: { fontFamily: fonts.display, fontSize: 19, color: c.headerText },
        headerRight: () => (
          <Pressable onPress={() => router.push('/settings')} accessibilityLabel="Setup" hitSlop={12} style={{ paddingHorizontal: 14 }}>
            <Icon name="settings" color={c.headerText} />
          </Pressable>
        ),
        tabBarStyle: {
          backgroundColor: c.tabBar,
          borderTopColor: c.gold,
          borderTopWidth: 1.5,
          height: 66 + insets.bottom,
          paddingTop: 4,
          paddingBottom: insets.bottom + 4,
        },
        tabBarActiveTintColor: c.tabActive,
        tabBarInactiveTintColor: c.tabInactive,
        tabBarLabelStyle: { fontFamily: fonts.bodySemi, fontSize: 11, lineHeight: 15 },
        sceneStyle: { backgroundColor: c.bg },
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Today', headerTitle: 'RuskiMaxxing', tabBarIcon: ({ color }) => <Icon name="today" color={color} /> }} />
      <Tabs.Screen name="program" options={{ title: 'Program', tabBarIcon: ({ color }) => <Icon name="program" color={color} /> }} />
      <Tabs.Screen name="progress" options={{ title: 'Progress', tabBarIcon: ({ color }) => <Icon name="progress" color={color} /> }} />
      <Tabs.Screen name="prs" options={{ title: 'PRs', tabBarIcon: ({ color }) => <Icon name="trophy" color={color} /> }} />
      <Tabs.Screen name="body" options={{ title: 'Body', tabBarIcon: ({ color }) => <Icon name="body" color={color} /> }} />
    </Tabs>
  );
}
