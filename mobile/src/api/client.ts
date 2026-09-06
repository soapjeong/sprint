import type {
  AuthResult,
  CommandOut,
  DeviceStatus,
  Device,
  NoteCode,
  PendingDevice,
  Session,
  SessionDetail,
  UserSummary,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

const TIMEOUT_MS = 12000;
/** 무료 호스팅(Render 등)은 한동안 요청이 없으면 잠들고, 깨어나는 데 1분 가까이 걸린다. */
const WAKE_TIMEOUT_MS = 60000;

function normalizeBase(baseUrl: string): string {
  const trimmed = baseUrl.trim().replace(/\/+$/, '');
  return trimmed.startsWith('http') ? trimmed : `http://${trimmed}`;
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  userToken?: string | null;
  /** 서버가 자고 있을 수 있는 요청(로그인 등)은 한 번 더, 더 오래 기다린다. */
  wake?: boolean;
};

async function request<T>(baseUrl: string, path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await attempt<T>(baseUrl, path, options, TIMEOUT_MS);
  } catch (err) {
    // 서버에 닿지도 못한 경우(status 0)만 다시 시도한다. HTTP 오류는 그대로 올린다.
    if (!options.wake || !(err instanceof ApiError) || err.status !== 0) throw err;
    return attempt<T>(baseUrl, path, options, WAKE_TIMEOUT_MS);
  }
}

async function attempt<T>(
  baseUrl: string,
  path: string,
  options: RequestOptions,
  timeoutMs: number,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(normalizeBase(baseUrl) + path, {
      method: options.method ?? 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...(options.userToken ? { 'X-User-Token': options.userToken } : {}),
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
    const target = normalizeBase(baseUrl);
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError(0, `서버가 응답하지 않습니다 (${target}). 잠시 뒤 다시 시도해 주세요.`);
    }
    throw new ApiError(
      0,
      `서버에 연결할 수 없습니다 (${target}).\n` +
        '주소가 맞는지, 서버가 켜져 있는지 확인해 주세요.',
    );
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: (base: string) => request<{ status: string }>(base, '/api/health', { wake: true }),

  // --- 첫 화면: 가입 / 로그인 / 기기 등록 ---
  signUp: (base: string, user_id: string, name: string, password: string) =>
    request<AuthResult>(base, '/api/users', { method: 'POST', body: { user_id, name, password }, wake: true }),
  logIn: (base: string, user_id: string, password: string) =>
    request<AuthResult>(base, '/api/auth/login', { method: 'POST', body: { user_id, password }, wake: true }),
  logOut: (base: string, userToken: string) =>
    request<null>(base, '/api/auth/logout', { method: 'POST', userToken }),
  registerDevice: (base: string, userToken: string, device_id: string, user_id: string, label: string) =>
    request<Device>(base, '/api/devices', { method: 'POST', userToken, body: { device_id, user_id, label } }),
  listDevices: (base: string, userToken: string, userId: string) =>
    request<Device[]>(base, `/api/users/${encodeURIComponent(userId)}/devices`, { userToken }),
  /** 등록되지 않은 채 신호를 보내온 기기들 — 기기 ID 는 칩 MAC 이라 목록에서 고른다 */
  pendingDevices: (base: string, userToken: string, minutes = 180) =>
    request<PendingDevice[]>(base, `/api/devices/pending?minutes=${minutes}`, { userToken }),
  unregisterDevice: (base: string, userToken: string, deviceId: string) =>
    request<null>(base, `/api/devices/${deviceId}`, { method: 'DELETE', userToken }),

  // --- 사용자 페이지 ---
  summary: (base: string, userToken: string, userId: string) =>
    request<UserSummary>(base, `/api/users/${encodeURIComponent(userId)}/summary`, { userToken }),
  sessions: (base: string, userToken: string, userId: string, limit = 30) =>
    request<Session[]>(base, `/api/users/${encodeURIComponent(userId)}/sessions?limit=${limit}`, { userToken }),
  sessionDetail: (base: string, userToken: string, sessionId: number) =>
    request<SessionDetail>(base, `/api/sessions/${sessionId}`, { userToken }),
  /** 홈 화면 한 장을 그리는 데 필요한 상태 (연결·진행 중인 기기 사용·워밍업 완료) */
  deviceStatus: (base: string, userToken: string, deviceId: string) =>
    request<DeviceStatus>(base, `/api/devices/${deviceId}/status`, { userToken }),
  /** 시작/중지 버튼 → 브리지를 거쳐 기기로 전달된다 */
  sendCommand: (base: string, userToken: string, deviceId: string, command: 'start' | 'abort' | 'off') =>
    request<CommandOut>(base, `/api/devices/${deviceId}/commands`, {
      method: 'POST',
      userToken,
      body: { command },
    }),
  commandStatus: (base: string, userToken: string, deviceId: string, commandId: number) =>
    request<CommandOut>(base, `/api/devices/${deviceId}/commands/${commandId}`, { userToken }),
  /** 아침 수면 평가(별점 + 특이사항) */
  reviewSession: (
    base: string,
    userToken: string,
    sessionId: number,
    rating: number,
    note_code: NoteCode,
    note_text = '',
  ) =>
    request<Session>(base, `/api/sessions/${sessionId}/review`, {
      method: 'POST',
      userToken,
      body: { rating, note_code, note_text },
    })
};
