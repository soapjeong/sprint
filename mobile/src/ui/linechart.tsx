import React from 'react';
import { View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Path, Stop, Text as SvgText } from 'react-native-svg';
import { radius, theme } from '@/theme';

export type Series = {
  /** x축에 찍히는 라벨 (요일 / 날짜 / 월) */
  label: string;
  value: number;
  /** 배지·평균에 쓰는 표시용 문자열 (예: "11분", "23:06", "38.4℃") */
  display: string;
};

const PAD_L = 6;
const PAD_R = 52;    // 오른쪽 단위선 라벨 자리
const TOP = 34;      // 마지막 값 배지 자리
const BOTTOM = 30;   // x축 라벨 자리

/**
 * 시안의 꺾은선 카드 — 노란 선 + 옅은 면적, 오른쪽에 단위선 라벨,
 * 마지막 값은 알약 배지로 직접 표시한다(계열이 하나라 범례는 두지 않는다).
 */
export function TrendLineChart({
  data,
  ticks,
  height = 210,
  width,
}: {
  data: Series[];
  /** 오른쪽에 표시할 단위선 값들 (아래→위) */
  ticks: { value: number; label: string }[];
  height?: number;
  width: number;
}) {
  if (width <= 0 || data.length === 0) return <View style={{ height }} />;

  const plotW = width - PAD_L - PAD_R;
  const plotH = height - TOP - BOTTOM;
  const min = Math.min(...ticks.map((t) => t.value));
  const max = Math.max(...ticks.map((t) => t.value));
  const span = Math.max(1e-6, max - min);

  const x = (i: number) => PAD_L + (data.length > 1 ? (i / (data.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => TOP + plotH - ((v - min) / span) * plotH;

  const line = data.map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(d.value)}`).join(' ');
  const area = `${line} L ${x(data.length - 1)} ${TOP + plotH} L ${x(0)} ${TOP + plotH} Z`;
  const lastX = x(data.length - 1);
  const lastY = y(data[data.length - 1].value);
  const badge = data[data.length - 1].display;
  const badgeW = Math.max(48, badge.length * 11 + 18);
  const badgeX = Math.min(Math.max(lastX - badgeW / 2, PAD_L), PAD_L + plotW - badgeW);

  return (
    <Svg width={width} height={height}>
      <Defs>
        <LinearGradient id="fillArea" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={theme.moon} stopOpacity={0.35} />
          <Stop offset="1" stopColor={theme.moon} stopOpacity={0.02} />
        </LinearGradient>
      </Defs>

      {/* 단위선 + 오른쪽 라벨 */}
      {ticks.map((t) => (
        <React.Fragment key={t.label}>
          <Path
            d={`M ${PAD_L} ${y(t.value)} L ${PAD_L + plotW} ${y(t.value)}`}
            stroke={theme.surfaceSoft}
            strokeWidth={1}
          />
          <SvgText
            x={PAD_L + plotW + 8}
            y={y(t.value) + 4}
            fill={theme.textMuted}
            fontSize={11}>
            {t.label}
          </SvgText>
        </React.Fragment>
      ))}
      {/* 마지막 지점을 지나는 세로 기준선 */}
      <Path
        d={`M ${lastX} ${TOP} L ${lastX} ${TOP + plotH}`}
        stroke={theme.surfaceSoft}
        strokeWidth={1}
        strokeDasharray="3 4"
      />

      <Path d={area} fill="url(#fillArea)" />
      <Path d={line} stroke={theme.moon} strokeWidth={2.5} fill="none" strokeLinejoin="round" strokeLinecap="round" />

      {data.map((d, i) => (
        <Circle
          key={`${d.label}-${i}`}
          cx={x(i)}
          cy={y(d.value)}
          r={i === data.length - 1 ? 5 : 3.5}
          fill={theme.moon}
          stroke={theme.surface}
          strokeWidth={i === data.length - 1 ? 2 : 1}
        />
      ))}

      {/* 마지막 값 배지 */}
      <Path
        d={`M ${badgeX + 13} 6 L ${badgeX + badgeW - 13} 6
            A 13 13 0 0 1 ${badgeX + badgeW - 13} 32
            L ${badgeX + 13} 32 A 13 13 0 0 1 ${badgeX + 13} 6 Z`}
        fill={theme.moon}
      />
      <SvgText
        x={badgeX + badgeW / 2}
        y={24}
        fill={theme.onAccent}
        fontSize={14}
        fontWeight="800"
        textAnchor="middle">
        {badge}
      </SvgText>

      {/* x축 라벨 */}
      {data.map((d, i) => (
        <SvgText
          key={`x-${d.label}-${i}`}
          x={x(i)}
          y={height - 8}
          fill={i === data.length - 1 ? theme.textPrimary : theme.textMuted}
          fontSize={12}
          fontWeight={i === data.length - 1 ? '700' : '500'}
          textAnchor="middle">
          {d.label}
        </SvgText>
      ))}
    </Svg>
  );
}

export const chartCardStyle = { borderRadius: radius.card } as const;
