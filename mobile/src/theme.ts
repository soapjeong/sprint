import { useColorScheme } from 'react-native';

/**
 * 앱 전역 색상. 차트 색은 dataviz 팔레트의 검증된 값(밝은/어두운 모드 각각 별도 선택).
 *  - series1(파랑)  : 기본 데이터 계열
 *  - series2(아쿠아): "최적" 강조 (색만으로 구분하지 않고 항상 라벨을 함께 표시)
 */
export const lightTheme = {
  mode: 'light' as const,
  bg: '#f4f4f2',
  surface: '#fcfcfb',
  surfaceAlt: '#eeeeea',
  border: '#dcdcd6',
  textPrimary: '#0b0b0b',
  textSecondary: '#52514e',
  textMuted: '#83827c',
  accent: '#2a78d6',
  series1: '#2a78d6',
  series2: '#1baf7a',
  danger: '#e34948',
  warning: '#eda100',
  grid: '#e3e3dd',
  onAccent: '#ffffff',
};

export const darkTheme: typeof lightTheme = {
  mode: 'dark' as unknown as 'light',
  bg: '#121211',
  surface: '#1a1a19',
  surfaceAlt: '#242423',
  border: '#33332f',
  textPrimary: '#ffffff',
  textSecondary: '#c3c2b7',
  textMuted: '#8f8e85',
  accent: '#3987e5',
  series1: '#3987e5',
  series2: '#199e70',
  danger: '#e66767',
  warning: '#c98500',
  grid: '#2c2c2a',
  onAccent: '#ffffff',
};

export type Theme = typeof lightTheme;

export function useTheme(): Theme {
  return useColorScheme() === 'dark' ? darkTheme : lightTheme;
}

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 };
