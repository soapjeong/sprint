import { useLocalSearchParams } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { ScrollView, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import type { AdminUserDetail } from '@/api/types';
import { useSettings } from '@/store/settings';
import { spacing, useTheme } from '@/theme';
import { TempBarChart } from '@/ui/charts';
import { ReviewSummary } from '@/ui/review';
import {
  Body, Caption, Card, ErrorNote, Heading, Loading, OutcomeBadge, Row, Screen, StatTile, Title,
} from '@/ui/kit';
import { formatDateTime, formatMinutes, formatTemp } from '@/util/format';

/** 관리자 — 특정 사용자 ID에 쌓인 세션 DB. */
export default function AdminUserScreen() {
  const { userId } = useLocalSearchParams<{ userId: string }>();
  const { settings } = useSettings();
  const t = useTheme();
  const [data, setData] = useState<AdminUserDetail | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      if (!settings.adminToken) {
        setError('관리자 토큰이 없습니다. 관리자 페이지에서 다시 접속하세요.');
        return;
      }
      try {
        setData(await api.adminUserDetail(settings.serverUrl, settings.adminToken, String(userId)));
      } catch (e) {
        setError((e as ApiError).message);
      }
    })();
  }, [userId, settings.serverUrl, settings.adminToken]);

  if (error) {
    return (
      <Screen>
        <View style={{ padding: spacing.lg }}>
          <ErrorNote message={error} />
        </View>
      </Screen>
    );
  }
  if (!data) {
    return (
      <Screen>
        <Loading />
      </Screen>
    );
  }

  const onsets = data.sessions.filter((s) => s.outcome === 'onset' && s.sol_min !== null);
  const byTemp = new Map<number, { sum: number; count: number }>();
  for (const s of onsets) {
    if (s.target_temp_c === null) continue;
    const cur = byTemp.get(s.target_temp_c) ?? { sum: 0, count: 0 };
    byTemp.set(s.target_temp_c, { sum: cur.sum + (s.sol_min ?? 0), count: cur.count + 1 });
  }
  const tempBars = [...byTemp.entries()]
    .map(([temp, v]) => ({ temp, avgSol: v.sum / v.count, count: v.count }))
    .sort((a, b) => a.temp - b.temp);
  const avgSol = onsets.length ? onsets.reduce((a, s) => a + (s.sol_min ?? 0), 0) / onsets.length : null;
  const rated = data.sessions.filter((s) => s.rating !== null);
  const avgRating = rated.length ? rated.reduce((a, s) => a + (s.rating ?? 0), 0) / rated.length : null;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg }}>
        <View style={{ gap: spacing.xs }}>
          <Title>{`${data.user.user_id}${data.user.name ? ` · ${data.user.name}` : ''}`}</Title>
          <Caption>{`가입 ${formatDateTime(data.user.created_at)}`}</Caption>
        </View>

        <Card>
          <Row>
            <StatTile label="세션" value={String(data.sessions.length)} unit="회" />
            <StatTile label="입면" value={String(onsets.length)} unit="회" />
            <StatTile label="평균 SOL" value={formatMinutes(avgSol)} unit="분" />
            <StatTile label="평균 별점" value={avgRating === null ? '-' : avgRating.toFixed(1)} unit="/ 5" />
          </Row>
          {data.devices.map((d) => (
            <Caption key={d.device_id}>
              {`기기 ${d.device_id}${d.label ? ` (${d.label})` : ''} · 마지막 통신 ${formatDateTime(d.last_seen_at)}`}
            </Caption>
          ))}
        </Card>

        {tempBars.length > 0 ? (
          <Card>
            <TempBarChart data={tempBars} />
          </Card>
        ) : null}

        <Card>
          <Heading>세션 기록</Heading>
          {data.sessions.length === 0 ? <Body muted>세션 데이터가 없습니다.</Body> : null}
          {data.sessions.map((s) => (
            <View
              key={s.session_id}
              style={{ borderTopWidth: 1, borderTopColor: t.border, paddingTop: spacing.sm, gap: 2 }}>
              <Row style={{ alignItems: 'center' }}>
                <Body>{`#${s.session_id} · ${formatDateTime(s.started_at)}`}</Body>
                <View style={{ flex: 1 }} />
                <OutcomeBadge outcome={s.outcome} />
              </Row>
              <Caption>
                {`목표 ${formatTemp(s.target_temp_c)} · SOL ${formatMinutes(s.sol_min)}분 · 안정심박 ${
                  s.resting_bpm ? s.resting_bpm.toFixed(0) : '-'
                } BPM · 기준 ${s.threshold_bpm ? s.threshold_bpm.toFixed(0) : '-'} BPM`}
              </Caption>
              <ReviewSummary rating={s.rating} noteCode={s.note_code} noteText={s.note_text} />
            </View>
          ))}
        </Card>

        <Card>
          <Heading>최근 이벤트</Heading>
          {data.recent_events.slice(0, 20).map((e) => (
            <Caption key={e.event_id}>
              {`${formatDateTime(e.recorded_at)} · ${e.flag}${e.v1 !== null ? ` (${e.v1.toFixed(1)})` : ''}`}
            </Caption>
          ))}
        </Card>
      </ScrollView>
    </Screen>
  );
}
