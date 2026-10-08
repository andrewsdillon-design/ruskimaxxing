// Setup: intake (start date, units, height), starting maxes, cloud backup (sign in, back up, delete account),
// privacy / terms, appearance and Prilepin's chart.
import Constants from 'expo-constants';
import * as Linking from 'expo-linking';
import { useState } from 'react';
import { Alert, Pressable, View } from 'react-native';
import { ExercisePicker } from '../components/ExercisePicker';
import { Banner, Button, Card, Chip, Field, GoldRule, Row, Screen, Segmented, T } from '../components/ui';
import { addWeeks, isValidIso, nextMonday, weekday } from '../core/dates';
import { isPlyo } from '../core/exercises';
import { ZONES } from '../core/prilepin';
import { fmtG } from '../core/pyfmt';
import { CloudError } from '../core/sync';
import { BODYFAT_METHODS, e1rm, entry } from '../core/tracking';
import { heightUnit, number } from '../core/workout';
import { errorText } from '../lib/format';
import { useApp } from '../state/app';
import { useTheme, type ThemePref } from '../theme';

export default function Settings() {
  return (
    <Screen>
      <Intake />
      <StartingMaxes />
      <CloudBackup />
      <Appearance />
      <Prilepin />
      <About />
    </Screen>
  );
}

function Intake() {
  const { c } = useTheme();
  const { store, cfg } = useApp();
  const [units, setUnits] = useState<'lb' | 'kg'>(cfg.unit);
  const [increment, setIncrement] = useState(store.get('increment', '5'));
  const [start, setStart] = useState(store.get('start', '') || nextMonday());
  const [height, setHeight] = useState(store.get('height', ''));
  const [bw, setBw] = useState(store.get('bodyweight_start', ''));
  const [bf, setBf] = useState(store.get('bodyfat_start', ''));
  const [method, setMethod] = useState(store.get('bodyfat_method', ''));
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  const save = () => {
    if (!isValidIso(start.trim())) return setMsg({ text: 'Use the format YYYY-MM-DD for the start date.', ok: false });
    store.setMany({
      units,
      increment: number(increment) ? fmtG(number(increment) as number) : '5',
      start: start.trim(),
      height: number(height) ? fmtG(number(height) as number) : '',
      bodyweight_start: number(bw) ? fmtG(number(bw) as number) : '',
      bodyfat_start: number(bf) ? fmtG(number(bf) as number) : '',
      bodyfat_method: method,
    });
    const startWeight = number(bw);
    if (startWeight && !store.bodyweights().some((b) => b.week === 0))
      store.setBodyweight({ week: 0, date: addWeeks(start.trim(), -1), weight: startWeight });
    setMsg({ text: 'Saved. Every weight in the program now uses these.', ok: true });
  };

  const hu = units === 'kg' ? 'cm' : 'in';
  return (
    <Card title="1. Intake">
      <T size={13} muted style={{ marginBottom: 6 }}>Units</T>
      <Segmented options={[{ value: 'lb', label: 'Pounds (lb)' }, { value: 'kg', label: 'Kilos (kg)' }]} value={units} onChange={setUnits} style={{ marginBottom: 12 }} />
      <Row>
        <Field label={`Round weights to (${units})`} value={increment} onChangeText={setIncrement} keyboardType="decimal-pad" style={{ flex: 1 }} />
        <Field label={`Height (${hu})`} value={height} onChangeText={setHeight} keyboardType="decimal-pad" style={{ flex: 1 }} />
      </Row>
      <Field label="Start date (a Monday, YYYY-MM-DD)" value={start} onChangeText={setStart} autoCapitalize="none" />
      {isValidIso(start.trim()) && weekday(start.trim()) !== 0 ? (
        <T size={13} style={{ color: c.danger, marginTop: -6, marginBottom: 8 }}>That's not a Monday - the plan's days are Mon / Wed / Fri.</T>
      ) : null}
      <Chip label="Next Monday" onPress={() => setStart(nextMonday())} />
      <Row style={{ marginTop: 12 }}>
        <Field label={`Starting bodyweight (${units})`} value={bw} onChangeText={setBw} keyboardType="decimal-pad" style={{ flex: 1 }} />
        <Field label="Starting body fat %" value={bf} onChangeText={setBf} keyboardType="decimal-pad" style={{ flex: 1 }} />
      </Row>
      <T size={13} muted style={{ marginBottom: 6 }}>Body fat method</T>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
        {BODYFAT_METHODS.map((m) => (
          <Chip key={m} label={m} on={m === method} onPress={() => setMethod(m)} />
        ))}
      </View>
      <Button title="Save intake" onPress={save} />
      {msg ? <T size={13} style={{ color: msg.ok ? c.success : c.danger, marginTop: 8 }}>{msg.text}</T> : null}
    </Card>
  );
}

