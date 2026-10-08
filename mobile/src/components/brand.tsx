// The RuskiMaxxing emblem and the tab-bar icons (line icons drawn with react-native-svg).
import { Image, type ColorValue } from 'react-native';
import Svg, { Circle, Line, Path, Rect } from 'react-native-svg';

export function Emblem({ size = 72 }: { size?: number }) {
  return (
    <Image
      source={require('../../assets/emblem.png')}
      style={{ width: size, height: size }}
      accessibilityLabel="RuskiMaxxing emblem"
    />
  );
}

export type IconName = 'today' | 'program' | 'progress' | 'trophy' | 'body' | 'settings' | 'check';

/** Simple line icons: a barbell, a calendar, a chart, a trophy, a scale, a gear, a tick. */
export function Icon({ name, color, size = 24 }: { name: IconName; color: ColorValue; size?: number }) {
  const p = { stroke: color, strokeWidth: 1.8, fill: 'none', strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {name === 'today' && (
        <>
          <Line x1="2" y1="12" x2="22" y2="12" {...p} />
          <Rect x="4" y="6" width="3" height="12" rx="0.8" {...p} />
          <Rect x="17" y="6" width="3" height="12" rx="0.8" {...p} />
          <Rect x="7.5" y="8.5" width="1.8" height="7" rx="0.5" {...p} />
          <Rect x="14.7" y="8.5" width="1.8" height="7" rx="0.5" {...p} />
        </>
      )}
      {name === 'program' && (
        <>
          <Rect x="3" y="5" width="18" height="16" rx="1.5" {...p} />
          <Line x1="3" y1="10" x2="21" y2="10" {...p} />
          <Line x1="8" y1="3" x2="8" y2="7" {...p} />
          <Line x1="16" y1="3" x2="16" y2="7" {...p} />
          <Circle cx="8" cy="14.5" r="1" fill={color} />
          <Circle cx="12" cy="14.5" r="1" fill={color} />
          <Circle cx="16" cy="14.5" r="1" fill={color} />
        </>
      )}
      {name === 'progress' && (
        <>
          <Path d="M3 3 V21 H21" {...p} />
          <Path d="M6 16 L10 11 L13.5 13.5 L20 6" {...p} />
          <Path d="M16 6 H20 V10" {...p} />
        </>
      )}
      {name === 'trophy' && (
        <>
          <Path d="M7 4 H17 V9 A5 5 0 0 1 7 9 Z" {...p} />
          <Path d="M7 6 H4 V8 A3 3 0 0 0 7.5 11" {...p} />
          <Path d="M17 6 H20 V8 A3 3 0 0 1 16.5 11" {...p} />
          <Line x1="12" y1="14" x2="12" y2="18" {...p} />
          <Path d="M8 21 H16 L15 18 H9 Z" {...p} />
        </>
      )}
      {name === 'body' && (
        <>
          <Rect x="3" y="4" width="18" height="17" rx="3" {...p} />
          <Path d="M7 10 A5 5 0 0 1 17 10" {...p} />
          <Line x1="12" y1="10" x2="14" y2="7.5" {...p} />
        </>
      )}
      {name === 'settings' && (
        <>
          <Path
            d="M10.3 2.5h3.4l.5 2.6 1.9.8 2.2-1.5 2.4 2.4-1.5 2.2.8 1.9 2.6.5v3.4l-2.6.5-.8 1.9 1.5 2.2-2.4 2.4-2.2-1.5-1.9.8-.5 2.6h-3.4l-.5-2.6-1.9-.8-2.2 1.5-2.4-2.4 1.5-2.2-.8-1.9-2.6-.5v-3.4l2.6-.5.8-1.9-1.5-2.2 2.4-2.4 2.2 1.5 1.9-.8z"
            {...p}
          />
          <Circle cx="12" cy="12" r="3.2" {...p} />
        </>
      )}
      {name === 'check' && <Path d="M5 12.5 L10 17.5 L19 7" {...p} strokeWidth={2.6} />}
    </Svg>
  );
}
