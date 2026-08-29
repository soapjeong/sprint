import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';
import { spacing, useTheme } from '@/theme';

export function Screen({ children }: { children: React.ReactNode }) {
  const t = useTheme();
  return <View style={{ flex: 1, backgroundColor: t.bg }}>{children}</View>;
}

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  const t = useTheme();
  return (
    <View
      style={[
        {
          backgroundColor: t.surface,
          borderColor: t.border,
          borderWidth: StyleSheet.hairlineWidth,
          borderRadius: 14,
          padding: spacing.lg,
          gap: spacing.md,
        },
        style,
      ]}>
      {children}
    </View>
  );
}

export function Title({ children }: { children: React.ReactNode }) {
  const t = useTheme();
  return <Text style={{ color: t.textPrimary, fontSize: 22, fontWeight: '700' }}>{children}</Text>;
}

export function Heading({ children }: { children: React.ReactNode }) {
  const t = useTheme();
  return <Text style={{ color: t.textPrimary, fontSize: 16, fontWeight: '600' }}>{children}</Text>;
}

export function Body({ children, muted }: { children: React.ReactNode; muted?: boolean }) {
  const t = useTheme();
  return (
    <Text style={{ color: muted ? t.textSecondary : t.textPrimary, fontSize: 14, lineHeight: 20 }}>
      {children}
    </Text>
  );
}

export function Caption({ children }: { children: React.ReactNode }) {
  const t = useTheme();
  return <Text style={{ color: t.textMuted, fontSize: 12, lineHeight: 17 }}>{children}</Text>;
}

export function Field({
  label,
  hint,
  ...props
}: TextInputProps & { label: string; hint?: string }) {
  const t = useTheme();
  return (
    <View style={{ gap: spacing.xs }}>
      <Text style={{ color: t.textSecondary, fontSize: 13, fontWeight: '600' }}>{label}</Text>
      <TextInput
        placeholderTextColor={t.textMuted}
        autoCapitalize="none"
        autoCorrect={false}
        {...props}
        style={{
          borderWidth: StyleSheet.hairlineWidth,
          borderColor: t.border,
          backgroundColor: t.surfaceAlt,
          borderRadius: 10,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.md,
          color: t.textPrimary,
          fontSize: 15,
        }}
      />
      {hint ? <Caption>{hint}</Caption> : null}
    </View>
  );
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  loading,
  disabled,
}: {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'danger';
  loading?: boolean;
  disabled?: boolean;
}) {
  const t = useTheme();
  const bg = variant === 'primary' ? t.accent : variant === 'danger' ? t.danger : t.surfaceAlt;
  const fg = variant === 'secondary' ? t.textPrimary : t.onAccent;
  const off = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={off}
      style={({ pressed }) => ({
        backgroundColor: bg,
        opacity: off ? 0.5 : pressed ? 0.85 : 1,
        borderRadius: 10,
        paddingVertical: 14,
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 48,
      })}>
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <Text style={{ color: fg, fontSize: 15, fontWeight: '600' }}>{label}</Text>
      )}
    </Pressable>
  );
}

export function StatTile({ label, value, unit }: { label: string; value: string; unit?: string }) {
  const t = useTheme();
  return (
    <View
      style={{
        flex: 1,
        minWidth: 96,
        backgroundColor: t.surfaceAlt,
        borderRadius: 12,
        padding: spacing.md,
        gap: 2,
      }}>
      <Text style={{ color: t.textSecondary, fontSize: 12 }}>{label}</Text>
      <Text style={{ color: t.textPrimary, fontSize: 22, fontWeight: '700' }}>
        {value}
        {unit ? <Text style={{ fontSize: 13, fontWeight: '500' }}> {unit}</Text> : null}
      </Text>
    </View>
  );
}

const OUTCOME_LABEL: Record<string, string> = {
  onset: '입면 성공',
  no_onset: '미입면(60분)',
  running: '진행 중',
  aborted: '중단',
  fault: '안전 정지',
};

export function OutcomeBadge({ outcome }: { outcome: string }) {
  const t = useTheme();
  const color =
    outcome === 'onset' ? t.series2 : outcome === 'no_onset' ? t.warning : outcome === 'running' ? t.accent : t.textMuted;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
      <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: color }} />
      <Text style={{ color: t.textSecondary, fontSize: 12, fontWeight: '600' }}>
        {OUTCOME_LABEL[outcome] ?? outcome}
      </Text>
    </View>
  );
}

export function ErrorNote({ message }: { message: string }) {
  const t = useTheme();
  return (
    <View
      style={{
        backgroundColor: t.surfaceAlt,
        borderLeftWidth: 3,
        borderLeftColor: t.danger,
        borderRadius: 8,
        padding: spacing.md,
      }}>
      <Text style={{ color: t.textPrimary, fontSize: 13 }}>{message}</Text>
    </View>
  );
}

export function Loading({ label = '불러오는 중…' }: { label?: string }) {
  const t = useTheme();
  return (
    <View style={{ padding: spacing.xl, alignItems: 'center', gap: spacing.sm }}>
      <ActivityIndicator color={t.accent} />
      <Caption>{label}</Caption>
    </View>
  );
}

export function Row({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[{ flexDirection: 'row', gap: spacing.sm }, style]}>{children}</View>;
}
