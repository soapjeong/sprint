import React, { useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { NOTE_OPTIONS, type NoteCode } from '@/api/types';
import { spacing, useTheme } from '@/theme';
import { Body, Button, Caption, Heading } from './kit';

/** 별 5개 입력. 색이 아니라 채워짐/빈 별 모양으로 구분하고, 선택값을 글자로도 알린다. */
export function StarRating({
  value,
  onChange,
  size = 38,
}: {
  value: number;
  onChange: (v: number) => void;
  size?: number;
}) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: 'row', gap: spacing.xs }}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Pressable
          key={n}
          onPress={() => onChange(n)}
          hitSlop={8}
          accessibilityRole="radio"
          accessibilityState={{ selected: value === n }}
          accessibilityLabel={`별 ${n}점`}
          style={({ pressed }) => ({ opacity: pressed ? 0.6 : 1, padding: 2 })}>
          <Text style={{ fontSize: size, color: n <= value ? t.warning : t.textMuted, lineHeight: size * 1.15 }}>
            {n <= value ? '★' : '☆'}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

const RATING_LABEL = ['', '많이 뒤척였어요', '별로였어요', '보통이었어요', '잘 잤어요', '아주 푹 잤어요'];

/**
 * 아침 수면 평가 카드.
 * 별점을 먼저 매기고, 그다음 특이사항을 고르면 저장할 수 있다(요구 흐름 그대로).
 */
export function SleepReviewCard({
  dateLabel,
  onSubmit,
  submitting,
  error,
}: {
  dateLabel: string;
  onSubmit: (rating: number, note: NoteCode, text: string) => void;
  submitting?: boolean;
  error?: string;
}) {
  const t = useTheme();
  const [rating, setRating] = useState(0);
  const [note, setNote] = useState<NoteCode | null>(null);
  const [text, setText] = useState('');

  const needsText = note === 'other';
  const canSubmit = rating > 0 && note !== null && (!needsText || text.trim().length > 0);

  return (
    <View style={{ gap: spacing.md }}>
      <Heading>어젯밤 수면은 어땠나요?</Heading>
      <Caption>{dateLabel} 세션</Caption>

      <View style={{ gap: spacing.xs }}>
        <StarRating value={rating} onChange={setRating} />
        <Caption>{rating > 0 ? RATING_LABEL[rating] : '별을 눌러 점수를 매겨주세요.'}</Caption>
      </View>

      {rating > 0 ? (
        <View style={{ gap: spacing.sm }}>
          <Body>특이사항을 골라주세요.</Body>
          {NOTE_OPTIONS.map((opt) => {
            const selected = note === opt.code;
            return (
              <Pressable
                key={opt.code}
                onPress={() => setNote(opt.code)}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                style={({ pressed }) => ({
                  flexDirection: 'row',
                  alignItems: 'center',
                  gap: spacing.sm,
                  paddingVertical: spacing.md,
                  paddingHorizontal: spacing.md,
                  borderRadius: 10,
                  borderWidth: 1,
                  borderColor: selected ? t.accent : t.border,
                  backgroundColor: selected ? t.surfaceAlt : 'transparent',
                  opacity: pressed ? 0.7 : 1,
                  minHeight: 48,
                })}>
                <View
                  style={{
                    width: 20,
                    height: 20,
                    borderRadius: 10,
                    borderWidth: 2,
                    borderColor: selected ? t.accent : t.textMuted,
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                  {selected ? (
                    <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: t.accent }} />
                  ) : null}
                </View>
                <Text style={{ color: t.textPrimary, fontSize: 15, flexShrink: 1 }}>{opt.label}</Text>
              </Pressable>
            );
          })}

          {needsText ? (
            <TextInput
              value={text}
              onChangeText={setText}
              placeholder="어떤 일이 있었나요? (예: 야근, 감기)"
              placeholderTextColor={t.textMuted}
              maxLength={200}
              style={{
                borderWidth: 1,
                borderColor: t.border,
                backgroundColor: t.surfaceAlt,
                borderRadius: 10,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.md,
                color: t.textPrimary,
                fontSize: 15,
              }}
            />
          ) : null}
        </View>
      ) : null}

      {error ? <Caption>{error}</Caption> : null}

      <Button
        label="기록 저장"
        onPress={() => note && onSubmit(rating, note, text.trim())}
        disabled={!canSubmit}
        loading={submitting}
      />
      {rating > 0 && note === null ? <Caption>특이사항까지 골라야 저장할 수 있어요.</Caption> : null}
    </View>
  );
}

/** 이미 남긴 평가를 보여주는 한 줄 */
export function ReviewSummary({
  rating,
  noteCode,
  noteText,
}: {
  rating: number | null;
  noteCode: string | null;
  noteText: string | null;
}) {
  if (!rating) return null;
  const label = NOTE_OPTIONS.find((o) => o.code === noteCode)?.label ?? '-';
  const suffix = noteCode === 'other' && noteText ? ` (${noteText})` : '';
  return <Caption>{`${'★'.repeat(rating)}${'☆'.repeat(5 - rating)} · ${label}${suffix}`}</Caption>;
}
