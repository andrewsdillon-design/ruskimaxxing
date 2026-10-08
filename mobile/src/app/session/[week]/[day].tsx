// One workout: every set pre-filled from the plan; edit, tick done, save. Leaving saves too.
import { Stack, useLocalSearchParams, useNavigation } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { Icon } from '../../../components/brand';
import { RestTimer } from '../../../components/RestTimer';
import { Banner, Button, Card, Display, GoldRule, KindTag, Row, Screen, T, Tag } from '../../../components/ui';
import { fmtLong } from '../../../core/dates';
import { isPlyo } from '../../../core/exercises';
import { fmtG } from '../../../core/pyfmt';
import { session, sessionDate, weekLabel } from '../../../core/program';
import { addSet, heightUnit, markAllDone, saveWorkout, workoutModel, type SaveResult, type SetRow, type WorkoutBlock } from '../../../core/workout';
import { groupPrs, plural } from '../../../lib/format';
import { useApp } from '../../../state/app';
import { fonts, useTheme } from '../../../theme';

export default function SessionScreen() {
  const params = useLocalSearchParams<{ week: string; day: string }>();
  const week = Number(params.week);
  const day = Number(params.day);
  const { c } = useTheme();
  const { store, cfg, backupQuietly } = useApp();
  const s = session(week, day);
  const navigation = useNavigation();

  const [blocks, setBlocks] = useState<WorkoutBlock[]>(() => workoutModel(store, week, day, cfg));
  const [dirty, setDirty] = useState(false);
  const [result, setResult] = useState<(SaveResult & { done: number }) | null>(null);

  // keep the latest edits reachable from the "leaving the screen" listener
  const latest = useRef({ blocks, dirty });
  latest.current = { blocks, dirty };

  const edit = (next: WorkoutBlock[]) => {
    setBlocks(next);
    setDirty(true);
  };

  const persist = useCallback(
    (current: WorkoutBlock[]) => {
      const out = saveWorkout(store, week, day, current, cfg);
      backupQuietly();
      return out;
    },
    [store, week, day, cfg, backupQuietly],
  );

  // never lose edits: save on the way out
  useEffect(
    () =>
      navigation.addListener('beforeRemove', () => {
        if (latest.current.dirty) persist(latest.current.blocks);
      }),
    [navigation, persist],
  );

  const save = () => {
    const out = persist(blocks);
    setBlocks(workoutModel(store, week, day, cfg));
    setDirty(false);
    setResult({ ...out, done: out.saved.filter((e) => e.done).length });
  };

  const setRow = (bi: number, ri: number, patch: Partial<SetRow>) =>
    edit(blocks.map((b, i) => (i !== bi ? b : { ...b, rows: b.rows.map((r, j) => (j !== ri ? r : { ...r, ...patch })) })));

  const done = blocks.reduce((n, b) => n + b.rows.filter((r) => r.done).length, 0);
  const planned = blocks.reduce((n, b) => n + b.planned, 0);

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <Stack.Screen options={{ title: s.day.split(' - ')[0] }} />
      <Screen>
        <Card>
          <Row style={{ justifyContent: 'space-between' }}>
            <T muted size={13}>{weekLabel(week)}</T>
            <Tag label={s.phase} color={/test|baseline/i.test(s.phase) ? c.danger : c.gold} />
          </Row>
          <Display size={23} style={{ marginTop: 4 }}>{s.day.split(' - ')[1] ?? s.day}</Display>
          <T muted size={13}>{fmtLong(sessionDate(s, cfg.start))}</T>
          <GoldRule style={{ marginVertical: 10 }} />
          <Row style={{ justifyContent: 'space-between' }}>
            <T bold>
              {done}/{planned} sets done
            </T>
            <Button title="Mark all done" kind="secondary" small onPress={() => edit(markAllDone(blocks))} />
          </Row>
        </Card>

        {blocks.map((b, bi) => (
          <ExerciseCard
            key={`${b.p.exercise}-${bi}`}
            block={b}
            unit={isPlyo(b.p.exercise) ? heightUnit(cfg) : cfg.unit}
            onRow={(ri, patch) => setRow(bi, ri, patch)}
            onAddSet={() => edit(addSet(blocks, bi))}
            onNote={(note) => edit(blocks.map((x, i) => (i === bi ? { ...x, note } : x)))}
          />
        ))}

        <Card title="Finish">
          {dirty ? <T size={13} style={{ color: c.danger, marginBottom: 8 }}>Unsaved changes (leaving this screen saves them too).</T> : null}
          <Button title="Save workout" onPress={save} />
        </Card>
      </Screen>
      <RestTimer />
      <ResultModal result={result} onClose={() => setResult(null)} />
    </View>
  );
}

