import { useRouter } from 'expo-router';
import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';
import { Text } from '@/ui/typography';
import { api, ApiError } from '@/api/client';
import type { Session } from '@/api/types';
import { useSettings } from '@/store/settings';
import { radius, spacing, theme } from '@/theme';
import { Caption, Card, ErrorNote, Loading, Row, Screen } from '@/ui/kit';
import { TrendLineChart, type Series } from '@/ui/linechart';

type Metric = 'onset' | 'bedtime' | 'temp';
type Period = 'day' | 'week' | 'month';

const METRICS: { key: Metric; label: string }[] = [
  { key: 'onset', label: '입면시간' },
  { key: 'bedtime', label: '잠든 시간' },
  { key: 'temp', label: '적정 온도' },
];
const PERIODS: { key: Period; label: string }[] = [
  { key: 'day', label: '일별' },
  { key: 'week', label: '주별' },
  { key: 'month', label: '월별' },
];
const WEEKDAY = ['일', '월', '화', '수', '목', '금', '토'];

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const startOfWeek = (d: Date) => {
  const s = startOfDay(d);
  s.setDate(s.getDate() - s.getDay());
  return s;
};
const fmtDay = (d: Date) => `${d.getMonth() + 1}월 ${d.getDate()}일`;

/** 지표별로 세션에서 값을 꺼낸다(잠든 시간은 자정을 넘겨도 이어지도록 분 단위로 편다). */
function pickValue(metric: Metric, s: Session): number | null {
  if (metric === 'onset') return s.outcome === 'onset' ? s.sol_min : null;
  if (metric === 'temp') return s.target_temp_c;
  if (!s.onset_at) return null;
  const d = new Date(s.onset_at);
  const minutes = d.getHours() * 60 + d.getMinutes();
  return minutes < 12 * 60 ? minutes + 24 * 60 : minutes;   // 새벽 1시 = 25:00
}

function display(metric: Metric, value: number): string {
  if (metric === 'onset') return `${Math.round(value)}분`;
  if (metric === 'temp') return `${value.toFixed(1)}℃`;
  const total = Math.round(value) % (24 * 60);
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

/** 단위선 기본 간격 — 잠든 시간은 2시간, 입면시간은 5분, 온도는 0.5℃ 단위. */
const TICK_STEP: Record<Metric, number> = { onset: 5, bedtime: 120, temp: 0.5 };
const round3 = (v: number) => Math.round(v * 1000) / 1000;

/** 단위선 — 값 범위를 감싸는 눈금을 만든다. 줄이 너무 촘촘해지면 간격을 두 배로 늘린다. */
function makeTicks(metric: Metric, values: number[]) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  let step = TICK_STEP[metric];
  while ((Math.ceil(max / step) * step - Math.floor(min / step) * step) / step > 8) step *= 2;

  let lo = round3(Math.floor(min / step) * step);
  let hi = round3(Math.ceil(max / step) * step);
  // 눈금이 최소 세 줄은 되도록 위아래로 한 칸씩 넓힌다(선이 카드 끝에 붙지 않게).
  while (round3((hi - lo) / step) < 2) {
    lo = round3(lo - step);
    hi = round3(hi + step);
  }

  const ticks: { value: number; label: string }[] = [];
  for (let v = lo; v <= hi + 1e-6; v = round3(v + step)) ticks.push({ value: v, label: display(metric, v) });
  return ticks;
}

