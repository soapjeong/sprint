import React, { useState } from 'react';
import { View } from 'react-native';
import Svg, { Circle, G, Line, Path, Text as SvgText } from 'react-native-svg';
import { Caption, Heading } from './kit';
import { spacing, useTheme } from '@/theme';

const H_PADDING = 12;
const LABEL_GUTTER = 26;   // x축 라벨 영역
const TOP_GUTTER = 18;     // 값 라벨 영역

function niceMax(value: number): number {
  if (value <= 0) return 10;
  const step = value <= 20 ? 5 : value <= 60 ? 10 : 20;
  return Math.ceil((value * 1.1) / step) * step;
}

/** 위쪽 모서리만 둥근 막대(값 끝단 4px, 바닥은 기준선에 붙임) */
function barPath(x: number, y: number, w: number, h: number, r = 4): string {
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

export type TrendPoint = { label: string; value: number };

/**
 * 세션별 수면잠복기(SOL) 추이 — 단일 계열 라인차트.
 * 계열이 하나라 범례는 두지 않고(제목이 계열을 설명), 마지막·최단 지점만 직접 라벨링한다.
 * 점을 누르면 해당 세션 값을 캡션으로 보여준다(모바일에서의 hover 대체).
 */
export function SolTrendChart({ data, height = 190 }: { data: TrendPoint[]; height?: number }) {
  const t = useTheme();
  const [width, setWidth] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);

  const plotH = height - LABEL_GUTTER - TOP_GUTTER;
  const plotW = Math.max(0, width - H_PADDING * 2);
  const max = niceMax(Math.max(...data.map((d) => d.value), 0));
  const stepX = data.length > 1 ? plotW / (data.length - 1) : 0;
  const xAt = (i: number) => H_PADDING + (data.length > 1 ? i * stepX : plotW / 2);
  const yAt = (v: number) => TOP_GUTTER + plotH - (v / max) * plotH;

  const minIdx = data.reduce((best, d, i) => (d.value < data[best].value ? i : best), 0);
  const lastIdx = data.length - 1;
  const path = data.map((d, i) => `${i === 0 ? 'M' : 'L'} ${xAt(i)} ${yAt(d.value)}`).join(' ');
  const picked = selected !== null ? data[selected] : null;

  return (
    <View style={{ gap: spacing.sm }} onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
      <Heading>세션별 잠들기까지 걸린 시간</Heading>
      {width > 0 && data.length > 0 ? (
        <Svg width={width} height={height}>
          {[0, 0.5, 1].map((f) => (
            <Line
              key={f}
              x1={H_PADDING}
              x2={H_PADDING + plotW}
              y1={TOP_GUTTER + plotH * f}
              y2={TOP_GUTTER + plotH * f}
              stroke={t.grid}
              strokeWidth={1}
            />
          ))}
          <SvgText x={H_PADDING} y={TOP_GUTTER - 6} fill={t.textMuted} fontSize={10}>
            {`${max}분`}
          </SvgText>

          {data.length > 1 ? (
            <Path d={path} stroke={t.series1} strokeWidth={2} fill="none" strokeLinejoin="round" />
          ) : null}

          {data.map((d, i) => (
            <G key={`${d.label}-${i}`} onPress={() => setSelected(i === selected ? null : i)}>
              {/* 터치 영역을 마크보다 크게 */}
              <Circle cx={xAt(i)} cy={yAt(d.value)} r={16} fill="transparent" />
              <Circle
                cx={xAt(i)}
                cy={yAt(d.value)}
                r={selected === i ? 6 : 4}
                fill={t.series1}
                stroke={t.surface}
                strokeWidth={2}
              />
            </G>
          ))}

          {/* 직접 라벨: 최단 기록과 마지막 기록만 */}
          {[minIdx, lastIdx]
            .filter((i, idx, arr) => arr.indexOf(i) === idx && data.length > 0)
            .map((i) => (
              <SvgText
                key={`label-${i}`}
                x={Math.min(Math.max(xAt(i), H_PADDING + 10), H_PADDING + plotW - 10)}
                y={yAt(data[i].value) - 10}
                fill={t.textSecondary}
                fontSize={11}
                fontWeight="600"
                textAnchor="middle">
                {`${data[i].value.toFixed(0)}분`}
              </SvgText>
            ))}

          <SvgText x={H_PADDING} y={height - 6} fill={t.textMuted} fontSize={10}>
            {data[0].label}
          </SvgText>
          {data.length > 1 ? (
            <SvgText x={H_PADDING + plotW} y={height - 6} fill={t.textMuted} fontSize={10} textAnchor="end">
              {data[lastIdx].label}
            </SvgText>
          ) : null}
        </Svg>
      ) : null}
      <Caption>
        {picked
          ? `${picked.label} · ${picked.value.toFixed(1)}분`
          : '점을 누르면 해당 세션 기록을 볼 수 있어요.'}
      </Caption>
    </View>
  );
}

