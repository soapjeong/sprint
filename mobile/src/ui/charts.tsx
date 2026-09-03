import React, { useState } from 'react';
import { View } from 'react-native';
import Svg, { Circle, G, Line, Path, Text as SvgText } from 'react-native-svg';
import { spacing, theme } from '@/theme';
import { Caption, Heading } from './kit';

/** 밤색 카드 위에서 대비가 확인된 마크 색(단일 계열 + 강조) */
const MARK = '#3987e5';
const MARK_BEST = '#199e70';
const GRID = theme.surfaceSoft;

const H_PAD = 14;
const TOP = 22;
const BOTTOM = 26;

function niceMax(value: number, step = 10): number {
  if (value <= 0) return step;
  return Math.ceil((value * 1.15) / step) * step;
}

function barPath(x: number, y: number, w: number, h: number, r = 5): string {
  const radius = Math.min(r, w / 2, h);
  return [
    `M ${x} ${y + h}`,
    `L ${x} ${y + radius}`,
    `Q ${x} ${y} ${x + radius} ${y}`,
    `L ${x + w - radius} ${y}`,
    `Q ${x + w} ${y} ${x + w} ${y + radius}`,
    `L ${x + w} ${y + h}`,
    'Z',
  ].join(' ');
}

export type Point = { label: string; value: number };

/** 그날 밤 심박수 — 입면 기준선을 함께 그려 "언제 내려갔는지"가 보이게 한다. */
export function HeartRateChart({
  points,
  threshold,
  height = 180,
}: {
  points: Point[];
  threshold: number | null;
  height?: number;
}) {
  const [width, setWidth] = useState(0);
  if (points.length < 2) {
    return (
      <View style={{ gap: spacing.sm }}>
        <Heading>그날 밤 심박수</Heading>
        <Caption>심박 기록이 충분하지 않아요.</Caption>
      </View>
    );
  }

  const plotH = height - TOP - BOTTOM;
  const plotW = Math.max(0, width - H_PAD * 2);
  const values = points.map((p) => p.value);
  const max = Math.ceil(Math.max(...values, threshold ?? 0) / 10) * 10 + 5;
  const min = Math.max(0, Math.floor(Math.min(...values, threshold ?? 999) / 10) * 10 - 5);
  const span = Math.max(1, max - min);
  const x = (i: number) => H_PAD + (i / (points.length - 1)) * plotW;
  const y = (v: number) => TOP + plotH - ((v - min) / span) * plotH;
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(p.value)}`).join(' ');

  return (
    <View style={{ gap: spacing.sm }} onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
      <Heading>그날 밤 심박수</Heading>
      {width > 0 ? (
        <Svg width={width} height={height}>
          {[0, 0.5, 1].map((f) => (
            <Line key={f} x1={H_PAD} x2={H_PAD + plotW} y1={TOP + plotH * f} y2={TOP + plotH * f}
                  stroke={GRID} strokeWidth={1} />
          ))}
          {threshold !== null ? (
            <>
              <Line x1={H_PAD} x2={H_PAD + plotW} y1={y(threshold)} y2={y(threshold)}
                    stroke={MARK_BEST} strokeWidth={1.5} strokeDasharray="5 4" />
              <SvgText x={H_PAD + plotW} y={y(threshold) - 6} fill={MARK_BEST} fontSize={11}
                       fontWeight="700" textAnchor="end">
                {`입면 기준 ${threshold.toFixed(0)}`}
              </SvgText>
            </>
          ) : null}
          <Path d={path} stroke={MARK} strokeWidth={2} fill="none" strokeLinejoin="round" />
          <Circle cx={x(points.length - 1)} cy={y(values[values.length - 1])} r={4}
                  fill={MARK} stroke={theme.surface} strokeWidth={2} />
          <SvgText x={H_PAD} y={height - 6} fill={theme.textMuted} fontSize={10}>{points[0].label}</SvgText>
          <SvgText x={H_PAD + plotW} y={height - 6} fill={theme.textMuted} fontSize={10} textAnchor="end">
            {points[points.length - 1].label}
          </SvgText>
        </Svg>
      ) : null}
      <Caption>파란 선이 심박수, 초록 점선 아래로 내려가 유지되면 잠든 것으로 봐요.</Caption>
    </View>
  );
}

/** 최근 기기 사용별 입면시간 추이 */
export function OnsetTrendChart({ points, height = 170 }: { points: Point[]; height?: number }) {
  const [width, setWidth] = useState(0);
  if (points.length === 0) {
    return (
      <View style={{ gap: spacing.sm }}>
        <Heading>입면시간 변화</Heading>
        <Caption>아직 기록이 없어요.</Caption>
      </View>
    );
  }

  const plotH = height - TOP - BOTTOM;
  const plotW = Math.max(0, width - H_PAD * 2);
  const max = niceMax(Math.max(...points.map((p) => p.value)), 10);
  const x = (i: number) => H_PAD + (points.length > 1 ? (i / (points.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => TOP + plotH - (v / max) * plotH;
  const best = points.reduce((b, p, i) => (p.value < points[b].value ? i : b), 0);
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(p.value)}`).join(' ');

  return (
    <View style={{ gap: spacing.sm }} onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
      <Heading>입면시간 변화</Heading>
      {width > 0 ? (
        <Svg width={width} height={height}>
          {[0, 0.5, 1].map((f) => (
            <Line key={f} x1={H_PAD} x2={H_PAD + plotW} y1={TOP + plotH * f} y2={TOP + plotH * f}
                  stroke={GRID} strokeWidth={1} />
          ))}
          <SvgText x={H_PAD} y={TOP - 8} fill={theme.textMuted} fontSize={10}>{`${max}분`}</SvgText>
          {points.length > 1 ? (
            <Path d={path} stroke={MARK} strokeWidth={2} fill="none" strokeLinejoin="round" />
          ) : null}
          {points.map((p, i) => (
            <Circle key={`${p.label}-${i}`} cx={x(i)} cy={y(p.value)} r={i === best ? 5.5 : 4}
                    fill={i === best ? MARK_BEST : MARK} stroke={theme.surface} strokeWidth={2} />
          ))}
          <SvgText
            x={Math.min(Math.max(x(best), H_PAD + 26), H_PAD + plotW - 26)}
            y={y(points[best].value) - 10}
            fill={MARK_BEST}
            fontSize={11}
            fontWeight="700"
            textAnchor="middle">
            {`최단 ${points[best].value.toFixed(0)}분`}
          </SvgText>
          <SvgText x={H_PAD} y={height - 6} fill={theme.textMuted} fontSize={10}>{points[0].label}</SvgText>
          {points.length > 1 ? (
            <SvgText x={H_PAD + plotW} y={height - 6} fill={theme.textMuted} fontSize={10} textAnchor="end">
              {points[points.length - 1].label}
            </SvgText>
          ) : null}
        </Svg>
      ) : null}
    </View>
  );
}

