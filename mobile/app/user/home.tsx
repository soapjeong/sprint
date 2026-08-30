import { useFocusEffect, useRouter } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import type { NoteCode, UserSummary } from '@/api/types';
import { useSettings } from '@/store/settings';
import { spacing, useTheme } from '@/theme';
import { SolTrendChart, TempBarChart } from '@/ui/charts';
import { ReviewSummary, SleepReviewCard } from '@/ui/review';
import {
  Body, Button, Caption, Card, ErrorNote, Heading, Loading, OutcomeBadge, Row, Screen, StatTile, Title,
} from '@/ui/kit';
import { formatDate, formatDateTime, formatMinutes, formatTemp } from '@/util/format';

/** 사용자 페이지 — 내 세션 기록 요약. */
export default function UserHomeScreen() {
  const router = useRouter();
  const t = useTheme();
  const { settings, signOut } = useSettings();
  const [summary, setSummary] = useState<UserSummary | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState('');

  const load = useCallback(async () => {
    if (!settings.userId || !settings.userToken) return;
    setError('');
    try {
      setSummary(await api.summary(settings.serverUrl, settings.userToken, settings.userId));
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 401) {
        // 토큰이 만료됐으면 첫 화면으로 돌려보낸다
        await signOut();
        router.replace('/');
        return;
      }
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [settings.serverUrl, settings.userToken, settings.userId, signOut, router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  async function submitReview(rating: number, note: NoteCode, text: string) {
    const pending = summary?.pending_review;
    if (!pending) return;
    setReviewError('');
    setReviewing(true);
    try {
      await api.reviewSession(
        settings.serverUrl,
        settings.userToken ?? '',
        pending.session_id,
        rating,
        note,
        text,
      );
      await load();
    } catch (e) {
      setReviewError((e as ApiError).message);
    } finally {
      setReviewing(false);
    }
  }

  if (loading && !summary) {
    return (
      <Screen>
        <Loading />
      </Screen>
    );
  }

  const onsetSessions = (summary?.recent_sessions ?? [])
    .filter((s) => s.outcome === 'onset' && s.sol_min !== null)
    .slice()
    .reverse();

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={t.accent} />}>
        {error ? <ErrorNote message={error} /> : null}

        <View style={{ gap: spacing.xs }}>
          <Title>{summary?.user.name || settings.userId}</Title>
          <Caption>{`ID ${settings.userId} · 기기 ${settings.deviceId ?? '미등록'}`}</Caption>
        </View>

        {summary?.pending_review ? (
          <Card>
            <SleepReviewCard
              dateLabel={formatDateTime(summary.pending_review.started_at)}
              onSubmit={submitReview}
              submitting={reviewing}
              error={reviewError}
            />
          </Card>
        ) : null}

        <Card>
          <Heading>지금까지의 기록</Heading>
          <Row>
            <StatTile label="측정 세션" value={String(summary?.session_count ?? 0)} unit="회" />
            <StatTile label="입면 성공" value={String(summary?.onset_count ?? 0)} unit="회" />
          </Row>
          <Row>
            <StatTile label="평균 잠들기" value={formatMinutes(summary?.avg_sol_min)} unit="분" />
            <StatTile label="최단 기록" value={formatMinutes(summary?.best_sol_min)} unit="분" />
          </Row>
          <Row>
            <StatTile
              label="내가 매긴 평균 별점"
              value={summary?.avg_rating ? summary.avg_rating.toFixed(1) : '-'}
              unit="/ 5"
            />
          </Row>
          {summary?.best_temp_c != null ? (
            <Body muted>{`지금까지는 ${formatTemp(summary.best_temp_c)} 설정에서 가장 빨리 잠들었어요.`}</Body>
          ) : (
            <Body muted>입면 기록이 쌓이면 가장 잘 맞는 온도를 알려드려요.</Body>
          )}
        </Card>

        {onsetSessions.length > 0 ? (
          <Card>
            <SolTrendChart
              data={onsetSessions.map((s) => ({ label: formatDate(s.started_at), value: s.sol_min ?? 0 }))}
            />
          </Card>
        ) : null}

        {summary && summary.temp_stats.length > 0 ? (
          <Card>
            <TempBarChart
              data={summary.temp_stats.map((s) => ({
                temp: s.target_temp_c,
                avgSol: s.avg_sol_min,
                count: s.onset_count,
              }))}
            />
          </Card>
        ) : null}

        <Card>
          <Heading>최근 세션</Heading>
          {summary && summary.recent_sessions.length > 0 ? (
            summary.recent_sessions.map((s) => (
              <Pressable
                key={s.session_id}
                onPress={() => router.push(`/user/session/${s.session_id}`)}
                style={({ pressed }) => ({
                  paddingVertical: spacing.md,
                  borderTopWidth: 1,
                  borderTopColor: t.border,
                  opacity: pressed ? 0.6 : 1,
                  gap: 4,
                })}>
                <Row style={{ alignItems: 'center' }}>
                  <Body>{formatDateTime(s.started_at)}</Body>
                  <View style={{ flex: 1 }} />
                  <OutcomeBadge outcome={s.outcome} />
                </Row>
                <Caption>
                  {`목표 ${formatTemp(s.target_temp_c)} · 잠들기 ${formatMinutes(s.sol_min)}분 · 안정심박 ${
                    s.resting_bpm ? s.resting_bpm.toFixed(0) : '-'
                  } BPM`}
                </Caption>
                <ReviewSummary rating={s.rating} noteCode={s.note_code} noteText={s.note_text} />
              </Pressable>
            ))
          ) : (
            <Body muted>아직 기록이 없습니다. 기기에서 세션을 시작하면 여기에 쌓입니다.</Body>
          )}
        </Card>

        <Card>
          <Heading>내 기기</Heading>
          {summary?.devices.map((d) => (
            <View key={d.device_id} style={{ gap: 2 }}>
              <Body>{`${d.device_id}${d.label ? ` · ${d.label}` : ''}`}</Body>
              <Caption>{`마지막 통신 ${formatDateTime(d.last_seen_at)}`}</Caption>
            </View>
          ))}
          <Button
            label="로그아웃 · 다시 등록"
            variant="secondary"
            onPress={async () => {
              if (settings.userToken) {
                try {
                  await api.logOut(settings.serverUrl, settings.userToken);
                } catch {
                  // 서버에 못 알려도 로컬 로그아웃은 진행한다
                }
              }
              await signOut();
              router.replace('/');
            }}
          />
        </Card>

        <Button label="관리자 페이지" variant="secondary" onPress={() => router.push('/admin')} />
      </ScrollView>
    </Screen>
  );
}
