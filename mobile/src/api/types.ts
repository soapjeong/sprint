export type User = { user_id: string; name: string; created_at: string };

export type Device = {
  device_id: string;
  user_id: string;
  label: string;
  registered_at: string;
  last_seen_at: string | null;
};

export type SessionOutcome = 'running' | 'onset' | 'no_onset' | 'aborted' | 'fault';

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

export type AdminUserRow = {
  user_id: string;
  name: string;
  created_at: string;
  device_count: number;
  session_count: number;
  onset_count: number;
  avg_sol_min: number | null;
  last_session_at: string | null;
};

export type AdminUserDetail = {
  user: User;
  devices: Device[];
  sessions: Session[];
  recent_events: SessionEvent[];
};
