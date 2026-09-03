"""데이터 레이어 — SQLite(로컬) / PostgreSQL(배포) 양쪽을 지원한다.

사용자(id) → 기기 → 세션 → 측정 샘플/이벤트 구조로 쌓인다.
관리자 페이지는 이 테이블들을 id 기준으로 집계해서 보여준다.

  DATABASE_URL 이 있으면 PostgreSQL, 없으면 SLEEP_DB_PATH 의 SQLite 파일을 쓴다.
  질의는 SQLite 문법(`?` 파라미터)으로 한 벌만 쓰고, PostgreSQL 로 보낼 때 변환한다.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Sequence

DB_PATH = os.environ.get("SLEEP_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "sleep.db"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")


def is_postgres() -> bool:
    return bool(DATABASE_URL)
SQLITE_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    name          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    password_salt TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL DEFAULT ''
);

-- 로그인 후 앱이 보관하는 접근 토큰(기기마다 하나). 로그아웃하면 지운다.
CREATE TABLE IF NOT EXISTS auth_tokens (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_auth_user ON auth_tokens(user_id);

CREATE TABLE IF NOT EXISTS devices (
    device_id     TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    label         TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL,
    last_seen_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    session_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    device_id       TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    device_start_ms INTEGER NOT NULL DEFAULT 0,
    target_temp_c   REAL,
    resting_bpm     REAL,
    threshold_bpm   REAL,
    sol_min         REAL,
    outcome         TEXT NOT NULL DEFAULT 'running',  -- running | onset | no_onset | aborted | fault
    -- 아침에 사용자가 남기는 수면 평가
    rating          INTEGER,                          -- 1~5 별점
    note_code       TEXT,                             -- alcohol | caffeine | none | other
    note_text       TEXT,                             -- note_code='other' 일 때의 자유 입력
    reviewed_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_open ON sessions(device_id, outcome);

CREATE TABLE IF NOT EXISTS samples (
    sample_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    recorded_at   TEXT NOT NULL,
    device_ms     INTEGER NOT NULL,
    elapsed_s     INTEGER NOT NULL,
    skin_c        REAL,
    heater_c      REAL,
    target_c      REAL,
    duty_pct      REAL,
    bpm           REAL,
    resting_bpm   REAL,
    threshold_bpm REAL,
    sensor_state  TEXT,
    safety_state  TEXT,
    session_state TEXT,
    quiet_min     INTEGER,
    asleep        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_samples_session ON samples(session_id, device_ms);

CREATE TABLE IF NOT EXISTS events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(session_id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL,
    device_id  TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    device_ms  INTEGER NOT NULL DEFAULT 0,
    flag       TEXT NOT NULL,
    v1         REAL,
    v2         REAL,
    raw        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, event_id);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id, event_id DESC);

-- 아직 어느 사용자에게도 등록되지 않은 채 신호를 보내온 기기.
-- 앱의 "연결된 기기 찾기" 목록이 여기서 나온다.
CREATE TABLE IF NOT EXISTS pending_devices (
    device_id     TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    firmware      TEXT NOT NULL DEFAULT ''
);

-- 앱에서 누른 버튼을 기기까지 전달하는 명령 큐 (앱 -> 서버 -> 브리지 -> 시리얼)
CREATE TABLE IF NOT EXISTS device_commands (
    command_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    command      TEXT NOT NULL,                    -- start | abort | off
    requested_by TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | done | failed
    sent_at      TEXT,
    acked_at     TEXT,
    detail       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_commands_device ON device_commands(device_id, status, command_id);

"""

# 같은 구조의 PostgreSQL 판 (배포용)
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    name          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    password_salt TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL DEFAULT ''
);

