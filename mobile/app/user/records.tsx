import { useRouter } from 'expo-router';
import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import { NOTE_OPTIONS, type Session } from '@/api/types';
import { useSettings } from '@/store/settings';
import { radius, spacing, theme } from '@/theme';
import { Body, Caption, Card, ErrorNote, Heading, Loading, Row, Screen, Title } from '@/ui/kit';
import { formatMinutes } from '@/util/format';

const WEEK = ['일', '월', '화', '수', '목', '금', '토'];

function ymd(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 헤더의 [기록] 버튼 — 달력에서 기록이 있는 날을 찾아 본다. */
export default function RecordsScreen() {
  const router = useRouter();
  const { settings } = useSettings();
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState('');
  const [cursor, setCursor] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const [picked, setPicked] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setSessions(
          await api.sessions(settings.serverUrl, settings.userToken ?? '', settings.userId ?? '', 120),
        );
      } catch (e) {
        setError((e as ApiError).message);
      }
    })();
  }, [settings.serverUrl, settings.userToken, settings.userId]);

  /** 날짜별로 그날의 기록을 모아둔다 */
  const byDay = useMemo(() => {
    const map = new Map<string, Session[]>();
    (sessions ?? []).forEach((s) => {
      const key = ymd(s.started_at);
      map.set(key, [...(map.get(key) ?? []), s]);
    });
    return map;
  }, [sessions]);

  const year = cursor.getFullYear();
  const month = cursor.getMonth();
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  const todayKey = ymd(new Date().toISOString());

  const pickedSessions = picked ? byDay.get(picked) ?? [] : [];
  const monthSessions = (sessions ?? []).filter((s) => {
    const d = new Date(s.started_at);
    return d.getFullYear() === year && d.getMonth() === month;
  });
  const monthOnsets = monthSessions.filter((s) => s.outcome === 'onset' && s.sol_min !== null);

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.xl, gap: spacing.lg, paddingBottom: spacing.xxl }}>
        <Row style={{ alignItems: 'center' }}>
          <Pressable onPress={() => router.back()} hitSlop={10}>
            <Text style={{ color: theme.moon, fontSize: 22, fontWeight: '700' }}>←</Text>
          </Pressable>
          <Title>기록</Title>
        </Row>

        {error ? <ErrorNote message={error} /> : null}
        {!sessions && !error ? <Loading /> : null}

        {sessions ? (
          <Card>
            {/* 달 이동 */}
            <Row style={{ alignItems: 'center' }}>
              <Pressable onPress={() => setCursor(new Date(year, month - 1, 1))} hitSlop={10}>
                <Text style={{ color: theme.textSecondary, fontSize: 20, fontWeight: '700' }}>‹</Text>
              </Pressable>
              <View style={{ flex: 1, alignItems: 'center' }}>
                <Heading>{`${year}년 ${month + 1}월`}</Heading>
              </View>
              <Pressable onPress={() => setCursor(new Date(year, month + 1, 1))} hitSlop={10}>
                <Text style={{ color: theme.textSecondary, fontSize: 20, fontWeight: '700' }}>›</Text>
              </Pressable>
            </Row>

            {/* 요일 */}
            <Row style={{ gap: 0 }}>
              {WEEK.map((w) => (
                <View key={w} style={{ flex: 1, alignItems: 'center' }}>
                  <Caption>{w}</Caption>
                </View>
              ))}
            </Row>

            {/* 날짜 칸 */}
            <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
              {cells.map((day, i) => {
                if (day === null) return <View key={`e${i}`} style={{ width: `${100 / 7}%`, height: 52 }} />;
                const key = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
                const daySessions = byDay.get(key) ?? [];
                const onset = daySessions.find((s) => s.outcome === 'onset');
                const failed = daySessions.length > 0 && !onset;
                const selected = picked === key;
                return (
                  <Pressable
                    key={key}
                    onPress={() => setPicked(selected ? null : key)}
                    disabled={daySessions.length === 0}
                    style={{ width: `${100 / 7}%`, height: 52, alignItems: 'center', justifyContent: 'center' }}>
                    <View
                      style={{
                        width: 38,
                        height: 38,
                        borderRadius: 19,
                        alignItems: 'center',
                        justifyContent: 'center',
                        backgroundColor: selected ? theme.moon : daySessions.length ? theme.surfaceAlt : 'transparent',
                        borderWidth: key === todayKey ? 1.5 : 0,
                        borderColor: theme.star,
                      }}>
                      <Text
                        style={{
                          color: selected ? theme.onAccent : daySessions.length ? theme.textPrimary : theme.textMuted,
                          fontSize: 14,
                          fontWeight: daySessions.length ? '700' : '400',
                        }}>
                        {day}
                      </Text>
                      {daySessions.length ? (
                        <View
                          style={{
                            width: 5,
                            height: 5,
                            borderRadius: 3,
                            marginTop: 2,
                            backgroundColor: selected ? theme.onAccent : onset ? theme.mint : theme.amber,
                          }}
                        />
                      ) : null}
                    </View>
                  </Pressable>
                );
              })}
            </View>

            <Row style={{ justifyContent: 'center', gap: spacing.lg }}>
              <Row style={{ alignItems: 'center', gap: 6 }}>
                <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: theme.mint }} />
                <Caption>잘 잠든 날</Caption>
              </Row>
              <Row style={{ alignItems: 'center', gap: 6 }}>
                <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: theme.amber }} />
                <Caption>못 잠든 날</Caption>
              </Row>
            </Row>
          </Card>
        ) : null}

        {/* 고른 날의 기록 */}
        {picked ? (
          <Card>
            <Heading>{`${Number(picked.slice(5, 7))}월 ${Number(picked.slice(8, 10))}일`}</Heading>
            {pickedSessions.length === 0 ? <Body muted>기록이 없어요.</Body> : null}
            {pickedSessions.map((s) => {
              const note = NOTE_OPTIONS.find((o) => o.code === s.note_code);
              const ok = s.outcome === 'onset';
              return (
                <View
                  key={s.session_id}
                  style={{
                    backgroundColor: theme.surfaceAlt,
                    borderRadius: radius.tile,
                    padding: spacing.lg,
                    gap: 6,
                  }}>
                  {/* 1) 입면 성공 여부 */}
                  <Row style={{ alignItems: 'center', gap: 8 }}>
                    <View style={{ width: 9, height: 9, borderRadius: 5, backgroundColor: ok ? theme.mint : theme.amber }} />
                    <Text style={{ color: theme.textPrimary, fontSize: 16, fontWeight: '700' }}>
                      {ok ? '입면 성공' : '입면 실패'}
                    </Text>
                  </Row>

                  {/* 2) 성공했다면 입면시간 */}
                  {ok ? (
                    <Row style={{ alignItems: 'flex-end', gap: 6 }}>
                      <Text style={{ color: theme.textPrimary, fontSize: 26, fontWeight: '800' }}>
                        {`${formatMinutes(s.sol_min)}분`}
                      </Text>
                      <Text style={{ color: theme.textSecondary, fontSize: 14, paddingBottom: 4 }}>
                        만에 잠들었어요
                      </Text>
                    </Row>
                  ) : null}

                  {/* 3) 수면 평가 */}
                  {s.rating ? (
                    <View style={{ gap: 2 }}>
                      <Text style={{ color: theme.moon, fontSize: 16, letterSpacing: 1 }}>
                        {`${'★'.repeat(s.rating)}${'☆'.repeat(5 - s.rating)}`}
                      </Text>
                      <Caption>
                        {note ? note.label : '특이사항 없음'}
                        {s.note_code === 'other' && s.note_text ? ` · ${s.note_text}` : ''}
                      </Caption>
                    </View>
                  ) : (
                    <Caption>수면 평가를 남기지 않았어요</Caption>
                  )}
                </View>
              );
            })}
          </Card>
        ) : (
          <Caption>날짜를 누르면 그날 기록이 보여요.</Caption>
        )}
      </ScrollView>
    </Screen>
  );
}