/** 홈의 "수면 입면 분석" 카드를 누르면 오는 화면 — 시안 그대로 탭 두 줄과 꺾은선 한 장. */
export default function AnalysisScreen() {
  const router = useRouter();
  const { settings } = useSettings();
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState('');
  const [metric, setMetric] = useState<Metric>('onset');
  const [period, setPeriod] = useState<Period>('day');
  const [width, setWidth] = useState(0);

  useEffect(() => {
    (async () => {
      try {
        setSessions(
          await api.sessions(settings.serverUrl, settings.userToken ?? '', settings.userId ?? '', 200),
        );
      } catch (e) {
        setError((e as ApiError).message);
      }
    })();
  }, [settings.serverUrl, settings.userToken, settings.userId]);

  const { series, rangeLabel } = useMemo(() => {
    const rows = sessions ?? [];
    const buckets = new Map<string, { at: Date; values: number[] }>();

    rows.forEach((s) => {
      const value = pickValue(metric, s);
      if (value === null) return;
      const at = new Date(s.started_at);
      const key =
        period === 'day'
          ? startOfDay(at).toISOString()
          : period === 'week'
            ? startOfWeek(at).toISOString()
            : new Date(at.getFullYear(), at.getMonth(), 1).toISOString();
      const cur = buckets.get(key) ?? { at: new Date(key), values: [] };
      cur.values.push(value);
      buckets.set(key, cur);
    });

    const count = period === 'day' ? 7 : period === 'week' ? 6 : 6;
    const sorted = [...buckets.values()].sort((a, b) => a.at.getTime() - b.at.getTime()).slice(-count);
    const out: Series[] = sorted.map((b) => {
      const avg = b.values.reduce((a, v) => a + v, 0) / b.values.length;
      const label =
        period === 'day'
          ? WEEKDAY[b.at.getDay()]
          : period === 'week'
            ? fmtDay(b.at)
            : `${b.at.getMonth() + 1}월`;
      return { label, value: avg, display: display(metric, avg) };
    });

    let range = '';
    if (sorted.length) {
      const first = sorted[0].at;
      const last = sorted[sorted.length - 1].at;
      if (period === 'month') {
        range = `${first.getMonth() + 1}월 - ${last.getMonth() + 1}월, ${last.getFullYear()}`;
      } else if (period === 'week') {
        const end = new Date(last);
        end.setDate(end.getDate() + 6);
        range = `${fmtDay(first)} - ${fmtDay(end)}, ${end.getFullYear()}`;
      } else {
        range = `${fmtDay(first)} - ${fmtDay(last)}, ${last.getFullYear()}`;
      }
    }
    return { series: out, rangeLabel: range };
  }, [sessions, metric, period]);

  const average =
    series.length > 0 ? series.reduce((a, s) => a + s.value, 0) / series.length : null;

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: spacing.xl, gap: spacing.lg }}>
        <Row style={{ alignItems: 'center', gap: spacing.md }}>
          <Pressable onPress={() => router.back()} hitSlop={10}>
            <Text style={{ color: theme.textPrimary, fontSize: 24, fontWeight: '700' }}>←</Text>
          </Pressable>
          <Text style={{ color: theme.textPrimary, fontSize: 22, fontWeight: '800' }}>수면 입면 분석</Text>
        </Row>

        {/* 지표 탭 */}
        <Row>
          {METRICS.map((m) => {
            const on = metric === m.key;
            return (
              <Pressable
                key={m.key}
                onPress={() => setMetric(m.key)}
                accessibilityRole="tab"
                accessibilityState={{ selected: on }}
                style={({ pressed }) => ({
                  flex: 1,
                  paddingVertical: 13,
                  borderRadius: radius.pill,
                  alignItems: 'center',
                  backgroundColor: on ? theme.moon : theme.surface,
                  borderWidth: 1,
                  borderColor: on ? theme.moon : theme.border,
                  opacity: pressed ? 0.85 : 1,
                })}>
                <Text style={{ color: on ? theme.onAccent : theme.textSecondary, fontWeight: '700', fontSize: 14 }}>
                  {m.label}
                </Text>
              </Pressable>
            );
          })}
        </Row>

        {/* 기간 탭 */}
        <View style={{ flexDirection: 'row', backgroundColor: theme.surfaceAlt, borderRadius: radius.pill, padding: 4 }}>
          {PERIODS.map((p) => {
            const on = period === p.key;
            return (
              <Pressable
                key={p.key}
                onPress={() => setPeriod(p.key)}
                accessibilityRole="tab"
                accessibilityState={{ selected: on }}
                style={{
                  flex: 1,
                  paddingVertical: 11,
                  borderRadius: radius.pill,
                  alignItems: 'center',
                  backgroundColor: on ? theme.surface : 'transparent',
                }}>
                <Text style={{ color: on ? theme.moon : theme.textSecondary, fontWeight: '700', fontSize: 14 }}>
                  {p.label}
                </Text>
              </Pressable>
            );
          })}
        </View>

        {error ? <ErrorNote message={error} /> : null}
        {!sessions && !error ? <Loading /> : null}

        {sessions ? (
          <Card style={{ gap: spacing.sm }}>
            <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
              {series.length === 0 ? (
                <Caption>아직 보여줄 기록이 없어요.</Caption>
              ) : (
                <>
                  <Row style={{ alignItems: 'flex-start' }}>
                    <Text style={{ color: theme.textPrimary, fontSize: 15, fontWeight: '800' }}>
                      {`평균: ${average !== null ? display(metric, average) : '-'}`}
                    </Text>
                    <View style={{ flex: 1 }} />
                    <Caption>{rangeLabel}</Caption>
                  </Row>
                  <TrendLineChart
                    data={series}
                    ticks={makeTicks(metric, series.map((s) => s.value))}
                    width={width}
                  />
                </>
              )}
            </View>
          </Card>
        ) : null}
      </ScrollView>
    </Screen>
  );
}
