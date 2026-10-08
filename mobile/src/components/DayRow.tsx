// One training day: name, date, a progress bar of sets done, and a tick once it's complete. Opens the workout.
import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';
import { fmtDayMonDay } from '../core/dates';
import { session, sessionDate } from '../core/program';
import { dayProgress } from '../core/workout';
import { useApp } from '../state/app';
import { fonts, useTheme } from '../theme';
import { Icon } from './brand';
import { T } from './ui';

export function DayRow({ week, day, highlight }: { week: number; day: number; highlight?: boolean }) {
  const { c } = useTheme();
  const { store, cfg } = useApp();
  const s = session(week, day);
  const [done, planned] = dayProgress(store, week, day);
  const complete = done >= planned;
  const name = s.day.split(' - ');
  return (
    <Pressable
      onPress={() => router.push({ pathname: '/session/[week]/[day]', params: { week: String(week), day: String(day) } })}
      accessibilityRole="button"
      accessibilityLabel={`${s.day}, ${fmtDayMonDay(sessionDate(s, cfg.start))}, ${done} of ${planned} sets done`}
      style={({ pressed }) => [
        st.row,
        { backgroundColor: highlight ? c.field : c.card, borderColor: highlight ? c.gold : c.borderSoft, opacity: pressed ? 0.8 : 1 },
      ]}
    >
      <View style={[st.badge, { borderColor: complete ? c.success : c.gold, backgroundColor: complete ? c.success : 'transparent' }]}>
        {complete ? <Icon name="check" color="#FFF8E1" size={18} /> : <T bold style={{ color: c.accent }}>{day + 1}</T>}
      </View>
      <View style={{ flex: 1 }}>
        <T bold style={{ fontFamily: fonts.bodyBold }}>
          {name[1] ?? s.day}
          {highlight ? <T size={12} style={{ color: c.gold }}>{'   ◆ NEXT UP'}</T> : null}
        </T>
        <T size={13} muted>
          {fmtDayMonDay(sessionDate(s, cfg.start))} · {s.phase}
        </T>
        <View style={[st.track, { backgroundColor: c.borderSoft }]}>
          <View style={[st.fill, { width: `${Math.min(100, (done / planned) * 100)}%`, backgroundColor: complete ? c.success : c.gold }]} />
        </View>
      </View>
      <T size={13} muted style={{ minWidth: 44, textAlign: 'right' }}>
        {done}/{planned}
      </T>
    </Pressable>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderRadius: 6, padding: 12 },
  badge: { width: 34, height: 34, borderRadius: 17, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  track: { height: 4, borderRadius: 2, marginTop: 6, overflow: 'hidden' },
  fill: { height: 4, borderRadius: 2 },
});
