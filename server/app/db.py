"""SQLite 데이터 레이어.

사용자(id) → 기기 → 세션 → 측정 샘플/이벤트 구조로 쌓인다.
관리자 페이지는 이 테이블들을 id 기준으로 집계해서 보여준다.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

DB_PATH = os.environ.get("SLEEP_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "sleep.db"))

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

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
"""

# 기존 DB 파일에 나중에 추가된 컬럼(구버전 DB 호환)
MIGRATIONS: dict[str, dict[str, str]] = {
    "sessions": {
        "rating": "INTEGER",
        "note_code": "TEXT",
        "note_text": "TEXT",
        "reviewed_at": "TEXT",
    },
}


def _apply_migrations(conn: sqlite3.Connection) -> None:
    for table, columns in MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    directory = os.path.dirname(os.path.abspath(target))
    os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: str | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _apply_migrations(conn)


@contextmanager
def session_scope(path: str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
