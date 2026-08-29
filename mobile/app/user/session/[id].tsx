import { useLocalSearchParams } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { ScrollView, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import type { SessionDetail } from '@/api/types';
import { useSettings } from '@/store/settings';
import { spacing, useTheme } from '@/theme';
import { Body, Caption, Card, ErrorNote, Heading, Loading, OutcomeBadge, Row, Screen, StatTile } from '@/ui/kit';
import { formatDateTime, formatMinutes, formatTemp } from '@/util/format';

const FLAG_LABEL: Record<string, string> = {
  SESSION_START: '세션 시작',
  WARMUP_DONE: '센서 워밍업 종료 · 가온 시작',
  HR_BASELINE: '안정심박수 확정',
  HR_BASELINE_FALLBACK: '안정심박수 측정 실패(기본값 사용)',
  SLEEP_ONSET: '입면 판정',
  COOLDOWN_START: '가온 유지 시작',
  NO_ONSET: '60분 미입면',
  SESSION_DONE: '세션 종료',
  FAULT: '안전 정지(FAULT)',
  POWER_OFF: '기기 전원 종료',
  RESULT: '탐색 결과',
};

/** 세션 상세 — 결과 요약과 기기 이벤트 타임라인. */
export default function SessionDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { settings } = useSettings();
  const t = useTheme();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        setDetail(await api.sessionDetail(settings.serverUrl, Number(id)));
      } catch (e) {
        setError((e as ApiError).message);
      }
    })();
  }, [id, settings.serverUrl]);

  if (error) {
    return (
      <Screen>
        <View style={{ padding: spacing.lg }}>
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

  const { session, samples, events } = detail;
  const skinValues = samples.map((s) => s.skin_c).filter((v): v is number => v !== null);
  const dutyValues = samples.map((s) => s.duty_pct).filter((v): v is number => v !== null);
  const peakSkin = skinValues.length ? Math.max(...skinValues) : null;
  const avgDuty = dutyValues.length ? dutyValues.reduce((a, b) => a + b, 0) / dutyValues.length : null;
  const faults = samples.filter((s) => s.safety_state && s.safety_state !== 'NORMAL').length;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg }}>
        <Card>
          <Row style={{ alignItems: 'center' }}>
            <Heading>{formatDateTime(session.started_at)}</Heading>
            <View style={{ flex: 1 }} />
            <OutcomeBadge outcome={session.outcome} />
          </Row>
          <Row>
            <StatTile label="잠들기까지" value={formatMinutes(session.sol_min)} unit="분" />
            <StatTile label="목표 온도" value={formatTemp(session.target_temp_c)} />
          </Row>
          <Row>
            <StatTile
              label="안정심박수"
              value={session.resting_bpm ? session.resting_bpm.toFixed(0) : '-'}
              unit="BPM"
            />
            <StatTile
              label="입면 기준"
              value={session.threshold_bpm ? session.threshold_bpm.toFixed(0) : '-'}
              unit="BPM"
            />
          </Row>
          <Caption>{`종료 ${formatDateTime(session.ended_at)} · 기기 ${session.device_id}`}</Caption>
        </Card>

        <Card>
          <Heading>측정 요약</Heading>
          <Row>
            <StatTile label="기록 샘플" value={String(samples.length)} unit="개" />
            <StatTile label="최고 피부온도" value={peakSkin === null ? '-' : peakSkin.toFixed(1)} unit="℃" />
          </Row>
          <Row>
            <StatTile label="평균 히터 출력" value={avgDuty === null ? '-' : avgDuty.toFixed(0)} unit="%" />
            <StatTile label="안전 이상 구간" value={String(faults)} unit="초" />
          </Row>
        </Card>

        <Card>
          <Heading>기기 이벤트</Heading>
          {events.length === 0 ? <Body muted>기록된 이벤트가 없습니다.</Body> : null}
          {events.map((e) => (
            <View
              key={e.event_id}
              style={{ borderTopWidth: 1, borderTopColor: t.border, paddingTop: spacing.sm, gap: 2 }}>
              <Body>{FLAG_LABEL[e.flag] ?? e.flag}</Body>
              <Caption>
                {`${formatDateTime(e.recorded_at)}${
                  e.v1 !== null ? ` · ${e.v1.toFixed(1)}${e.v2 !== null ? ` / ${e.v2.toFixed(1)}` : ''}` : ''
                }`}
              </Caption>
            </View>
          ))}
        </Card>
      </ScrollView>
    </Screen>
  );
}
