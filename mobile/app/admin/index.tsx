import { useRouter } from 'expo-router';
import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import type { AdminUserRow } from '@/api/types';
import { useSettings } from '@/store/settings';
import { spacing, useTheme } from '@/theme';
import {
  Body, Button, Caption, Card, ErrorNote, Field, Heading, Loading, Row, Screen, StatTile, Title,
} from '@/ui/kit';
import { formatDateTime, formatMinutes } from '@/util/format';

/** 관리자 페이지 — ID별로 쌓인 데이터 현황. */
export default function AdminHomeScreen() {
  const router = useRouter();
  const t = useTheme();
  const { settings, update } = useSettings();
  const [token, setToken] = useState(settings.adminToken ?? '');
  const [rows, setRows] = useState<AdminUserRow[] | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (withToken: string) => {
      if (!withToken) return;
      setLoading(true);
      setError('');
      try {
        setRows(await api.adminUsers(settings.serverUrl, withToken));
      } catch (e) {
        const err = e as ApiError;
        setError(err.status === 401 ? '관리자 토큰이 올바르지 않습니다.' : err.message);
        setRows(null);
      } finally {
        setLoading(false);
      }
    },
    [settings.serverUrl],
  );

  useEffect(() => {
    if (settings.adminToken) load(settings.adminToken);
  }, [settings.adminToken, load]);

  async function signIn() {
    await update({ adminToken: token.trim() });
    await load(token.trim());
  }

  const totals = (rows ?? []).reduce(
    (acc, r) => ({
      sessions: acc.sessions + r.session_count,
      onsets: acc.onsets + r.onset_count,
    }),
    { sessions: 0, onsets: 0 },
  );

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg }}
        refreshControl={
          <RefreshControl refreshing={loading} onRefresh={() => load(token)} tintColor={t.accent} />
        }>
        <Title>관리자 페이지</Title>
        {error ? <ErrorNote message={error} /> : null}

        {rows === null ? (
          <Card>
            <Heading>관리자 인증</Heading>
            <Field
              label="관리자 토큰"
              value={token}
              onChangeText={setToken}
              placeholder="dev-admin-token"
              secureTextEntry
              hint="서버의 ADMIN_TOKEN 환경변수 값입니다."
            />
            <Button label="접속" onPress={signIn} loading={loading} />
          </Card>
        ) : (
          <>
            <Card>
              <Heading>전체 현황</Heading>
              <Row>
                <StatTile label="등록 사용자" value={String(rows.length)} unit="명" />
                <StatTile label="누적 세션" value={String(totals.sessions)} unit="회" />
                <StatTile label="입면 성공" value={String(totals.onsets)} unit="회" />
              </Row>
            </Card>

            <Card>
              <Heading>사용자 ID별 데이터</Heading>
              {rows.length === 0 ? <Body muted>아직 등록된 사용자가 없습니다.</Body> : null}
              {rows.map((r) => (
                <Pressable
                  key={r.user_id}
                  onPress={() => router.push(`/admin/${r.user_id}`)}
                  style={({ pressed }) => ({
                    borderTopWidth: 1,
                    borderTopColor: t.border,
                    paddingVertical: spacing.md,
                    gap: 4,
                    opacity: pressed ? 0.6 : 1,
                  })}>
                  <Row style={{ alignItems: 'center' }}>
                    <Body>{`${r.user_id}${r.name ? ` · ${r.name}` : ''}`}</Body>
                    <View style={{ flex: 1 }} />
                    <Caption>{`세션 ${r.session_count} / 입면 ${r.onset_count}`}</Caption>
                  </Row>
                  <Caption>
                    {`평균 ${formatMinutes(r.avg_sol_min)}분 · 별점 ${
                      r.avg_rating ? r.avg_rating.toFixed(1) : '-'
                    } · 기기 ${r.device_count}대 · 최근 ${formatDateTime(r.last_session_at)}`}
                  </Caption>
                </Pressable>
              ))}
            </Card>

            <Button
              label="로그아웃"
              variant="secondary"
              onPress={async () => {
                await update({ adminToken: null });
                setRows(null);
                setToken('');
              }}
            />
          </>
        )}
      </ScrollView>
    </Screen>
  );
}
