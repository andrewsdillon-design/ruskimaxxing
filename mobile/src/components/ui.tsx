// The building blocks (from the Orthodox Barbell Club app): parchment screens, ivory cards with gold borders,
// purple buttons, gold rules.
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import { fonts, useTheme } from '../theme';

export function Screen({
  children,
  refreshing,
  onRefresh,
  footer,
}: {
  children: ReactNode;
  refreshing?: boolean;
  onRefresh?: () => void;
  footer?: ReactNode;
}) {
  const { c } = useTheme();
  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView
        contentContainerStyle={styles.screen}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          onRefresh ? (
            <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={c.gold} colors={[c.gold]} />
          ) : undefined
        }
      >
        {children}
      </ScrollView>
      {footer}
    </View>
  );
}

export function T({
  children,
  style,
  muted,
  bold,
  size = 15,
  ...rest
}: TextProps & { muted?: boolean; bold?: boolean; size?: number }) {
  const { c } = useTheme();
  return (
    <Text
      {...rest}
      style={[
        { color: muted ? c.muted : c.text, fontFamily: bold ? fonts.bodyBold : fonts.body, fontSize: size, lineHeight: size * 1.35 },
        style,
      ]}
    >
      {children}
    </Text>
  );
}

/** Cinzel display type. */
export function Display({ children, size = 20, style, color }: { children: ReactNode; size?: number; style?: StyleProp<TextStyle>; color?: string }) {
  const { c } = useTheme();
  return (
    <Text style={[{ fontFamily: fonts.display, fontSize: size, color: color ?? c.accent, letterSpacing: 0.5 }, style]}>
      {children}
    </Text>
  );
}

/** A thin gold rule with a small diamond in the middle. */
export function GoldRule({ style }: { style?: StyleProp<ViewStyle> }) {
  const { c } = useTheme();
  return (
    <View style={[styles.ruleRow, style]}>
      <View style={[styles.ruleLine, { backgroundColor: c.border }]} />
      <View style={[styles.diamond, { borderColor: c.border, backgroundColor: c.card }]} />
      <View style={[styles.ruleLine, { backgroundColor: c.border }]} />
    </View>
  );
}

export function Card({
  title,
  right,
  children,
  style,
  accent,
}: {
  title?: ReactNode;
  right?: ReactNode;
  children?: ReactNode;
  style?: StyleProp<ViewStyle>;
  accent?: string;
}) {
  const { c } = useTheme();
  return (
    <View style={[styles.card, { backgroundColor: c.card, borderColor: accent ?? c.border }, style]}>
      {title ? (
        <>
          <View style={styles.cardHead}>
            {typeof title === 'string' ? <Display size={17} style={{ flex: 1 }}>{title}</Display> : <View style={{ flex: 1 }}>{title}</View>}
            {right}
          </View>
          <GoldRule style={{ marginBottom: 10 }} />
        </>
      ) : null}
      {children}
    </View>
  );
}

type ButtonKind = 'primary' | 'secondary' | 'danger' | 'ghost';

export function Button({
  title,
  onPress,
  kind = 'primary',
  disabled,
  busy,
  small,
  style,
}: {
  title: string;
  onPress?: () => void;
  kind?: ButtonKind;
  disabled?: boolean;
  busy?: boolean;
  small?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const { c } = useTheme();
  const look: Record<ButtonKind, { bg: string; fg: string; border: string }> = {
    primary: { bg: c.accent, fg: c.onAccent, border: c.gold },
    secondary: { bg: 'transparent', fg: c.accent, border: c.gold },
    danger: { bg: c.danger, fg: '#FFF8E1', border: c.danger },
    ghost: { bg: 'transparent', fg: c.accent, border: 'transparent' },
  };
  const l = look[kind];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      onPress={onPress}
      disabled={disabled || busy}
      style={({ pressed }) => [
        styles.button,
        small && styles.buttonSmall,
        { backgroundColor: l.bg, borderColor: l.border, opacity: disabled ? 0.45 : pressed ? 0.8 : 1 },
        style,
      ]}
    >
      {busy ? (
        <ActivityIndicator color={l.fg} />
      ) : (
        <Text style={{ color: l.fg, fontFamily: fonts.bodyBold, fontSize: small ? 13 : 15, letterSpacing: 0.3 }}>{title}</Text>
      )}
    </Pressable>
  );
}

export function Tag({ label, color }: { label: string; color: string }) {
  return (
    <View style={[styles.tag, { borderColor: color }]}>
      <Text style={{ color, fontFamily: fonts.bodyBold, fontSize: 10, letterSpacing: 0.8 }}>{label.toUpperCase()}</Text>
    </View>
  );
}