function ExerciseCard({
  block,
  unit,
  onRow,
  onAddSet,
  onNote,
}: {
  block: WorkoutBlock;
  unit: string;
  onRow: (ri: number, patch: Partial<SetRow>) => void;
  onAddSet: () => void;
  onNote: (note: string) => void;
}) {
  const { c } = useTheme();
  const p = block.p;
  const scheme = `${p.sets ? `${p.sets} × ${p.reps}` : p.reps}${p.percent ? ` @ ${fmtG(p.percent)}%` : ''}`;
  const needsMax = block.source === 'enter a starting max';
  return (
    <Card accent={p.kind === 'test' ? c.danger : undefined}>
      <Row style={{ alignItems: 'flex-start' }}>
        <View style={{ flex: 1 }}>
          <Display size={17}>{p.exercise}</Display>
          <T bold style={{ marginTop: 2 }}>{scheme}</T>
          <T size={13} style={{ color: needsMax ? c.danger : c.muted }}>
            {needsMax ? 'Enter a starting max in Setup to get weights' : block.source}
          </T>
        </View>
        <KindTag kind={p.kind} />
      </Row>
      {p.note ? <T size={13} muted style={{ marginTop: 4, fontStyle: 'italic' }}>{p.note}</T> : null}

      <View style={[st.head, { borderBottomColor: c.borderSoft }]}>
        <T size={11} muted style={st.setCol}>SET</T>
        <T size={11} muted style={st.col}>{unit.toUpperCase()}</T>
        <T size={11} muted style={st.col}>REPS</T>
        <T size={11} muted style={st.rpeCol}>RPE</T>
        <T size={11} muted style={st.doneCol}>DONE</T>
      </View>
      {block.rows.map((r, ri) => (
        <View key={ri} style={st.row}>
          <T bold style={[st.setCol, r.target === 'extra set' && { color: c.gold }]}>{r.target === 'extra set' ? '+' : ri + 1}</T>
          <Box value={r.weight} placeholder="–" decimal onChangeText={(v) => onRow(ri, { weight: v })} label={`${p.exercise} set ${ri + 1} weight`} />
          <Box value={r.reps} placeholder={p.reps} onChangeText={(v) => onRow(ri, { reps: v })} label={`${p.exercise} set ${ri + 1} reps`} />
          <Box value={r.rpe} placeholder="–" decimal small onChangeText={(v) => onRow(ri, { rpe: v })} label={`${p.exercise} set ${ri + 1} RPE`} />
          <Pressable
            onPress={() => onRow(ri, { done: !r.done })}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: r.done }}
            accessibilityLabel={`${p.exercise} set ${ri + 1} done`}
            hitSlop={6}
            style={[st.doneCol, st.tick, { borderColor: r.done ? c.success : c.gold, backgroundColor: r.done ? c.success : c.field }]}
          >
            {r.done ? <Icon name="check" color="#FFF8E1" size={20} /> : null}
          </Pressable>
        </View>
      ))}
      <Row style={{ marginTop: 8 }}>
        <TextInput
          value={block.note}
          onChangeText={onNote}
          placeholder="Notes"
          placeholderTextColor={c.muted}
          style={[st.note, { backgroundColor: c.field, borderColor: c.borderSoft, color: c.text, fontFamily: fonts.body }]}
        />
        <Button title="+ Set" kind="secondary" small onPress={onAddSet} />
      </Row>
    </Card>
  );
}

function Box({ value, placeholder, onChangeText, decimal, small, label }: {
  value: string;
  placeholder: string;
  onChangeText: (v: string) => void;
  decimal?: boolean;
  small?: boolean;
  label: string;
}) {
  const { c } = useTheme();
  return (
    <TextInput
      value={value}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={c.muted}
      keyboardType={decimal ? 'decimal-pad' : 'number-pad'}
      selectTextOnFocus
      accessibilityLabel={label}
      style={[small ? st.rpeCol : st.col, st.box, { backgroundColor: c.field, borderColor: c.borderSoft, color: c.text, fontFamily: fonts.bodySemi }]}
    />
  );
}

function ResultModal({ result, onClose }: { result: (SaveResult & { done: number }) | null; onClose: () => void }) {
  const { c } = useTheme();
  if (!result) return null;
  return (
    <Modal transparent animationType="fade" visible onRequestClose={onClose}>
      <View style={st.backdrop}>
        <Card title={result.prs.length ? 'New PR!' : 'Workout saved'} style={{ width: '100%', maxWidth: 420 }}>
          <T>{plural(result.done, 'set')} done.</T>
          {result.prs.length ? (
            <View style={{ marginTop: 8 }}>
              {groupPrs(result.prs).map((p) => (
                <T key={p} bold style={{ color: c.danger }}>✦ {p}</T>
              ))}
            </View>
          ) : null}
          {result.bad.length ? (
            <Banner tone="warn">
              <T size={14}>Ticked done but no reps, so saved as not done:</T>
              {result.bad.map((b) => (
                <T key={b} size={14}>• {b}</T>
              ))}
            </Banner>
          ) : null}
          <Button title="Done" style={{ marginTop: 12 }} onPress={onClose} />
        </Card>
      </View>
    </Modal>
  );
}

const st = StyleSheet.create({
  head: { flexDirection: 'row', gap: 6, marginTop: 12, paddingBottom: 4, borderBottomWidth: 1 },
  row: { flexDirection: 'row', gap: 6, alignItems: 'center', marginTop: 6 },
  setCol: { width: 26, textAlign: 'center' },
  col: { flex: 1, minWidth: 0, textAlign: 'center' },
  rpeCol: { width: 52, minWidth: 0, flexShrink: 0, textAlign: 'center' },
  doneCol: { width: 44, textAlign: 'center' },
  box: { borderWidth: 1, borderRadius: 5, paddingVertical: 8, paddingHorizontal: 6, fontSize: 16, textAlign: 'center' },
  tick: { height: 38, borderWidth: 1.5, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  note: { flex: 1, borderWidth: 1, borderRadius: 5, paddingVertical: 8, paddingHorizontal: 10, fontSize: 15 },
  backdrop: { flex: 1, backgroundColor: 'rgba(20,4,18,0.6)', alignItems: 'center', justifyContent: 'center', padding: 20 },
});
