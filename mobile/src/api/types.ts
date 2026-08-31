export type User = { user_id: string; name: string; created_at: string };

/** 가입/로그인 결과 — access_token 을 저장해 이후 요청 헤더에 싣는다 */
export type AuthResult = { user: User; access_token: string };

export type Device = {
  device_id: string;
  user_id: string;
  label: string;
  registered_at: string;
  last_seen_at: string | null;
};

export type SessionOutcome = 'running' | 'onset' | 'no_onset' | 'aborted' | 'fault';

/** 아침 평가의 특이사항 선택지 */
export type NoteCode = 'alcohol' | 'caffeine' | 'none' | 'other';

export const NOTE_OPTIONS: { code: NoteCode; label: string }[] = [
  { code: 'alcohol', label: '음주' },
  { code: 'caffeine', label: '취침 6시간 이내 카페인 섭취' },
  { code: 'none', label: '없음' },
  { code: 'other', label: '기타' },
];

export type PendingDevice = {
  device_id: string;
  first_seen_at: string;
  last_seen_at: string;
  firmware: string;
};

export type Session = {
  session_id: number;
  user_id: string;
  device_id: string;
  started_at: string;
  ended_at: string | null;
  target_temp_c: number | null;
  resting_bpm: number | null;
  threshold_bpm: number | null;
  sol_min: number | null;
  outcome: SessionOutcome;
  rating: number | null;
  note_code: NoteCode | null;
  note_text: string | null;
  reviewed_at: string | null;
};

export type TempStat = { target_temp_c: number; avg_sol_min: number; onset_count: number };

export type UserSummary = {
  user: User;
  devices: Device[];
  session_count: number;
  onset_count: number;
  avg_sol_min: number | null;
  best_sol_min: number | null;
  best_temp_c: number | null;
  temp_stats: TempStat[];
  recent_sessions: Session[];
  /** 아직 별점을 남기지 않은 최근 세션 — 있으면 홈에 평가 카드를 띄운다 */
  pending_review: Session | null;
  avg_rating: number | null;
};

export type Sample = {
  sample_id: number;
  session_id: number;
  elapsed_s: number;
  skin_c: number | null;
  heater_c: number | null;
  target_c: number | null;
  duty_pct: number | null;
  bpm: number | null;
  resting_bpm: number | null;
  threshold_bpm: number | null;
  sensor_state: string | null;
  safety_state: string | null;
  session_state: string | null;
  quiet_min: number | null;
  asleep: number;
};

export type SessionEvent = {
  event_id: number;
  session_id: number | null;
  user_id: string;
  device_id: string;
  recorded_at: string;
  device_ms: number;
  flag: string;
  v1: number | null;
  v2: number | null;
};

export type SessionDetail = { session: Session; samples: Sample[]; events: SessionEvent[] };