function StartingMaxes() {
  const { c } = useTheme();
  const { store, cfg } = useApp();
  const [exercise, setExercise] = useState('Squat');
  const [picking, setPicking] = useState(false);
  const [weight, setWeight] = useState('');
  const [reps, setReps] = useState('1');
  const baselines = store.lifts().filter((e) => e.kind === 'baseline');
  const unit = isPlyo(exercise) ? heightUnit(cfg) : cfg.unit;

  const add = () => {
    const w = number(weight);
    const r = number(reps);
    if (!w || !r) return;
    store.addLift(entry({ date: addWeeks(cfg.start, -1), exercise, weight: w, reps: Math.trunc(r), kind: 'baseline', note: 'starting max' }));
    setWeight('');
  };

  return (
    <Card title="2. Starting maxes">
      <T size={14} muted style={{ marginBottom: 10 }}>
        Enter what you know - any movement, weight and reps - or run Week 0 to test. Weights for each cycle come from these.
      </T>
      <Pressable
        onPress={() => setPicking(true)}
        accessibilityRole="button"
        style={{ borderWidth: 1, borderColor: c.gold, borderRadius: 6, padding: 11, marginBottom: 10, backgroundColor: c.field }}
      >
        <T size={12} muted>Exercise</T>
        <T bold>{exercise}  ▾</T>
      </Pressable>
      <Row style={{ alignItems: 'flex-end' }}>
        <Field label={`Weight (${unit})`} value={weight} onChangeText={setWeight} keyboardType="decimal-pad" style={{ flex: 1, marginBottom: 0 }} />
        <Field label="Reps" value={reps} onChangeText={setReps} keyboardType="number-pad" style={{ width: 70, marginBottom: 0 }} />
        <Button title="Add" onPress={add} />
      </Row>
      {baselines.length ? <GoldRule style={{ marginVertical: 12 }} /> : null}
      {baselines.map((e) => (
        <Row key={e.id} style={{ paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: c.borderSoft }}>
          <View style={{ flex: 1 }}>
            <T bold>{e.exercise}</T>
            <T size={13} muted>
              {fmtG(e.weight)} × {e.reps}
              {isPlyo(e.exercise) ? '' : `  ·  e1RM ${Math.round(e1rm(e))}`}
            </T>
          </View>
          <Button title="Remove" kind="ghost" small onPress={() => store.deleteLift(e.id as number)} />
        </Row>
      ))}
      <ExercisePicker visible={picking} onClose={() => setPicking(false)} onPick={(n) => { setExercise(n); setPicking(false); }} />
    </Card>
  );
}

