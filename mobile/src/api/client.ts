import type {
  AdminUserDetail,
  AdminUserRow,
  Device,
  NoteCode,
  PendingDevice,
  Session,
  SessionDetail,
  User,
  UserSummary,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

const TIMEOUT_MS = 8000;

function normalizeBase(baseUrl: string): string {
  const trimmed = baseUrl.trim().replace(/\/+$/, '');
  return trimmed.startsWith('http') ? trimmed : `http://${trimmed}`;
}

async function request<T>(
  baseUrl: string,
  path: string,
  options: { method?: string; body?: unknown; adminToken?: string } = {},
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(normalizeBase(baseUrl) + path, {
      method: options.method ?? 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...(options.adminToken ? { 'X-Admin-Token': options.adminToken } : {}),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
    });
    const text = await res.text();
    const payload = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const detail =
        payload && typeof payload.detail === 'string' ? payload.detail : `요청 실패 (HTTP ${res.status})`;
      throw new ApiError(res.status, detail);
    }
    return payload as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError(0, '서버 응답이 없습니다. 주소와 네트워크를 확인하세요.');
    }
    throw new ApiError(0, '서버에 연결할 수 없습니다. 주소를 확인하세요.');
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: (base: string) => request<{ status: string }>(base, '/api/health'),

  // --- 첫 화면: 사용자 ID / 기기 등록 ---
  createUser: (base: string, user_id: string, name: string) =>
    request<User>(base, '/api/users', { method: 'POST', body: { user_id, name } }),
  getUser: (base: string, userId: string) => request<User>(base, `/api/users/${userId}`),
  registerDevice: (base: string, device_id: string, user_id: string, label: string) =>
    request<Device>(base, '/api/devices', { method: 'POST', body: { device_id, user_id, label } }),
  listDevices: (base: string, userId: string) => request<Device[]>(base, `/api/users/${userId}/devices`),
  /** 등록되지 않은 채 신호를 보내온 기기들 — 기기 ID 는 칩 MAC 이라 목록에서 고른다 */
  pendingDevices: (base: string, minutes = 180) =>
    request<PendingDevice[]>(base, `/api/devices/pending?minutes=${minutes}`),
  unregisterDevice: (base: string, deviceId: string) =>
    request<null>(base, `/api/devices/${deviceId}`, { method: 'DELETE' }),

  // --- 사용자 페이지 ---
  summary: (base: string, userId: string) => request<UserSummary>(base, `/api/users/${userId}/summary`),
  sessions: (base: string, userId: string, limit = 30) =>
    request<Session[]>(base, `/api/users/${userId}/sessions?limit=${limit}`),
  sessionDetail: (base: string, sessionId: number) =>
    request<SessionDetail>(base, `/api/sessions/${sessionId}`),
  /** 아침 수면 평가(별점 + 특이사항) */
  reviewSession: (base: string, sessionId: number, rating: number, note_code: NoteCode, note_text = '') =>
    request<Session>(base, `/api/sessions/${sessionId}/review`, {
      method: 'POST',
      body: { rating, note_code, note_text },
    }),

  // --- 관리자 페이지 ---
  adminUsers: (base: string, adminToken: string) =>
    request<AdminUserRow[]>(base, '/api/admin/users', { adminToken }),
  adminUserDetail: (base: string, adminToken: string, userId: string) =>
    request<AdminUserDetail>(base, `/api/admin/users/${userId}`, { adminToken }),
};
