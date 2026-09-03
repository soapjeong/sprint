/** 화면 표시용 포맷 헬퍼. */
const WEEKDAYS = ['일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일'];

export function formatDateTime(iso: string | null): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** "8월 12일 · 수요일" */
export function formatKoreanDate(date: Date = new Date()): string {
  return `${date.getMonth() + 1}월 ${date.getDate()}일 · ${WEEKDAYS[date.getDay()]}`;
}

/** "22:42" */
export function formatClock(iso: string | null): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

export function formatMinutes(value: number | null | undefined): string {
  return value === null || value === undefined ? '-' : value.toFixed(0);
}

export function formatTemp(value: number | null | undefined): string {
  return value === null || value === undefined ? '-' : value.toFixed(1);
}
