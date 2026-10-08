// Program: the whole year, a month at a time. Tap any day to open it.
import { useState } from 'react';
import { ScrollView, View } from 'react-native';
import { DayRow } from '../../components/DayRow';
import { Card, Chip, Display, Screen, T, Tag } from '../../components/ui';
import { fmtMonDay } from '../../core/dates';
import { MONTHS, monthLabel, monthOf, monthWeeks, session, sessionDate, weekLabel } from '../../core/program';
import { useApp } from '../../state/app';
import { useTheme } from '../../theme';

const PHASE_COLORS: Record<string, string> = { Test: 'danger', Deload: 'success', Taper: 'muted', Baseline: 'danger' };

export default function Program() {
  const { c } = useTheme();
  const { cfg, currentWeek } = useApp();
  const [month, setMonth] = useState(monthOf(currentWeek));
  const label = monthLabel(month).split(' - ');

  return (
    <Screen>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingVertical: 2 }}>
        {Array.from({ length: MONTHS + 1 }, (_, m) => (
          <Chip key={m} label={m === 0 ? 'Baseline' : `M${m}`} on={m === month} onPress={() => setMonth(m)} />
        ))}
      </ScrollView>

      <View>
        <Display size={22}>{label[0]}</Display>
        <T muted>{label.slice(1).join(' · ')}</T>
      </View>

      {monthWeeks(month).map((week) => {
        const s = session(week, 0);
        const tone = PHASE_COLORS[s.phase];
        const color = tone ? (c as unknown as Record<string, string>)[tone] : c.gold;
        return (
          <Card
            key={week}
            title={
              <View>
                <Display size={17}>{week === 0 ? 'Week 0' : `Week ${week}`}</Display>
                <T size={12} muted>
                  {weekLabel(week).split(' - ').slice(1).join(' · ')} · from {fmtMonDay(sessionDate(s, cfg.start))}
                </T>
              </View>
            }
            right={
              <View style={{ alignItems: 'flex-end', gap: 4 }}>
                <Tag label={s.phase} color={color} />
                {week === currentWeek ? <Tag label="This week" color={c.accent} /> : null}
              </View>
            }
            accent={week === currentWeek ? c.accent : undefined}
          >
            <View style={{ gap: 8 }}>
              {[0, 1, 2].map((d) => (
                <DayRow key={d} week={week} day={d} />
              ))}
            </View>
          </Card>
        );
      })}
    </Screen>
  );
}
