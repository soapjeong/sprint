/** 화면 표시용 포맷 헬퍼. */
export function formatDateTime(iso: string | null): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function formatMinutes(value: number | null | undefined): string {
  return value === null || value === undefined ? '-' : value.toFixed(1);
}

export function formatTemp(value: number | null | undefined): string {
  return value === null || value === undefined ? '-' : `${value.toFixed(1)}℃`;
}
