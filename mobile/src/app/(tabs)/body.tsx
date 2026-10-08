// Body: monthly body fat (with the how-to), and the weekly bodyweight log.
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';
import { Button, Card, Chip, Field, GoldRule, Row, Screen, T, Tag } from '../../components/ui';
import { addWeeks, fmtMonDay, isValidIso, today } from '../../core/dates';
import { bodyfatWeek, monthOf, MONTHS } from '../../core/program';
import { fmtG } from '../../core/pyfmt';
import { BODYFAT_GUIDE, BODYFAT_METHODS, leanMass } from '../../core/tracking';
import { number } from '../../core/workout';
import { useApp } from '../../state/app';
import { useTheme } from '../../theme';

export default function Body() {
  const { c } = useTheme();
  const { store, cfg, currentWeek } = useApp();
  const fats = new Map(store.bodyfats().map((f) => [f.month, f]));
  const [month, setMonth] = useState(Math.max(1, monthOf(currentWeek)));
  const [date, setDate] = useState(today());
  const [pct, setPct] = useState('');
  const [weight, setWeight] = useState('');
  const [method, setMethod] = useState(store.get('bodyfat_method', '') || BODYFAT_METHODS[0]);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [guide, setGuide] = useState(false);

  const save = () => {
    const percent = number(pct);
    if (!percent || !isValidIso(date)) return setMsg({ text: 'Enter the date (YYYY-MM-DD) and your body fat %.', ok: false });
    store.setBodyfat({ month, date, percent, method, weight: number(weight) });
    setPct('');
    setMsg({ text: `Month ${month} saved.`, ok: true });
  };

  const weights = [...store.bodyweights()].sort((a, b) => b.week - a.week).slice(0, 12);

  return (
    <Screen>
      <Card title="Body fat - once a month">
        <T size={13} muted style={{ marginBottom: 6 }}>Month</T>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, marginBottom: 10 }}>
          {Array.from({ length: MONTHS }, (_, i) => i + 1).map((m) => (
            <Chip key={m} label={`M${m}${fats.has(m) ? ' ✓' : ''}`} on={m === month} onPress={() => setMonth(m)} />
          ))}
        </ScrollView>
        <Row>
          <Field label="Date" value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" autoCapitalize="none" style={{ flex: 1 }} />
          <Field label="Body fat %" value={pct} onChangeText={setPct} keyboardType="decimal-pad" placeholder="e.g. 18.5" style={{ flex: 1 }} />
        </Row>
        <Field label={`Weight at the test (${cfg.unit}, optional)`} value={weight} onChangeText={setWeight} keyboardType="decimal-pad" />
        <T size={13} muted style={{ marginBottom: 6 }}>Method</T>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
          {BODYFAT_METHODS.map((m) => (
            <Chip key={m} label={m} on={m === method} onPress={() => setMethod(m)} />
          ))}
        </View>
        <Button title="Save body fat" onPress={save} />
        {msg ? <T size={13} style={{ color: msg.ok ? c.success : c.danger, marginTop: 8 }}>{msg.text}</T> : null}
      </Card>

      <Card title="Monthly tests">
        {Array.from({ length: MONTHS }, (_, i) => i + 1).map((m) => {
          const f = fats.get(m);
          const due = addWeeks(cfg.start, bodyfatWeek(m) - 1);
          const lean = f ? leanMass(f) : null;
          return (
            <Row key={m} style={{ paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: c.borderSoft }}>
              <T bold style={{ width: 38 }}>M{m}</T>
              {f ? (
                <View style={{ flex: 1 }}>
                  <T bold>
                    {fmtG(f.percent)}%{lean ? <T size={13} muted>{`  ·  lean ${fmtG(lean)} ${cfg.unit}`}</T> : null}
                  </T>
                  <T size={12} muted>{fmtMonDay(f.date)} · {f.method}</T>
                </View>
              ) : (
                <T muted style={{ flex: 1 }}>due {fmtMonDay(due)}</T>
              )}
              {bodyfatWeek(m) === currentWeek ? <Tag label="Due" color={c.danger} /> : null}
            </Row>
          );
        })}
      </Card>

      <Card title="Bodyweight - weekly">
        <T size={13} muted style={{ marginBottom: 6 }}>Enter it on Today each week.</T>
        {weights.length ? (
          weights.map((b) => (
            <Row key={b.week} style={{ justifyContent: 'space-between', paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: c.borderSoft }}>
              <T>Week {b.week} <T size={13} muted>({fmtMonDay(b.date)})</T></T>
              <T bold>{fmtG(b.weight)} {cfg.unit}</T>
            </Row>
          ))
        ) : (
          <T muted>Nothing yet.</T>
        )}
      </Card>

      <Card title="How to measure body fat">
        <Pressable onPress={() => setGuide((g) => !g)} accessibilityRole="button">
          <T style={{ color: c.accent, textDecorationLine: 'underline' }}>{guide ? 'Hide the guide' : 'Show the guide'}</T>
        </Pressable>
        {guide ? (
          <>
            <GoldRule style={{ marginVertical: 10 }} />
            <T size={14}>{BODYFAT_GUIDE}</T>
          </>
        ) : null}
      </Card>
    </Screen>
  );
}
