/**
 * 밤하늘 테마 — 깊은 남색 배경에 달빛/별빛 포인트.
 * 화면이 어두운 방에서 자기 전에 열리는 앱이라 다크 톤 한 가지로만 간다(모드 전환 없음).
 */
export const theme = {
  // 배경: 위에서 아래로 짙어지는 밤하늘
  bgTop: '#141c44',
  bg: '#0d1330',
  bgDeep: '#080c22',

  surface: '#1b2450',        // 카드
  surfaceAlt: '#242e63',     // 카드 안 타일
  surfaceSoft: '#2b356f',    // 눌림/보조
  border: '#2f3a72',

  textPrimary: '#f4f6ff',
  textSecondary: '#c2caf0',
  textMuted: '#8b96c8',

  moon: '#ffd88a',           // 달빛 — 주요 강조(숫자, 링크)
  star: '#9fc0ff',           // 별빛 — 보조 강조(목표 온도 타일)
  mint: '#6fe0b4',           // 좋음/연결됨
  amber: '#ffc46b',          // 주의(전원·배터리)
  coral: '#ff8fa6',          // 문제(연결 안 됨)
  onAccent: '#12183a',
};

export type Theme = typeof theme;

/** 글씨체 — 둥글둥글한 주아체(Jua) 하나로 앱 전체를 통일한다. */
export const font = { family: 'Jua_400Regular' };

/** 둥글둥글하게 — 카드는 크게, 버튼은 알약처럼 */
export const radius = { tile: 22, card: 28, pill: 999, sheet: 34 };
export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 22, xxl: 30 };

/** 그림자도 남색으로 (검정 그림자는 밤하늘에서 탁해 보인다) */
export const shadow = {
  card: {
    shadowColor: '#03061a',
    shadowOpacity: 0.5,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
    elevation: 6,
  },
  glow: {
    shadowColor: '#8fb3ff',
    shadowOpacity: 0.45,
    shadowRadius: 26,
    shadowOffset: { width: 0, height: 0 },
    elevation: 10,
  },
};

export function useTheme(): Theme {
  return theme;
}
