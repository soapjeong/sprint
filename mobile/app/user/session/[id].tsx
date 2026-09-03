import { useLocalSearchParams, useRouter } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import { NOTE_OPTIONS, type Session, type SessionDetail } from '@/api/types';
import { useSettings } from '@/store/settings';
import { spacing, theme } from '@/theme';
import { HeartRateChart, OnsetTrendChart, TempBarChart, type Point, type TempBar } from '@/ui/charts';
import { Body, Caption, Card, ErrorNote, Heading, Loading, Row, Screen, Tile, Title } from '@/ui/kit';
import { formatClock, formatDate, formatMinutes, formatTemp } from '@/util/format';

/** 홈의 "수면 입면 분석" 카드를 누르면 오는 화면 — 그래프로 그날 밤을 보여준다. */
export default function SessionDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { settings } = useSettings();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [history, setHistory] = useState<Session[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      const token = settings.userToken ?? '';
      try {
        const [one, all] = await Promise.all([
          api.sessionDetail(settings.serverUrl, token, Number(id)),
          api.sessions(settings.serverUrl, token, settings.userId ?? '', 60),
        ]);
        setDetail(one);
        setHistory(all);
      } catch (e) {
        setError((e as ApiError).message);
      }
    })();
  }, [id, settings.serverUrl, settings.userToken, settings.userId]);

  if (error) {
    return (
      <Screen>
        <View style={{ padding: spacing.xl }}>
          <ErrorNote message={error} />
        </View>
      </Screen>
    );
  }
  if (!detail) {
    return (
      <Screen>
        <Loading />
      </Screen>
    );
  }

  const { session, samples } = detail;
  const note = NOTE_OPTIONS.find((o) => o.code === session.note_code);

  // 그날 밤 심박수 (기록이 촘촘하면 솎아낸다)
  const beats = samples.filter((s) => s.bpm !== null && s.bpm > 0);
  const stride = Math.max(1, Math.ceil(beats.length / 60));
  const hrPoints: Point[] = beats
    .filter((_, i) => i % stride === 0)
    .map((s) => ({ label: `${Math.round(s.elapsed_s / 60)}분`, value: s.bpm as number }));

  // 입면시간 변화 (성공한 밤만, 오래된 순)
  const onsets = history.filter((s) => s.outcome === 'onset' && s.sol_min !== null).slice().reverse();
  const trend: Point[] = onsets.map((s) => ({ label: formatDate(s.started_at), value: s.sol_min as number }));

  // 온도별 평균 입면시간
  const byTemp = new Map<number, { sum: number; count: number }>();
  onsets.forEach((s) => {
    if (s.target_temp_c === null) return;
    const cur = byTemp.get(s.target_temp_c) ?? { sum: 0, count: 0 };
    byTemp.set(s.target_temp_c, { sum: cur.sum + (s.sol_min ?? 0), count: cur.count + 1 });
  });
  const bars: TempBar[] = [...byTemp.entries()]
    .map(([temp, v]) => ({ temp, avg: v.sum / v.count, count: v.count }))
    .sort((a, b) => a.temp - b.temp);

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.xl, gap: spacing.lg, paddingBottom: spacing.xxl }}>
        <Row style={{ alignItems: 'center' }}>
          <Pressable onPress={() => router.back()} hitSlop={10}>
            <Text style={{ color: theme.moon, fontSize: 22, fontWeight: '700' }}>←</Text>
          </Pressable>
          <Title>수면 입면 분석</Title>
        </Row>

        <Card>
          <Heading>{formatDate(session.started_at)} 밤</Heading>
          <Row>
            <Tile label="입면시간">
              <Text style={{ color: theme.textPrimary, fontSize: 26, fontWeight: '800' }}>
                {session.outcome === 'onset' ? `${formatMinutes(session.sol_min)}분` : '-'}
              </Text>
            </Tile>
            <Tile label="잠든 시간">
              <Text style={{ color: theme.textPrimary, fontSize: 26, fontWeight: '800' }}>
                {formatClock(session.onset_at)}
              </Text>
            </Tile>
          </Row>
          <Row>
            <Tile label="목표 온도">
              <Text style={{ color: theme.star, fontSize: 22, fontWeight: '800' }}>
                {formatTemp(session.target_temp_c)}℃
              </Text>
            </Tile>
            <Tile label="안정심박수">
              <Text style={{ color: theme.textPrimary, fontSize: 22, fontWeight: '800' }}>
                {session.resting_bpm ? `${session.resting_bpm.toFixed(0)} BPM` : '-'}
              </Text>
            </Tile>
          </Row>
        </Card>

        <Card>
          <HeartRateChart points={hrPoints} threshold={session.threshold_bpm} />
        </Card>

        <Card>
          <OnsetTrendChart points={trend} />
        </Card>

        <Card>
          <TempBarChart bars={bars} />
        </Card>

        <Card>
          <Heading>내 평가</Heading>
          <Text style={{ color: theme.moon, fontSize: 22, fontWeight: '800' }}>
            {session.rating ? `${'★'.repeat(session.rating)}${'☆'.repeat(5 - session.rating)}` : '-'}
          </Text>
          <Body muted>
            {note ? note.label : '아직 평가를 남기지 않았어요'}
            {session.note_code === 'other' && session.note_text ? ` · ${session.note_text}` : ''}
          </Body>
        </Card>
      </ScrollView>
    </Screen>
  );
}