-- 로그인 후 앱이 보관하는 접근 토큰(기기마다 하나). 로그아웃하면 지운다.
CREATE TABLE IF NOT EXISTS auth_tokens (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_auth_user ON auth_tokens(user_id);

CREATE TABLE IF NOT EXISTS devices (
    device_id     TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    label         TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL,
    last_seen_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    session_id      BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    device_id       TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    device_start_ms INTEGER NOT NULL DEFAULT 0,
    target_temp_c   DOUBLE PRECISION,
    resting_bpm     DOUBLE PRECISION,
    threshold_bpm   DOUBLE PRECISION,
    sol_min         DOUBLE PRECISION,
    outcome         TEXT NOT NULL DEFAULT 'running',  -- running | onset | no_onset | aborted | fault
    -- 아침에 사용자가 남기는 수면 평가
    rating          INTEGER,                          -- 1~5 별점
    note_code       TEXT,                             -- alcohol | caffeine | none | other
    note_text       TEXT,                             -- note_code='other' 일 때의 자유 입력
    reviewed_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_open ON sessions(device_id, outcome);

CREATE TABLE IF NOT EXISTS samples (
    sample_id     BIGSERIAL PRIMARY KEY,
    session_id    INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    recorded_at   TEXT NOT NULL,
    device_ms     INTEGER NOT NULL,
    elapsed_s     INTEGER NOT NULL,
    skin_c        DOUBLE PRECISION,
    heater_c      DOUBLE PRECISION,
    target_c      DOUBLE PRECISION,
    duty_pct      DOUBLE PRECISION,
    bpm           DOUBLE PRECISION,
    resting_bpm   DOUBLE PRECISION,
    threshold_bpm DOUBLE PRECISION,
    sensor_state  TEXT,
    safety_state  TEXT,
    session_state TEXT,
    quiet_min     INTEGER,
    asleep        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_samples_session ON samples(session_id, device_ms);

CREATE TABLE IF NOT EXISTS events (
    event_id   BIGSERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(session_id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL,
    device_id  TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    device_ms  INTEGER NOT NULL DEFAULT 0,
    flag       TEXT NOT NULL,
    v1         DOUBLE PRECISION,
    v2         DOUBLE PRECISION,
    raw        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, event_id);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id, event_id DESC);

-- 아직 어느 사용자에게도 등록되지 않은 채 신호를 보내온 기기.
-- 앱의 "연결된 기기 찾기" 목록이 여기서 나온다.
CREATE TABLE IF NOT EXISTS pending_devices (
    device_id     TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    firmware      TEXT NOT NULL DEFAULT ''
);



-- 앱에서 누른 버튼을 기기까지 전달하는 명령 큐 (앱 -> 서버 -> 브리지 -> 시리얼)
CREATE TABLE IF NOT EXISTS device_commands (
    command_id   BIGSERIAL PRIMARY KEY,
    device_id    TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    command      TEXT NOT NULL,                    -- start | abort | off
    requested_by TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | done | failed
    sent_at      TEXT,
    acked_at     TEXT,
    detail       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_commands_device ON device_commands(device_id, status, command_id);

"""

# 나중에 추가된 컬럼(구버전 DB 호환). 두 엔진 모두에서 통하는 타입만 쓴다.
MIGRATIONS: dict[str, dict[str, str]] = {
    "users": {
        "password_salt": "TEXT NOT NULL DEFAULT ''",
        "password_hash": "TEXT NOT NULL DEFAULT ''",
    },
    "devices": {
        # 브리지가 알려주는 연결 상태: online | no_data | no_port | unknown
        "link_state": "TEXT NOT NULL DEFAULT 'unknown'",
        "link_seen_at": "TEXT",
        "battery_pct": "REAL",
    },
    "sessions": {
        "onset_at": "TEXT",
        "rating": "INTEGER",
        "note_code": "TEXT",
        "note_text": "TEXT",
        "reviewed_at": "TEXT",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_pg(sql: str) -> str:
    """SQLite 문법으로 쓴 질의를 psycopg 파라미터 형식으로 바꾼다."""
    return sql.replace("?", "%s")


class PgConnection:
    """psycopg 연결을 sqlite3.Connection 과 같은 방식으로 쓰게 감싼다."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self._raw.cursor()
        cur.execute(_to_pg(sql), tuple(params))
        return cur

    def executemany(self, sql: str, seq: Sequence[Sequence[Any]]) -> Any:
        cur = self._raw.cursor()
        cur.executemany(_to_pg(sql), [tuple(p) for p in seq])
        return cur

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


def connect(path: str | None = None) -> Any:
    if is_postgres():
        import psycopg
        from psycopg.rows import dict_row

        return PgConnection(psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False))

    target = path or DB_PATH
    directory = os.path.dirname(os.path.abspath(target))
    os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _existing_columns(conn: Any, table: str) -> set[str]:
    if is_postgres():
        rows = conn.execute(
            "SELECT column_name AS name FROM information_schema.columns WHERE table_name=?",
            (table,),
        ).fetchall()
    else:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _apply_migrations(conn: Any) -> None:
    for table, columns in MIGRATIONS.items():
        existing = _existing_columns(conn, table)
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db(path: str | None = None) -> None:
    conn = connect(path)
    try:
        schema = POSTGRES_SCHEMA if is_postgres() else SQLITE_SCHEMA
        for statement in schema.split(";"):
            if statement.strip():
                conn.execute(statement)
        _apply_migrations(conn)
        conn.commit()
    finally:
        conn.close()


def insert_returning_id(conn: Any, sql: str, params: Sequence[Any], id_column: str) -> int:
    """INSERT 후 새 행의 정수 키를 돌려준다(엔진별 차이를 여기서 흡수)."""
    if is_postgres():
        row = conn.execute(f"{sql} RETURNING {id_column}", params).fetchone()
        return int(row[id_column])
    cur = conn.execute(sql, params)
    return int(cur.lastrowid)


@contextmanager
def session_scope(path: str | None = None) -> Iterator[Any]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
