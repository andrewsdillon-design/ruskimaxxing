// A rest timer that sits under the session. It counts against the clock, so it stays right if the
// phone sleeps, and buzzes when rest is over.
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, Vibration, View } from 'react-native';
import { fonts, useTheme } from '../theme';

const PRESETS = [60, 90, 120, 180, 300];

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

export function RestTimer() {
  const { c } = useTheme();
  const [endAt, setEndAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (endAt === null) return;
    const id = setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (t >= endAt) {
        setEndAt(null);
        setDone(true);
        Vibration.vibrate([0, 400, 200, 400]);
      }
    }, 250);
    return () => clearInterval(id);
  }, [endAt]);

  const left = endAt ? Math.max(0, Math.ceil((endAt - now) / 1000)) : 0;
  const start = (s: number) => {
    setDone(false);
    setNow(Date.now());
    setEndAt(Date.now() + s * 1000);
  };

  const Btn = ({ label, onPress }: { label: string; onPress: () => void }) => (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} style={[s.btn, { borderColor: c.gold }]}>
      <Text style={{ color: c.headerText, fontFamily: fonts.bodyBold, fontSize: 13 }}>{label}</Text>
    </Pressable>
  );

  return (
    <View style={[s.bar, { backgroundColor: c.header, borderTopColor: c.gold }]}>
      {endAt ? (
        <>
          <Text style={[s.time, { color: c.headerText }]} accessibilityLiveRegion="polite">
            {clock(left)}
          </Text>
          <Btn label="−15" onPress={() => setEndAt((e) => (e ? Math.max(Date.now() + 1000, e - 15000) : e))} />
          <Btn label="+15" onPress={() => setEndAt((e) => (e ? e + 15000 : e))} />
          <Btn label="Stop" onPress={() => setEndAt(null)} />
        </>
      ) : (
        <>
          <Text style={[s.label, { color: done ? c.gold : c.headerText }]}>{done ? 'Lift!' : 'Rest'}</Text>
          {PRESETS.map((p) => (
            <Btn key={p} label={clock(p)} onPress={() => start(p)} />
          ))}
        </>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  bar: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderTopWidth: 2 },
  time: { fontFamily: fonts.display, fontSize: 24, flex: 1 },
  label: { fontFamily: fonts.display, fontSize: 16, marginRight: 4, flex: 1 },
  btn: { borderWidth: 1, borderRadius: 5, paddingHorizontal: 9, paddingVertical: 6 },
});
