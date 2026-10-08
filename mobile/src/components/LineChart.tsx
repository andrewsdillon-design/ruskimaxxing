// A dated line chart drawn with react-native-svg: gold grid, purple (gold in dark mode) line, and optional
// dashed reference lines (e.g. jump standards).
import { useState } from 'react';
import { View } from 'react-native';
import Svg, { Circle, Line, Path, Text as SvgText } from 'react-native-svg';
import { fmtShort, toUtc } from '../core/dates';
import { fmtNum } from '../lib/format';
import { fonts, useTheme } from '../theme';
import { T } from './ui';

export interface Point {
  date: string;
  value: number;
}

export interface RefLine {
  label: string;
  value: number;
}

const PAD = { left: 44, right: 12, top: 12, bottom: 24 };

function niceRange(min: number, max: number): [number, number, number] {
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const span = max - min;
  const rough = span / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) ?? 10 * mag;
  return [Math.floor(min / step) * step, Math.ceil(max / step) * step, step];
}

export function LineChart({
  points,
  height = 190,
  unit = '',
  refLines = [],
  empty = 'Nothing logged yet.',
}: {
  points: Point[];
  height?: number;
  unit?: string;
  refLines?: RefLine[];
  empty?: string;
}) {
  const { c } = useTheme();
  const [width, setWidth] = useState(0);
  const data = [...points].sort((a, b) => a.date.localeCompare(b.date));
  if (data.length === 0) return <T muted style={{ paddingVertical: 24, textAlign: 'center' }}>{empty}</T>;
  const times = data.map((p) => toUtc(p.date).getTime());
  const t0 = times[0];
  const t1 = times[times.length - 1] === t0 ? t0 + 86400000 : times[times.length - 1];
  const values = [...data.map((p) => p.value), ...refLines.map((r) => r.value)];
  // at least ~10% of the value on the axis, so a 2.5 lb change doesn't look like a cliff
  const vMin = Math.min(...values);
  const vMax = Math.max(...values);
  const pad = Math.max(0, Math.abs(vMax) * 0.1 - (vMax - vMin)) / 2;
  const [lo, hi, step] = niceRange(Math.max(vMin >= 0 ? 0 : -Infinity, vMin - pad), vMax + pad);
  const w = Math.max(width - PAD.left - PAD.right, 1);
  const h = height - PAD.top - PAD.bottom;
  const x = (t: number) => PAD.left + ((t - t0) / (t1 - t0)) * w;
  const y = (v: number) => PAD.top + h - ((v - lo) / (hi - lo)) * h;
  const line = data.map((p, i) => `${i ? 'L' : 'M'}${x(times[i]).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
  const area = `${line} L${x(times[times.length - 1]).toFixed(1)},${PAD.top + h} L${x(t0).toFixed(1)},${PAD.top + h} Z`;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(v);
  const last = data[data.length - 1];

  return (
    <View
      onLayout={(e) => setWidth(e.nativeEvent.layout.width)}
      accessible
      accessibilityLabel={`Chart from ${fmtShort(data[0].date)} to ${fmtShort(last.date)}, latest ${fmtNum(last.value)} ${unit}`}
    >
      {width > 0 ? (
        <Svg width={width} height={height}>
          {ticks.map((v) => (
            <Line key={`g${v}`} x1={PAD.left} x2={PAD.left + w} y1={y(v)} y2={y(v)} stroke={c.chartGrid} strokeWidth={1} />
          ))}
          {ticks.map((v) => (
            <SvgText key={`t${v}`} x={PAD.left - 6} y={y(v) + 4} fontSize={10} fill={c.muted} textAnchor="end" fontFamily={fonts.body}>
              {fmtNum(v)}
            </SvgText>
          ))}
          {refLines.map((r) => (
            <Line key={`r${r.label}`} x1={PAD.left} x2={PAD.left + w} y1={y(r.value)} y2={y(r.value)} stroke={c.gold} strokeWidth={1} strokeDasharray="4 4" />
          ))}
          {refLines.map((r) => (
            <SvgText key={`rl${r.label}`} x={PAD.left + w - 2} y={y(r.value) - 3} fontSize={9} fill={c.muted} textAnchor="end" fontFamily={fonts.bodySemi}>
              {r.label}
            </SvgText>
          ))}
          <Path d={area} fill={c.chartFill} />
          <Path d={line} stroke={c.chartLine} strokeWidth={2.5} fill="none" strokeLinejoin="round" />
          {data.length <= 40 &&
            data.map((p, i) => <Circle key={i} cx={x(times[i])} cy={y(p.value)} r={3} fill={c.gold} stroke={c.chartLine} strokeWidth={1} />)}
          <SvgText x={PAD.left} y={height - 6} fontSize={10} fill={c.muted} fontFamily={fonts.body}>
            {fmtShort(data[0].date)}
          </SvgText>
          <SvgText x={PAD.left + w} y={height - 6} fontSize={10} fill={c.muted} textAnchor="end" fontFamily={fonts.body}>
            {fmtShort(last.date)}
          </SvgText>
        </Svg>
      ) : (
        <View style={{ height }} />
      )}
    </View>
  );
}
