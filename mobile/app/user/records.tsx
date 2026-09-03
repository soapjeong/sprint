import { useRouter } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import { NOTE_OPTIONS, type Session } from '@/api/types';
import { useSettings } from '@/store/settings';
import { radius, spacing, theme } from '@/theme';
import { Body, Caption, Card, ErrorNote, Heading, Loading, Row, Screen, Title } from '@/ui/kit';
import { formatClock, formatDate, formatMinutes, formatTemp } from '@/util/format';

const OUTCOME: Record<string, { label: string; color: string }> = {
  onset: { label: '잘 잤어요', color: theme.mint },
  no_onset: { label: '못 잠들었어요', color: theme.amber },
  running: { label: '진행 중', color: theme.star },
  aborted: { label: '중단', color: theme.textMuted },
  fault: { label: '안전 정지', color: theme.coral },
};

/** 헤더의 [기록] 버튼으로 들어오는 화면 — 지난 밤들의 목록. */
export default function RecordsScreen() {
  const router = useRouter();
  const { settings } = useSettings();
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        setSessions(
          await api.sessions(settings.serverUrl, settings.userToken ?? '', settings.userId ?? '', 60),
        );
      } catch (e) {
        setError((e as ApiError).message);
      }
    })();
  }, [settings.serverUrl, settings.userToken, settings.userId]);

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.xl, gap: spacing.lg }}>
        <Row style={{ alignItems: 'center' }}>
          <Pressable onPress={() => router.back()} hitSlop={10}>
            <Text style={{ color: theme.moon, fontSize: 22, fontWeight: '700' }}>←</Text>
          </Pressable>
          <Title>기록</Title>
        </Row>

        {error ? <ErrorNote message={error} /> : null}
        {!sessions && !error ? <Loading /> : null}
        {sessions?.length === 0 ? (
          <Card>
            <Body muted>아직 기록이 없어요. 오늘 밤 시작을 눌러보세요.</Body>
          </Card>
        ) : null}

        {sessions?.map((s) => {
          const badge = OUTCOME[s.outcome] ?? OUTCOME.aborted;
          const note = NOTE_OPTIONS.find((o) => o.code === s.note_code);
          return (
            <Pressable
              key={s.session_id}
              onPress={() => router.push(`/user/session/${s.session_id}`)}
              style={({ pressed }) => ({ opacity: pressed ? 0.8 : 1 })}>
              <Card>
                <Row style={{ alignItems: 'center' }}>
                  <Heading>{formatDate(s.started_at)}</Heading>
                  <View style={{ flex: 1 }} />
                  <Row style={{ alignItems: 'center', gap: 6 }}>
                    <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: badge.color }} />
                    <Caption color={theme.textSecondary}>{badge.label}</Caption>
                  </Row>
                </Row>
                <Row style={{ alignItems: 'flex-end', gap: 6 }}>
                  <Text style={{ color: theme.textPrimary, fontSize: 24, fontWeight: '800' }}>
                    {s.outcome === 'onset' ? `${formatMinutes(s.sol_min)}분` : '-'}
                  </Text>
                  <Text style={{ color: theme.textSecondary, fontSize: 14, paddingBottom: 3 }}>
                    {s.outcome === 'onset' ? `· ${formatClock(s.onset_at)}에 잠듦` : '입면 기록 없음'}
                  </Text>
                </Row>
                <Caption>
                  {`목표 ${formatTemp(s.target_temp_c)}℃`}
                  {s.rating ? ` · ${'★'.repeat(s.rating)}${'☆'.repeat(5 - s.rating)}` : ''}
                  {note ? ` · ${note.label}` : ''}
                </Caption>
              </Card>
            </Pressable>
          );
        })}

        <View style={{ height: spacing.xxl, borderRadius: radius.tile }} />
      </ScrollView>
    </Screen>
  );
}
