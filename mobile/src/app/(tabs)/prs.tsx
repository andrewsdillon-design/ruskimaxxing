// PR board: your total, every lift's best estimated 1RM and rep maxes, and where your jumps stand.
import { View } from 'react-native';
import { Card, Display, GoldRule, Row, Screen, T, Tag } from '../../components/ui';
import { CATALOG, JUMP_STANDARDS, jumpLevel, jumpTargets, MAIN } from '../../core/exercises';
import { fmt0, fmtG } from '../../core/pyfmt';
import { bestE1rm, e1rm, repMaxes, type LogEntry } from '../../core/tracking';
import { heightUnit } from '../../core/workout';
import { useApp } from '../../state/app';
import { useTheme } from '../../theme';

const SHOWN_RMS = [1, 3, 5, 10];

function LiftRow({ name, entries }: { name: string; entries: LogEntry[] }) {
  const { c } = useTheme();
  const best = bestE1rm(entries, name);
  const rms = repMaxes(entries, name);
  return (
    <View style={{ paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.borderSoft }}>
      <Row style={{ justifyContent: 'space-between' }}>
        <T bold>{name}</T>
        <T bold style={{ color: c.accent }}>{best ? `${fmt0(e1rm(best))} e1RM` : '—'}</T>
      </Row>
      <Row style={{ gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
        {SHOWN_RMS.filter((n) => rms.has(n)).map((n) => (
          <Tag key={n} label={`${n}RM ${fmtG(rms.get(n)!.weight)}`} color={c.gold} />
        ))}
        {!rms.size ? <T size={13} muted>No sets yet</T> : null}
      </Row>
    </View>
  );
}

export default function Prs() {
  const { c } = useTheme();
  const { store, cfg } = useApp();
  const entries = store.lifts();
  const hu = heightUnit(cfg);
  const logged = new Set(entries.filter((e) => e.done).map((e) => e.exercise));
  const mains = MAIN.map((n) => ({ name: n, best: bestE1rm(entries, n) }));
  const total = mains.reduce((t, m) => t + (m.best ? e1rm(m.best) : 0), 0);
  const others = [...CATALOG.values()].filter((e) => logged.has(e.name) && !(MAIN as readonly string[]).includes(e.name) && e.category !== 'plyo');
  const otherJumps = [...CATALOG.values()].filter((e) => e.category === 'plyo' && logged.has(e.name) && !(e.name in JUMP_STANDARDS));

  return (
    <Screen>
      <Card style={{ backgroundColor: c.header, borderColor: c.gold, alignItems: 'center' }}>
        <T size={12} style={{ color: c.tabInactive, letterSpacing: 1.2 }}>TOTAL · ESTIMATED 1RM</T>
        <Display size={40} color={c.headerText} style={{ marginTop: 4 }}>
          {total ? fmt0(total) : '—'}
        </Display>
        <T size={13} style={{ color: c.tabInactive }}>{cfg.unit} · squat + bench + deadlift + overhead press</T>
        <Row style={{ marginTop: 12, gap: 4 }}>
          {mains.map((m) => (
            <View key={m.name} style={{ flex: 1, alignItems: 'center' }}>
              <Display size={17} color={c.headerText}>{m.best ? fmt0(e1rm(m.best)) : '—'}</Display>
              <T size={11} style={{ color: c.tabInactive, textAlign: 'center' }}>{m.name.replace(' Press', '').replace('Overhead', 'OHP')}</T>
            </View>
          ))}
        </Row>
      </Card>

      <Card title="Main lifts">
        {MAIN.map((n) => (
          <LiftRow key={n} name={n} entries={entries} />
        ))}
      </Card>

      {others.length ? (
        <Card title="Variations & accessories">
          {others.map((e) => (
            <LiftRow key={e.name} name={e.name} entries={entries} />
          ))}
        </Card>
      ) : null}

      <Card title="Jump standards">
        {Object.keys(JUMP_STANDARDS).map((jump, i) => {
          const done = entries.filter((e) => e.exercise === jump && e.done);
          const best = done.length ? Math.max(...done.map((e) => e.weight)) : null;
          const level = jumpLevel(jump, best, cfg.height, hu);
          return (
            <View key={jump}>
              {i ? <GoldRule style={{ marginVertical: 12 }} /> : null}
              <Row style={{ justifyContent: 'space-between' }}>
                <T bold>{jump}</T>
                <Tag label={level} color={best ? c.danger : c.muted} />
              </Row>
              <T size={13} muted>{best ? `Best ${fmtG(best)} ${hu}` : 'Not tested yet'}</T>
              <Row style={{ gap: 6, marginTop: 8 }}>
                {jumpTargets(jump, cfg.height, hu).map(([lvl, desc, target]) => {
                  const reached = best !== null && target !== null && best >= target;
                  return (
                    <View
                      key={lvl}
                      style={{ flex: 1, borderWidth: 1, borderRadius: 5, padding: 6, alignItems: 'center',
                        borderColor: reached ? c.success : c.borderSoft, backgroundColor: reached ? c.success : c.field }}
                    >
                      <T size={11} bold style={{ color: reached ? '#FFF8E1' : c.text }}>{lvl}</T>
                      <T size={12} style={{ color: reached ? '#FFF8E1' : c.muted }}>{target !== null ? `${fmtG(target)} ${hu}` : 'height?'}</T>
                    </View>
                  );
                })}
              </Row>
              <T size={12} muted style={{ marginTop: 4 }}>
                {jumpTargets(jump, cfg.height, hu).map(([lvl, desc]) => `${lvl}: ${desc}`).join(' · ')}
              </T>
            </View>
          );
        })}
        {otherJumps.length ? <GoldRule style={{ marginVertical: 12 }} /> : null}
        {otherJumps.map((e) => (
          <T key={e.name} size={14}>
            {e.name}: best {fmtG(Math.max(...entries.filter((x) => x.exercise === e.name && x.done).map((x) => x.weight)))} {hu}
          </T>
        ))}
      </Card>
    </Screen>
  );
}
