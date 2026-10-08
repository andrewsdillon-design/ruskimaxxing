// Today: where you are in the year, this week's three sessions, this week's bodyweight.
import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { Emblem } from '../../components/brand';
import { DayRow } from '../../components/DayRow';
import { Banner, Button, Card, Display, Field, GoldRule, Row, Screen, T, Tag } from '../../components/ui';
import { addWeeks, fmtLong } from '../../core/dates';
import { fmtG } from '../../core/pyfmt';
import { bodyfatWeek, MONTHS, monthOf, session, SHOULDER_TIP, WEEKS, weekLabel } from '../../core/program';
import { dayProgress, number } from '../../core/workout';
import { useApp } from '../../state/app';
import { useTheme } from '../../theme';

export default function Today() {
  const { c } = useTheme();
  const { store, cfg, setUp, currentWeek } = useApp();
  const week = currentWeek;
  const s = session(week, 0);
  const next = [0, 1, 2].find((d) => {
    const [done, planned] = dayProgress(store, week, d);
    return done < planned;
  });
  const bfMonth = Array.from({ length: MONTHS }, (_, i) => i + 1).find((m) => bodyfatWeek(m) === week);

  return (
    <Screen>
      <Card style={{ backgroundColor: c.header, borderColor: c.gold }}>
        <Row style={{ gap: 14 }}>
          <Emblem size={64} />
          <View style={{ flex: 1 }}>
            <T size={12} style={{ color: c.tabInactive, letterSpacing: 1 }}>
              {week === 0 ? 'BASELINE' : `MONTH ${monthOf(week)} OF ${MONTHS} · WEEK ${week} OF ${WEEKS}`}
            </T>
            <Display size={21} color={c.headerText} style={{ marginTop: 2 }}>
              {s.phase}
            </Display>
            <T size={13} style={{ color: c.tabInactive }}>{weekLabel(week)}</T>
          </View>
        </Row>
        <View style={{ height: 6, borderRadius: 3, backgroundColor: 'rgba(242,214,117,0.18)', marginTop: 14, overflow: 'hidden' }}>
          <View style={{ height: 6, borderRadius: 3, backgroundColor: c.gold, width: `${(week / WEEKS) * 100}%` }} />
        </View>
        <T size={12} style={{ color: c.tabInactive, marginTop: 6 }}>
          {setUp ? `Started ${fmtLong(cfg.start)}` : 'Not started yet'}
        </T>
      </Card>

      {!setUp ? (
        <Banner tone="warn">
          <T bold>Set up your year first</T>
          <T size={14} style={{ marginTop: 2 }}>
            Pick your start Monday, units and height, and enter your starting maxes - every weight in the program comes from them.
          </T>
          <Button title="Open Setup" small onPress={() => router.push('/settings')} style={{ marginTop: 10, alignSelf: 'flex-start' }} />
        </Banner>
      ) : null}

      <Card title="This week" right={<Tag label={`Week ${week}`} color={c.gold} />}>
        <View style={{ gap: 8 }}>
          {[0, 1, 2].map((d) => (
            <DayRow key={d} week={week} day={d} highlight={d === next} />
          ))}
        </View>
        {next === undefined ? <T style={{ color: c.success, marginTop: 10 }}>Week complete. Rest up.</T> : null}
      </Card>

      {bfMonth ? (
        <Banner tone="warn">
          <T bold>Body fat test due this week (month {bfMonth})</T>
          <Button title="Log it on Body" kind="secondary" small onPress={() => router.push('/body')} style={{ marginTop: 8, alignSelf: 'flex-start' }} />
        </Banner>
      ) : null}

      <BodyweightCard week={week} />

      <Card title="Shoulder tip" accent={c.danger}>
        <T size={14}>{SHOULDER_TIP.replace(/^SHOULDER TIP - /, '')}</T>
      </Card>
    </Screen>
  );
}

function BodyweightCard({ week }: { week: number }) {
  const { c } = useTheme();
  const { store, cfg } = useApp();
  const saved = store.bodyweights().find((b) => b.week === week);
  const [text, setText] = useState(saved ? fmtG(saved.weight) : '');
  const [msg, setMsg] = useState('');
  const save = () => {
    const w = number(text);
    if (w) store.setBodyweight({ week, date: addWeeks(cfg.start, week - 1), weight: w });
    else store.deleteBodyweight(week);
    setMsg(w ? 'Saved.' : 'Cleared.');
  };
  return (
    <Card title="Bodyweight this week">
      <Row style={{ alignItems: 'flex-end' }}>
        <Field
          label={`Week ${week} (${cfg.unit})`}
          value={text}
          onChangeText={(v) => {
            setText(v);
            setMsg('');
          }}
          keyboardType="decimal-pad"
          placeholder="e.g. 180"
          style={{ flex: 1, marginBottom: 0 }}
        />
        <Button title="Save" onPress={save} />
      </Row>
      {msg ? <T size={13} style={{ color: c.success, marginTop: 6 }}>{msg}</T> : null}
      <GoldRule style={{ marginVertical: 10 }} />
      <T size={13} muted>Weigh in once a week, same time of day. It charts against your lifts on Progress.</T>
    </Card>
  );
}