export type TempBar = { temp: number; avgSol: number; count: number };

/**
 * 설정 온도별 평균 SOL — 단일 계열 막대차트.
 * 가장 성적이 좋은 온도는 색과 함께 "최적" 라벨을 붙여 색만으로 구분하지 않는다.
 */
export function TempBarChart({ data, height = 200 }: { data: TempBar[]; height?: number }) {
  const t = useTheme();
  const [width, setWidth] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);

  const plotH = height - LABEL_GUTTER - TOP_GUTTER;
  const plotW = Math.max(0, width - H_PADDING * 2);
  const max = niceMax(Math.max(...data.map((d) => d.avgSol), 0));
  const slot = data.length > 0 ? plotW / data.length : 0;
  const barW = Math.max(8, slot - 2);                       // 막대 사이 2px 간격
  const bestIdx = data.reduce((best, d, i) => (d.avgSol < data[best].avgSol ? i : best), 0);
  const picked = selected !== null ? data[selected] : null;

  return (
    <View style={{ gap: spacing.sm }} onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
      <Heading>설정 온도별 평균 잠들기 시간</Heading>
      {width > 0 && data.length > 0 ? (
        <Svg width={width} height={height}>
          <Line
            x1={H_PADDING}
            x2={H_PADDING + plotW}
            y1={TOP_GUTTER + plotH}
            y2={TOP_GUTTER + plotH}
            stroke={t.grid}
            strokeWidth={1}
          />
          {data.map((d, i) => {
            const h = Math.max(2, (d.avgSol / max) * plotH);
            const x = H_PADDING + i * slot + (slot - barW) / 2;
            const y = TOP_GUTTER + plotH - h;
            const isBest = i === bestIdx;
            return (
              <G key={d.temp} onPress={() => setSelected(i === selected ? null : i)}>
                <Path d={barPath(x, y, barW, h)} fill={isBest ? t.series2 : t.series1} />
                <SvgText
                  x={x + barW / 2}
                  y={y - 5}
                  fill={t.textSecondary}
                  fontSize={11}
                  fontWeight={isBest ? '700' : '500'}
                  textAnchor="middle">
                  {isBest ? `최적 ${d.avgSol.toFixed(0)}분` : `${d.avgSol.toFixed(0)}분`}
                </SvgText>
                <SvgText
                  x={x + barW / 2}
                  y={height - 8}
                  fill={t.textMuted}
                  fontSize={10}
                  textAnchor="middle">
                  {`${d.temp.toFixed(1)}℃`}
                </SvgText>
              </G>
            );
          })}
        </Svg>
      ) : null}
      <Caption>
        {picked
          ? `${picked.temp.toFixed(1)}℃ · 평균 ${picked.avgSol.toFixed(1)}분 · ${picked.count}회 측정`
          : '막대를 누르면 측정 횟수까지 볼 수 있어요.'}
      </Caption>
    </View>
  );
}
