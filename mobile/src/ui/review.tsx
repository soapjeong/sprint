import React, { useState } from 'react';
import { Modal, Pressable, ScrollView, View } from 'react-native';
import { Text, TextInput } from '@/ui/typography';
import { NOTE_OPTIONS, type NoteCode } from '@/api/types';
import { radius, shadow, spacing, theme } from '@/theme';
import { Button, Caption, Heading } from './kit';

const RATING_LABEL = ['', '많이 뒤척였어요', '별로였어요', '보통이었어요', '잘 잤어요', '아주 푹 잤어요'];

/** 별 5개 — 채워짐/빈 별 모양으로 구분하고 선택값을 글자로도 알린다. */
function StarRow({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <View style={{ flexDirection: 'row', gap: spacing.sm, justifyContent: 'center' }}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Pressable
          key={n}
          onPress={() => onChange(n)}
          hitSlop={10}
          accessibilityRole="radio"
          accessibilityState={{ selected: value === n }}
          accessibilityLabel={`별 ${n}점`}
          style={({ pressed }) => ({ opacity: pressed ? 0.6 : 1 })}>
          <Text style={{ fontSize: 40, lineHeight: 48, color: n <= value ? theme.moon : theme.surfaceSoft }}>
            {n <= value ? '★' : '☆'}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

/**
 * 어젯밤 수면 평가 — 입면이 확정됐을 때만 화면 가운데 뜨는 팝업 카드.
 * 별점을 먼저 매기고, 그다음 특이사항을 골라야 저장할 수 있다.
 */
export function SleepReviewPopup({
  visible,
  dateLabel,
  solMin,
  onSubmit,
  submitting,
  error,
}: {
  visible: boolean;
  dateLabel: string;
  solMin: number | null;
  onSubmit: (rating: number, note: NoteCode, text: string) => void;
  submitting?: boolean;
  error?: string;
}) {
  const [rating, setRating] = useState(0);
  const [note, setNote] = useState<NoteCode | null>(null);
  const [text, setText] = useState('');

  const needsText = note === 'other';
  const canSubmit = rating > 0 && note !== null && (!needsText || text.trim().length > 0);

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={() => undefined}>
      {/* 화면 한가운데 뜨는 카드 — 평가를 남겨야 닫힌다 */}
      <View
        style={{
          flex: 1,
          backgroundColor: 'rgba(4,7,26,0.78)',
          justifyContent: 'center',
          padding: spacing.lg,
        }}>
        <View
          style={[
            {
              backgroundColor: theme.surface,
              borderRadius: radius.sheet,
              padding: spacing.xl,
              gap: spacing.lg,
              maxHeight: '86%',
            },
            shadow.card,
          ]}>
          <View style={{ alignItems: 'center', gap: 4 }}>
            <Heading>어젯밤은 잘 주무셨나요?</Heading>
            <Caption>
              {solMin !== null ? `${dateLabel} · ${solMin.toFixed(0)}분 만에 잠들었어요` : dateLabel}
            </Caption>
          </View>

          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: spacing.lg }}>
            <View style={{ gap: 6 }}>
              <StarRow value={rating} onChange={setRating} />
              <Text style={{ color: theme.textSecondary, fontSize: 14, textAlign: 'center' }}>
                {rating > 0 ? RATING_LABEL[rating] : '별을 눌러 점수를 매겨주세요'}
              </Text>
            </View>

            {/* 특이사항은 처음부터 보이게 둔다(별점만 매기고 못 찾는 일이 없도록) */}
            <View style={{ gap: spacing.sm }}>
                <Text style={{ color: theme.textPrimary, fontSize: 15, fontWeight: '700' }}>
                  특이사항을 골라주세요
                </Text>
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
                        gap: spacing.md,
                        paddingVertical: 14,
                        paddingHorizontal: spacing.lg,
                        borderRadius: radius.tile,
                        backgroundColor: selected ? theme.surfaceSoft : theme.surfaceAlt,
                        borderWidth: 2,
                        borderColor: selected ? theme.moon : 'transparent',
                        opacity: pressed ? 0.75 : 1,
                      })}>
                      <View
                        style={{
                          width: 20,
                          height: 20,
                          borderRadius: 10,
                          borderWidth: 2,
                          borderColor: selected ? theme.moon : theme.textMuted,
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}>
                        {selected ? (
                          <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: theme.moon }} />
                        ) : null}
                      </View>
                      <Text style={{ color: theme.textPrimary, fontSize: 15, flexShrink: 1 }}>{opt.label}</Text>
                    </Pressable>
                  );
                })}

                {needsText ? (
                  <TextInput
                    value={text}
                    onChangeText={setText}
                    placeholder="어떤 일이 있었나요? (예: 야근, 감기)"
                    placeholderTextColor={theme.textMuted}
                    maxLength={200}
                    style={{
                      backgroundColor: theme.surfaceAlt,
                      borderRadius: radius.tile,
                      paddingHorizontal: spacing.lg,
                      paddingVertical: 14,
                      color: theme.textPrimary,
                      fontSize: 15,
                    }}
                  />
              ) : null}
            </View>

            {error ? <Caption color={theme.coral}>{error}</Caption> : null}
          </ScrollView>

          <View style={{ gap: spacing.sm }}>
            <Button
              label="기록 저장"
              onPress={() => note && onSubmit(rating, note, text.trim())}
              disabled={!canSubmit}
              loading={submitting}
            />
            {rating > 0 && note === null ? (
              <Caption>특이사항까지 골라야 저장할 수 있어요.</Caption>
            ) : null}
          </View>
        </View>
      </View>
    </Modal>
  );
}
