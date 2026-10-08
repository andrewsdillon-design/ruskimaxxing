// Progress: estimated 1RM over time for each main lift, jumps against the standards, bodyweight and body fat.
import { useState } from 'react';
import { ScrollView } from 'react-native';
import { LineChart, type Point } from '../../components/LineChart';
import { Card, Chip, Row, Screen, Stat } from '../../components/ui';
import { jumpTargets, MAIN } from '../../core/exercises';
import { e1rmHistory } from '../../core/tracking';
import { heightUnit } from '../../core/workout';
import { fmtNum } from '../../lib/format';
import { useApp } from '../../state/app';

const JUMPS = ['Box Jump', 'Broad Jump', 'Vertical Jump'];

function Chips<V extends string>({ options, value, onChange }: { options: V[]; value: V; onChange: (v: V) => void }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, marginBottom: 10 }}>
      {options.map((o) => (
        <Chip key={o} label={o} on={o === value} onPress={() => onChange(o)} />
      ))}
    </ScrollView>
  );
}

function Stats({ points, unit }: { points: Point[]; unit: string }) {
  if (!points.length) return null;
  const first = points[0].value;
  const last = points[points.length - 1].value;
  const diff = last - first;
  return (
    <Row style={{ marginTop: 10 }}>
      <Stat label={`now (${unit})`} value={fmtNum(last)} />
      <Stat label="start" value={fmtNum(first)} />
      <Stat label="change" value={`${diff >= 0 ? '+' : ''}${fmtNum(diff)}`} />
    </Row>
  );
}

export default function Progress() {
  const { store, cfg } = useApp();
  const [lift, setLift] = useState<string>(MAIN[0]);
  const [jump, setJump] = useState(JUMPS[0]);
  const [body, setBody] = useState<'Bodyweight' | 'Body fat %'>('Bodyweight');
  const entries = store.lifts();
  const hu = heightUnit(cfg);

  const strength: Point[] = e1rmHistory(entries, lift).map(([date, value]) => ({ date, value }));

  const bestByDay = new Map<string, number>();
  for (const e of entries) if (e.exercise === jump && e.done && e.weight > 0) bestByDay.set(e.date, Math.max(bestByDay.get(e.date) ?? 0, e.weight));
  const jumps: Point[] = [...bestByDay].map(([date, value]) => ({ date, value }));
  const standards = jumpTargets(jump, cfg.height, hu)
    .filter(([, , t]) => t !== null)
    .map(([level, , t]) => ({ label: `${level} ${fmtNum(t as number)}`, value: t as number }));

  const bodyPoints: Point[] =
    body === 'Bodyweight'
      ? store.bodyweights().map((b) => ({ date: b.date, value: b.weight }))
      : store.bodyfats().map((f) => ({ date: f.date, value: f.percent }));

  return (
    <Screen>
      <Card title="Strength (estimated 1RM)">
        <Chips options={[...MAIN]} value={lift} onChange={setLift} />
        <LineChart points={strength} unit={cfg.unit} empty={`Log a ${lift} set to start the chart.`} />
        <Stats points={strength} unit={cfg.unit} />
      </Card>

      <Card title="Jumps">
        <Chips options={JUMPS} value={jump} onChange={setJump} />
        <LineChart points={jumps} unit={hu} refLines={standards} empty={`Log a ${jump} to start the chart.`} />
        <Stats points={jumps} unit={hu} />
      </Card>

      <Card title="Body">
        <Chips options={['Bodyweight', 'Body fat %'] as ('Bodyweight' | 'Body fat %')[]} value={body} onChange={setBody} />
        <LineChart
          points={bodyPoints}
          unit={body === 'Bodyweight' ? cfg.unit : '%'}
          empty={body === 'Bodyweight' ? 'Log your bodyweight on Today each week.' : 'Log a body fat test on Body.'}
        />
        <Stats points={bodyPoints} unit={body === 'Bodyweight' ? cfg.unit : '%'} />
      </Card>
    </Screen>
  );
}