export type TempBar = { temp: number; avg: number; count: number };

/** 설정 온도별 평균 입면시간 — 가장 짧은 온도는 색과 "최적" 라벨을 함께 붙인다. */
export function TempBarChart({ bars, height = 190 }: { bars: TempBar[]; height?: number }) {
  const [width, setWidth] = useState(0);
  if (bars.length === 0) {
    return (
      <View style={{ gap: spacing.sm }}>
        <Heading>온도별 평균 입면시간</Heading>
        <Caption>입면에 성공한 기록이 쌓이면 보여드려요.</Caption>
      </View>
    );
  }

  const plotH = height - TOP - BOTTOM;
  const plotW = Math.max(0, width - H_PAD * 2);
  const max = niceMax(Math.max(...bars.map((b) => b.avg)), 5);
  const slot = plotW / bars.length;
  const barW = Math.max(14, Math.min(64, slot - 10));
  const bestIdx = bars.reduce((b, d, i) => (d.avg < bars[b].avg ? i : b), 0);

  return (
    <View style={{ gap: spacing.sm }} onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
      <Heading>온도별 평균 입면시간</Heading>
      {width > 0 ? (
        <Svg width={width} height={height}>
          <Line x1={H_PAD} x2={H_PAD + plotW} y1={TOP + plotH} y2={TOP + plotH} stroke={GRID} strokeWidth={1} />
          {bars.map((b, i) => {
            const h = Math.max(3, (b.avg / max) * plotH);
            const bx = H_PAD + i * slot + (slot - barW) / 2;
            const by = TOP + plotH - h;
            const isBest = i === bestIdx;
            return (
              <G key={b.temp}>
                <Path d={barPath(bx, by, barW, h)} fill={isBest ? MARK_BEST : MARK} />
                <SvgText x={bx + barW / 2} y={by - 6} fill={theme.textSecondary} fontSize={11}
                         fontWeight={isBest ? '700' : '500'} textAnchor="middle">
                  {isBest ? `최적 ${b.avg.toFixed(0)}분` : `${b.avg.toFixed(0)}분`}
                </SvgText>
                <SvgText x={bx + barW / 2} y={height - 8} fill={theme.textMuted} fontSize={10}
                         textAnchor="middle">
                  {`${b.temp.toFixed(1)}℃`}
                </SvgText>
              </G>
            );
          })}
        </Svg>
      ) : null}
    </View>
  );
}
