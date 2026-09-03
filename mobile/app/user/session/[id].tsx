import { useLocalSearchParams, useRouter } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import { NOTE_OPTIONS, type SessionDetail } from '@/api/types';
import { useSettings } from '@/store/settings';
import { spacing, theme } from '@/theme';
import { Body, Caption, Card, ErrorNote, Heading, Loading, Row, Screen, Tile, Title } from '@/ui/kit';
import { formatClock, formatDate, formatMinutes, formatTemp } from '@/util/format';

/** 홈의 "자세히 보기 →" 로 들어오는 화면. */
export default function SessionDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { settings } = useSettings();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        setDetail(await api.sessionDetail(settings.serverUrl, settings.userToken ?? '', Number(id)));
      } catch (e) {
        setError((e as ApiError).message);
      }
    })();
  }, [id, settings.serverUrl, settings.userToken]);

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
  const skin = samples.map((s) => s.skin_c).filter((v): v is number => v !== null);
  const peak = skin.length ? Math.max(...skin) : null;
  const note = NOTE_OPTIONS.find((o) => o.code === session.note_code);

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.xl, gap: spacing.lg }}>
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
          <Heading>그날 밤 기록</Heading>
          <Row>
            <Tile label="최고 피부온도">
              <Text style={{ color: theme.textPrimary, fontSize: 22, fontWeight: '800' }}>
                {peak === null ? '-' : `${peak.toFixed(1)}℃`}
              </Text>
            </Tile>
            <Tile label="내 평가">
              <Text style={{ color: theme.moon, fontSize: 20, fontWeight: '800' }}>
                {session.rating ? `${'★'.repeat(session.rating)}${'☆'.repeat(5 - session.rating)}` : '-'}
              </Text>
              <Caption>{note ? note.label : '기록 없음'}</Caption>
            </Tile>
          </Row>
          {session.note_code === 'other' && session.note_text ? (
            <Body muted>{session.note_text}</Body>
          ) : null}
        </Card>
      </ScrollView>
    </Screen>
  );
}