export function KindTag({ kind }: { kind: string }) {
  const { c } = useTheme();
  return <Tag label={kind === 'test' ? 'Test' : kind} color={c.kinds[kind] ?? c.muted} />;
}

export function Field({
  label,
  style,
  inputStyle,
  ...rest
}: TextInputProps & { label?: string; inputStyle?: StyleProp<TextStyle> }) {
  const { c } = useTheme();
  return (
    <View style={[{ marginBottom: 10 }, style as StyleProp<ViewStyle>]}>
      {label ? <T size={13} muted style={{ marginBottom: 4 }}>{label}</T> : null}
      <TextInput
        placeholderTextColor={c.muted}
        {...rest}
        style={[
          styles.input,
          { backgroundColor: c.field, borderColor: c.borderSoft, color: c.text, fontFamily: fonts.body },
          inputStyle,
        ]}
      />
    </View>
  );
}

export function Segmented<V extends string>({
  options,
  value,
  onChange,
  style,
}: {
  options: { value: V; label: string }[];
  value: V;
  onChange: (v: V) => void;
  style?: StyleProp<ViewStyle>;
}) {
  const { c } = useTheme();
  return (
    <View style={[styles.segmented, { borderColor: c.gold }, style]}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <Pressable
            key={o.value}
            accessibilityRole="tab"
            accessibilityState={{ selected: on }}
            onPress={() => onChange(o.value)}
            style={[styles.segment, { backgroundColor: on ? c.accent : 'transparent' }]}
          >
            <Text style={{ color: on ? c.onAccent : c.accent, fontFamily: fonts.bodyBold, fontSize: 13 }}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Chip({ label, on, onPress }: { label: string; on?: boolean; onPress?: () => void }) {
  const { c } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: !!on }}
      style={[styles.chip, { borderColor: c.gold, backgroundColor: on ? c.accent : c.card }]}
    >
      <Text style={{ color: on ? c.onAccent : c.text, fontFamily: fonts.bodySemi, fontSize: 13 }}>{label}</Text>
    </Pressable>
  );
}

export function Row({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[{ flexDirection: 'row', alignItems: 'center', gap: 8 }, style]}>{children}</View>;
}

export function Loading({ label }: { label?: string }) {
  const { c } = useTheme();
  return (
    <View style={styles.center}>
      <ActivityIndicator color={c.gold} size="large" />
      {label ? <T muted style={{ marginTop: 8 }}>{label}</T> : null}
    </View>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { c } = useTheme();
  return (
    <Card accent={c.danger}>
      <T style={{ color: c.danger }}>{error instanceof Error ? error.message : String(error)}</T>
      {onRetry ? <Button title="Try again" kind="secondary" small onPress={onRetry} style={{ marginTop: 10, alignSelf: 'flex-start' }} /> : null}
    </Card>
  );
}

export function Banner({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warn' | 'good' }) {
  const { c } = useTheme();
  const color = tone === 'warn' ? c.danger : tone === 'good' ? c.success : c.gold;
  return (
    <View style={[styles.banner, { borderColor: color, backgroundColor: c.card }]}>
      {typeof children === 'string' ? <T size={14}>{children}</T> : children}
    </View>
  );
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ flex: 1, alignItems: 'center' }}>
      <Display size={20}>{value}</Display>
      <T size={12} muted>{label}</T>
    </View>
  );
}

export const styles = StyleSheet.create({
  screen: { padding: 14, paddingBottom: 40, gap: 12 },
  card: { borderWidth: 1, borderRadius: 6, padding: 14 },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 },
  ruleRow: { flexDirection: 'row', alignItems: 'center' },
  ruleLine: { flex: 1, height: 1 },
  diamond: { width: 7, height: 7, borderWidth: 1, transform: [{ rotate: '45deg' }], marginHorizontal: 6 },
  button: { borderWidth: 1.5, borderRadius: 6, paddingVertical: 12, paddingHorizontal: 18, alignItems: 'center', justifyContent: 'center' },
  buttonSmall: { paddingVertical: 7, paddingHorizontal: 12 },
  tag: { borderWidth: 1, borderRadius: 3, paddingHorizontal: 6, paddingVertical: 1.5, alignSelf: 'flex-start' },
  input: { borderWidth: 1, borderRadius: 5, paddingHorizontal: 10, paddingVertical: 9, fontSize: 16 },
  segmented: { flexDirection: 'row', borderWidth: 1.5, borderRadius: 6, overflow: 'hidden' },
  segment: { flex: 1, paddingVertical: 8, alignItems: 'center' },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
  center: { padding: 40, alignItems: 'center', justifyContent: 'center' },
  banner: { borderWidth: 1, borderLeftWidth: 5, borderRadius: 6, padding: 12 },
});
