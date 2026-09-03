import { useFocusEffect, useRouter } from 'expo-router';
import * as Speech from 'expo-speech';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import type { DeviceStatus, NoteCode, PendingDevice, UserSummary } from '@/api/types';
import { useSettings } from '@/store/settings';
import { radius, shadow, spacing, theme } from '@/theme';
import { DeviceLinkSheet, LinkChip, describeLink } from '@/ui/device';
import {
  Body, CalendarIcon, Caption, Card, ErrorNote, Heading, Loading, MoonIcon, PillButton, PowerIcon, Row, Screen, Tile, Title,
} from '@/ui/kit';
import { SleepReviewPopup } from '@/ui/review';
import { formatClock, formatKoreanDate, formatMinutes, formatTemp } from '@/util/format';

const POLL_MS = 5000;
const TTS_LINE = '연결이 확인되었습니다. 수면케어를 시작합니다.';

export default function HomeScreen() {
  const router = useRouter();
  const { settings, update, signOut } = useSettings();

  const [summary, setSummary] = useState<UserSummary | null>(null);
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState('');

  // 기기 연결 시트
  const [sheetOpen, setSheetOpen] = useState(false);
  const [found, setFound] = useState<PendingDevice[] | null>(null);
  const [finding, setFinding] = useState(false);
  const [sheetError, setSheetError] = useState('');

  // 평가 팝업
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState('');
  const [skipped, setSkipped] = useState<number | null>(null);

  const spokenFor = useRef<number | null>(null);   // 세션당 한 번만 안내 음성을 낸다
  const token = settings.userToken ?? '';
  const deviceId = settings.deviceId;

  const load = useCallback(async () => {
    if (!settings.userId || !token) return;
    try {
      const next = await api.summary(settings.serverUrl, token, settings.userId);
      setSummary(next);
      setError('');
      if (deviceId) {
        const st = await api.deviceStatus(settings.serverUrl, token, deviceId);
        setStatus(st);
        // 워밍업이 끝나 센서값이 정상으로 들어오는 순간 = 음성 안내 시점
        if (st.session && st.warmup_done && spokenFor.current !== st.session.session_id) {
          spokenFor.current = st.session.session_id;
          Speech.speak(TTS_LINE, { language: 'ko-KR' });
          setNotice(TTS_LINE);
        }
      }
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 401) {
        await signOut();
        router.replace('/');
        return;
      }
      if (err.status === 404) {
        // 등록해 둔 기기가 서버에서 사라진 경우
        await update({ deviceId: null });
        setStatus(null);
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  }, [settings.serverUrl, settings.userId, token, deviceId, router, signOut, update]);

  useFocusEffect(
    useCallback(() => {
      load();
      const timer = setInterval(load, POLL_MS);
      return () => clearInterval(timer);
    }, [load]),
  );

  // 입면이 확정된 세션만 평가를 물어본다
  const pending = summary?.pending_review ?? null;
  const askReview = pending !== null && pending.outcome === 'onset' && pending.session_id !== skipped;
  useEffect(() => {
    setReviewOpen(askReview);
  }, [askReview]);

  async function findDevices() {
    setSheetError('');
    setFinding(true);
    try {
      setFound(await api.pendingDevices(settings.serverUrl, token));
    } catch (e) {
      setSheetError((e as ApiError).message);
    } finally {
      setFinding(false);
    }
  }

  async function pickDevice(id: string) {
    try {
      await api.registerDevice(settings.serverUrl, token, id, settings.userId ?? '', '');
      await update({ deviceId: id });
      setSheetOpen(false);
      load();
    } catch (e) {
      setSheetError((e as ApiError).message);
    }
  }

  async function toggleSession() {
    if (!deviceId) {
      setSheetOpen(true);
      findDevices();
      return;
    }
    setSending(true);
    setNotice('');
    try {
      const running = !!status?.session;
      await api.sendCommand(settings.serverUrl, token, deviceId, running ? 'abort' : 'start');
      setNotice(running ? '기기에 중지를 전달했어요.' : '기기에 시작을 전달했어요. 센서를 확인하는 중이에요…');
      if (!running) spokenFor.current = null;
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSending(false);
    }
  }

  async function submitReview(rating: number, note: NoteCode, text: string) {
    if (!pending) return;
    setReviewError('');
    setReviewing(true);
    try {
      await api.reviewSession(settings.serverUrl, token, pending.session_id, rating, note, text);
      setReviewOpen(false);
      load();
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

  const running = !!status?.session;
  const state = status?.session_state ?? null;
  const link = describeLink(status, !!deviceId);
  const last = summary?.recent_sessions.find((s) => s.outcome === 'onset') ?? null;
  const heaterText = !running
    ? '작동 안 함'
    : state === 'WARMUP'
      ? '센서 확인 중'
      : state === 'COOLDOWN'
        ? '가온 유지 중'
        : '가온 중';

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={{ padding: spacing.xl, gap: spacing.lg, paddingBottom: spacing.xxl }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.moon} />}>
        {/* 헤더 */}
        <Row style={{ alignItems: 'flex-start' }}>
          <View style={{ flex: 1, gap: 2 }}>
            <Title>DormX</Title>
            <Caption>{formatKoreanDate()}</Caption>
          </View>
          <PillButton label="기록" icon={<CalendarIcon />} onPress={() => router.push('/user/records')} />
        </Row>

        {error ? <ErrorNote message={error} /> : null}

        {/* 시작 카드 */}
        <Card style={{ alignItems: 'center', gap: spacing.lg }}>
          {/* 원과 아래 문구를 한 덩어리로 눌리게 한다 */}
          <Pressable
            onPress={toggleSession}
            disabled={sending}
            accessibilityRole="button"
            accessibilityLabel={running ? '수면 케어 중지' : '수면 케어 시작'}
            style={({ pressed }) => ({
              alignItems: 'center',
              gap: spacing.md,
              opacity: pressed || sending ? 0.8 : 1,
            })}>
            <View
              style={[
                {
                  width: 172,
                  height: 172,
                  borderRadius: 86,
                  alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor: running ? theme.moon : theme.surfaceAlt,
                  borderWidth: 2,
                  borderColor: running ? theme.moon : theme.surfaceSoft,
                },
                running ? shadow.glow : null,
              ]}>
              <PowerIcon size={54} color={running ? theme.onAccent : theme.textPrimary} />
            </View>
            <Heading>{running ? '누르면 중지돼요' : '눌러서 작동 시작'}</Heading>
          </Pressable>

          {/* 요구: start 버튼 옆 기기 연결 상태 (색으로 구분) */}
          <LinkChip
            view={link}
            onPress={() => {
              setSheetOpen(true);
              findDevices();
            }}
          />

          <Row style={{ alignSelf: 'stretch' }}>
            <Tile label="오늘의 목표 온도" tint={theme.surfaceAlt}>
              <Row style={{ alignItems: 'flex-end', gap: 4 }}>
                <Text style={{ color: theme.star, fontSize: 34, fontWeight: '800' }}>
                  {formatTemp(status?.target_temp_c ?? summary?.best_temp_c ?? null)}
                </Text>
                <Text style={{ color: theme.star, fontSize: 15, fontWeight: '700', paddingBottom: 6 }}>℃</Text>
              </Row>
              <Caption>지난 기록으로 자동 설정돼요</Caption>
            </Tile>
            <Tile label="히터 상태">
              <Text style={{ color: theme.textPrimary, fontSize: 20, fontWeight: '800' }}>{heaterText}</Text>
              {status?.skin_c != null ? (
                <Caption>피부 {status.skin_c.toFixed(1)}℃</Caption>
              ) : (
                <Caption>{running ? '곧 데이터가 들어와요' : '시작하면 표시돼요'}</Caption>
              )}
            </Tile>
          </Row>

          <Caption>{notice || (running ? '편하게 누우세요. 잠들면 자동으로 기록돼요' : '잠들기 전, 시작을 눌러 히터를 켜세요')}</Caption>
        </Card>

        {/* 지난밤 결과 */}
        <Card>
          <Heading>지난밤 결과</Heading>
          {last ? (
            <Row style={{ alignItems: 'center' }}>
              <MoonIcon size={54} />
              <View style={{ flex: 1, gap: 2 }}>
                <Row style={{ alignItems: 'flex-end', gap: 4 }}>
                  <Text style={{ color: theme.textPrimary, fontSize: 26, fontWeight: '800' }}>
                    {formatMinutes(last.sol_min)}분
                  </Text>
                  <Text style={{ color: theme.textSecondary, fontSize: 15, paddingBottom: 3 }}>
                    만에 잠들었어요
                  </Text>
                </Row>
                <Caption>
                  {summary?.best_temp_c != null
                    ? `${formatTemp(summary.best_temp_c)}℃가 딱 맞는 온도로 확인됐어요`
                    : '기록이 쌓이면 딱 맞는 온도를 찾아드려요'}
                </Caption>
              </View>
            </Row>
          ) : (
            <Body muted>아직 기록이 없어요. 오늘 밤 시작을 눌러보세요.</Body>
          )}
        </Card>

        {/* 수면 입면 분석 */}
        <Card>
          <Row style={{ alignItems: 'center' }}>
            <Heading>수면 입면 분석</Heading>
            <View style={{ flex: 1 }} />
            <Pressable
              onPress={() => last && router.push(`/user/session/${last.session_id}`)}
              disabled={!last}
              hitSlop={8}>
              <Text style={{ color: theme.moon, fontSize: 14, fontWeight: '700', opacity: last ? 1 : 0.4 }}>
                자세히 보기 →
              </Text>
            </Pressable>
          </Row>
          <Row>
            <Tile label="입면시간" style={{ minHeight: 92 }}>
              <Text style={{ color: theme.textPrimary, fontSize: 24, fontWeight: '800' }}>
                {last ? `${formatMinutes(last.sol_min)}분` : '-'}
              </Text>
            </Tile>
            <Tile label="잠든 시간" style={{ minHeight: 92 }}>
              <Text style={{ color: theme.textPrimary, fontSize: 24, fontWeight: '800' }}>
                {formatClock(last?.onset_at ?? null)}
              </Text>
            </Tile>
          </Row>
        </Card>

        <Pressable
          onPress={async () => {
            if (token) {
              try {
                await api.logOut(settings.serverUrl, token);
              } catch {
                // 서버에 못 알려도 로컬 로그아웃은 진행한다
              }
            }
            await signOut();
            router.replace('/');
          }}
          style={{ alignSelf: 'center', padding: spacing.md, borderRadius: radius.pill }}>
          <Caption>로그아웃</Caption>
        </Pressable>
      </ScrollView>

      <DeviceLinkSheet
        visible={sheetOpen}
        devices={found}
        loading={finding}
        error={sheetError}
        onPick={pickDevice}
        onRefresh={findDevices}
        onClose={() => setSheetOpen(false)}
      />

      {/* 입면이 확정된 밤에만 뜨는 평가 팝업 */}
      <SleepReviewPopup
        visible={reviewOpen}
        dateLabel={pending ? formatKoreanDate(new Date(pending.started_at)) : ''}
        solMin={pending?.sol_min ?? null}
        onSubmit={submitReview}
        onSkip={() => {
          setSkipped(pending?.session_id ?? null);
          setReviewOpen(false);
        }}
        submitting={reviewing}
        error={reviewError}
      />
    </Screen>
  );
}
