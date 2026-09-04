import { LinearGradient } from 'expo-linear-gradient';
import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  View,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Circle, Path } from 'react-native-svg';
import { radius, shadow, spacing, theme } from '@/theme';
import { Text, TextInput } from './typography';

/** 밤하늘 배경 — 위쪽이 살짝 밝고 아래로 짙어진다. */
export function Screen({ children, edges = true }: { children: React.ReactNode; edges?: boolean }) {
  const insets = useSafeAreaInsets();
  return (
    <LinearGradient colors={[theme.bgTop, theme.bg, theme.bgDeep]} style={{ flex: 1 }}>
      <View style={{ flex: 1, paddingTop: edges ? insets.top : 0 }}>{children}</View>
    </LinearGradient>
  );
}

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return (
    <View
      style={[
        {
          backgroundColor: theme.surface,
          borderRadius: radius.card,
          padding: spacing.xl,
          gap: spacing.md,
          borderWidth: StyleSheet.hairlineWidth,
          borderColor: theme.border,
        },
        shadow.card,
        style,
      ]}>
      {children}
    </View>
  );
}

/** 카드 안에 들어가는 둥근 타일 (목표 온도 / 히터 상태) */
export function Tile({
  label,
  children,
  tint,
  style,
}: {
  label: string;
  children: React.ReactNode;
  tint?: string;
  style?: ViewStyle;
}) {
  return (
    <View
      style={[
        {
          flex: 1,
          backgroundColor: tint ?? theme.surfaceAlt,
          borderRadius: radius.tile,
          padding: spacing.lg,
          gap: 6,
          minHeight: 120,
        },
        style,
      ]}>
      <Text style={{ color: theme.textSecondary, fontSize: 13, fontWeight: '600' }}>{label}</Text>
      {children}
    </View>
  );
}

export function Title({ children }: { children: React.ReactNode }) {
  return <Text style={{ color: theme.textPrimary, fontSize: 26, fontWeight: '800' }}>{children}</Text>;
}
export function Heading({ children }: { children: React.ReactNode }) {
  return <Text style={{ color: theme.textPrimary, fontSize: 17, fontWeight: '700' }}>{children}</Text>;
}
export function Body({ children, muted }: { children: React.ReactNode; muted?: boolean }) {
  return (
    <Text style={{ color: muted ? theme.textSecondary : theme.textPrimary, fontSize: 15, lineHeight: 22 }}>
      {children}
    </Text>
  );
}
export function Caption({ children, color }: { children: React.ReactNode; color?: string }) {
  return <Text style={{ color: color ?? theme.textMuted, fontSize: 13, lineHeight: 19 }}>{children}</Text>;
}

export function Row({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[{ flexDirection: 'row', gap: spacing.md }, style]}>{children}</View>;
}

export function Field({ label, hint, ...props }: TextInputProps & { label: string; hint?: string }) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={{ color: theme.textSecondary, fontSize: 13, fontWeight: '700' }}>{label}</Text>
      <TextInput
        placeholderTextColor={theme.textMuted}
        autoCapitalize="none"
        autoCorrect={false}
        {...props}
        style={{
          backgroundColor: theme.surfaceAlt,
          borderRadius: radius.tile,
          paddingHorizontal: spacing.lg,
          paddingVertical: 15,
          color: theme.textPrimary,
          fontSize: 16,
          borderWidth: StyleSheet.hairlineWidth,
          borderColor: theme.border,
        }}
      />
      {hint ? <Caption>{hint}</Caption> : null}
    </View>
  );
}

/** 알약 모양 버튼 */
export function Button({
  label,
  onPress,
  variant = 'primary',
  loading,
  disabled,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'ghost' | 'soft';
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
}) {
  const off = disabled || loading;
  // 비활성 상태는 투명도만 낮추면 탁해 보여서, 아예 가라앉은 색으로 바꾼다
  const bg = off && variant === 'primary'
    ? theme.surfaceAlt
    : variant === 'primary' ? theme.moon : variant === 'soft' ? theme.surfaceAlt : 'transparent';
  const fg = off && variant === 'primary'
    ? theme.textMuted
    : variant === 'primary' ? theme.onAccent : theme.textPrimary;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={off}
      style={({ pressed }) => [
        {
          backgroundColor: bg,
          borderRadius: radius.pill,
          paddingVertical: 15,
          paddingHorizontal: spacing.xl,
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: 52,
          opacity: off ? 0.9 : pressed ? 0.85 : 1,
          borderWidth: variant === 'ghost' ? StyleSheet.hairlineWidth : 0,
          borderColor: theme.border,
        },
        style,
      ]}>
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <Text style={{ color: fg, fontSize: 16, fontWeight: '700' }}>{label}</Text>
      )}
    </Pressable>
  );
}

/** 작은 알약 (헤더의 "기록" 버튼처럼) */
export function PillButton({
  label,
  onPress,
  icon,
}: {
  label: string;
  onPress: () => void;
  icon?: React.ReactNode;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        backgroundColor: theme.surface,
        borderRadius: radius.pill,
        paddingVertical: 10,
        paddingHorizontal: spacing.lg,
        borderWidth: StyleSheet.hairlineWidth,
        borderColor: theme.border,
        opacity: pressed ? 0.7 : 1,
      })}>
      {icon}
      <Text style={{ color: theme.textPrimary, fontSize: 14, fontWeight: '700' }}>{label}</Text>
    </Pressable>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <View
      style={{
        backgroundColor: theme.surface,
        borderLeftWidth: 4,
        borderLeftColor: theme.coral,
        borderRadius: radius.tile,
        padding: spacing.lg,
      }}>
      <Text style={{ color: theme.textPrimary, fontSize: 14, lineHeight: 20 }}>{message}</Text>
    </View>
  );
}

export function Loading({ label = '불러오는 중…' }: { label?: string }) {
  return (
    <View style={{ padding: spacing.xxl, alignItems: 'center', gap: spacing.sm }}>
      <ActivityIndicator color={theme.moon} />
      <Caption>{label}</Caption>
    </View>
  );
}

// ---------------------------------------------------------------- 아이콘
export function MoonIcon({ size = 40 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 48 48">
      <Circle cx="24" cy="24" r="24" fill={theme.bgDeep} />
      <Path
        d="M30 12a12 12 0 1 0 6 22 13 13 0 0 1-6-22z"
        fill={theme.moon}
      />
      <Circle cx="34" cy="14" r="1.8" fill={theme.star} />
      <Circle cx="39" cy="20" r="1.2" fill={theme.star} />
      <Circle cx="14" cy="34" r="1.2" fill={theme.star} />
    </Svg>
  );
}

export function PowerIcon({ size = 46, color = theme.onAccent }: { size?: number; color?: string }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      <Path
        d="M12 3v9"
        stroke={color}
        strokeWidth={2.4}
        strokeLinecap="round"
      />
      <Path
        d="M6.5 6.8a8 8 0 1 0 11 0"
        stroke={color}
        strokeWidth={2.4}
        strokeLinecap="round"
        fill="none"
      />
    </Svg>
  );
}

export function CalendarIcon({ size = 16, color = theme.textSecondary }: { size?: number; color?: string }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      <Path
        d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5v-11z"
        stroke={color}
        strokeWidth={1.8}
        fill="none"
      />
      <Path d="M8 3v3M16 3v3M4.5 9.5h15" stroke={color} strokeWidth={1.8} strokeLinecap="round" />
    </Svg>
  );
}