function CloudBackup() {
  const { c } = useTheme();
  const { cloud, refresh } = useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [password, setPassword] = useState('');

  const run = async (label: string, work: () => Promise<string | void>) => {
    setBusy(label);
    try {
      const msg = await work();
      if (msg) Alert.alert('Cloud backup', msg);
    } catch (e) {
      Alert.alert('Cloud backup', errorText(e));
    } finally {
      setBusy(null);
      refresh();
    }
  };

  const signIn = () =>
    run('signin', async () => {
      // already started: reopen the same page; otherwise ask the server for a fresh sign-in link
      const url = cloud.pendingCode ? cloud.pendingUrl : (await cloud.startBrowserSignIn()).url;
      await Linking.openURL(url);
    });

  return (
    <Card title="3. Cloud backup (optional)">
      <T size={14} muted>Back up to the cloud so you can sign in on a new phone (or the desktop app) and get everything back.</T>
      <Banner tone={cloud.loggedIn ? 'good' : 'info'}>{cloud.status()}</Banner>
      <View style={{ gap: 8, marginTop: 10 }}>
        {cloud.loggedIn ? (
          <>
            <Row>
              <Button
                title="Back up now"
                style={{ flex: 1 }}
                busy={busy === 'sync'}
                onPress={() =>
                  run('sync', async () => {
                    try {
                      const [sent, received] = await cloud.sync();
                      return `Backed up ${sent}, received ${received} records.`;
                    } catch (e) {
                      if (e instanceof CloudError && e.code === 402) return e.message;
                      throw e;
                    }
                  })
                }
              />
              <Button title="Log out" kind="secondary" style={{ flex: 1 }} busy={busy === 'logout'} onPress={() => run('logout', async () => {
                await cloud.logout();
                return 'Logged out. Your data stays on this phone.';
              })} />
            </Row>
            {!deleting ? (
              <Button title="Delete account" kind="ghost" onPress={() => setDeleting(true)} />
            ) : (
              <Banner tone="warn">
                <T bold style={{ color: c.danger }}>Delete your account and all cloud backups for good.</T>
                <T size={13} style={{ marginBottom: 8 }}>Workouts saved on this phone stay. Any paid plan is cancelled too.</T>
                <Field label="Your password" value={password} onChangeText={setPassword} secureTextEntry autoCapitalize="none" />
                <Row>
                  <Button
                    title="Delete forever"
                    kind="danger"
                    style={{ flex: 1 }}
                    disabled={!password}
                    busy={busy === 'delete'}
                    onPress={() =>
                      run('delete', async () => {
                        await cloud.deleteAccount(password);
                        setDeleting(false);
                        setPassword('');
                        return 'Account and cloud backups deleted. Your data stays on this phone.';
                      })
                    }
                  />
                  <Button title="Cancel" kind="secondary" style={{ flex: 1 }} onPress={() => setDeleting(false)} />
                </Row>
                <Button title="Forgot password? Delete on the website" kind="ghost" small onPress={() => Linking.openURL(cloud.page('/account/delete'))} />
              </Banner>
            )}
          </>
        ) : cloud.pendingCode ? (
          <Row>
            <Button title="Open the sign-in page again" style={{ flex: 1 }} onPress={signIn} />
            <Button title="Cancel" kind="secondary" onPress={() => { cloud.cancelSignIn(); refresh(); }} />
          </Row>
        ) : (
          <Button title="Create a free account or log in" busy={busy === 'signin'} onPress={signIn} />
        )}
      </View>
      <GoldRule style={{ marginVertical: 12 }} />
      <Row>
        <Button title="Privacy policy" kind="ghost" small onPress={() => Linking.openURL(cloud.page('/privacy'))} />
        <Button title="Terms" kind="ghost" small onPress={() => Linking.openURL(cloud.page('/terms'))} />
      </Row>
    </Card>
  );
}

function Appearance() {
  const { pref, setPref } = useTheme();
  return (
    <Card title="Appearance">
      <Segmented<ThemePref>
        options={[{ value: 'system', label: 'Automatic' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]}
        value={pref}
        onChange={setPref}
      />
    </Card>
  );
}

function Prilepin() {
  const { c } = useTheme();
  const labels = ['Under 70%', '70-80%', '80-90%', '90%+'];
  return (
    <Card title="Prilepin's chart">
      <Row style={{ paddingBottom: 4, borderBottomWidth: 1, borderBottomColor: c.borderSoft }}>
        <T size={11} muted style={{ flex: 1.2 }}>INTENSITY</T>
        <T size={11} muted style={{ flex: 1 }}>REPS/SET</T>
        <T size={11} muted style={{ flex: 1 }}>OPTIMAL</T>
        <T size={11} muted style={{ flex: 1 }}>RANGE</T>
      </Row>
      {ZONES.map((z, i) => (
        <Row key={i} style={{ paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: c.borderSoft }}>
          <T bold style={{ flex: 1.2 }}>{labels[i]}</T>
          <T style={{ flex: 1 }}>{z.repsPerSet[0]}-{z.repsPerSet[1]}</T>
          <T style={{ flex: 1 }}>{z.optimalTotal}</T>
          <T style={{ flex: 1 }}>{z.totalRange[0]}-{z.totalRange[1]}</T>
        </Row>
      ))}
      <T size={13} muted style={{ marginTop: 8 }}>Total reps per lift per session by intensity. Every loaded session in the program follows it.</T>
    </Card>
  );
}

function About() {
  return (
    <T size={12} muted style={{ textAlign: 'center', marginTop: 4 }}>
      RuskiMaxxing {Constants.expoConfig?.version ?? ''} · free 1-year strength, mass and power program
    </T>
  );
}
