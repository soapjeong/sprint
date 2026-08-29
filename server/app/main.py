"""ESP32 수면 온도 최적화기 — 사용자/관리자 공용 API 서버.

경로 구조
  공개(앱 사용자)   : /api/users, /api/devices, /api/users/{id}/...
  브리지 업로드     : /api/ingest/*            (X-API-Key)
  관리자            : /api/admin/*             (X-Admin-Token)
"""
from __future__ import annotations

import io
import csv
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse

from . import db
from .models import (
    AdminUserRow,
    DeviceOut,
    DeviceRegister,
    EventIn,
    IngestResult,
    SampleBatch,
    SessionOut,
    TempStat,
    UserCreate,
    UserOut,
    UserSummary,
)
from .security import require_admin, require_ingest_key

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    yield


app = FastAPI(title="Sleep Onset Optimizer API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 모바일 앱/Expo 웹 개발 편의용
    allow_methods=["*"],
    allow_headers=["*"],
)

# 세션을 마감시키는 플래그와, 그때 기록할 결과
TERMINAL_FLAGS = {"SLEEP_ONSET": "onset", "NO_ONSET": "no_onset"}
CLOSING_FLAGS = {"POWER_OFF", "SESSION_DONE"}
# 세션이 닫힌 뒤에도 이 시간(초) 안에 도착한 샘플은 그 세션에 붙인다
LATE_SAMPLE_WINDOW_S = 600


# ---------------------------------------------------------------- helpers
def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _get_user(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"등록되지 않은 사용자입니다: {user_id}")
    return row


def _get_device(conn: sqlite3.Connection, device_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"등록되지 않은 기기입니다: {device_id}")
    return row


def _open_session(conn: sqlite3.Connection, device_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sessions WHERE device_id=? AND ended_at IS NULL ORDER BY session_id DESC LIMIT 1",
        (device_id,),
    ).fetchone()


def _session_for_samples(conn: sqlite3.Connection, device_id: str) -> Optional[sqlite3.Row]:
    """진행 중인 세션, 없으면 방금(LATE_SAMPLE_WINDOW_S 이내) 끝난 세션.

    브리지가 샘플을 배치로 올리기 때문에 세션 종료 이벤트보다 늦게 도착하는 묶음이 있다.
    그 마지막 몇 초를 버리지 않도록 최근에 닫힌 세션까지 허용한다.
    """
    session = _open_session(conn, device_id)
    if session is not None:
        return session
    row = conn.execute(
        "SELECT * FROM sessions WHERE device_id=? ORDER BY session_id DESC LIMIT 1", (device_id,)
    ).fetchone()
    if row is None or not row["ended_at"]:
        return None
    try:
        ended = datetime.fromisoformat(row["ended_at"])
    except ValueError:
        return None
    if (datetime.now(timezone.utc) - ended).total_seconds() <= LATE_SAMPLE_WINDOW_S:
        return row
    return None


def _value(values: list[float], idx: int) -> Optional[float]:
    return values[idx] if len(values) > idx else None


# ---------------------------------------------------------------- 사용자 / 기기 등록
@app.post("/api/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate) -> UserOut:
    """첫 화면에서 사용자 ID를 등록한다. 이미 있으면 409."""
    with db.session_scope() as conn:
        if conn.execute("SELECT 1 FROM users WHERE user_id=?", (payload.user_id,)).fetchone():
            raise HTTPException(status.HTTP_409_CONFLICT, "이미 사용 중인 ID 입니다.")
        created = db.now_iso()
        conn.execute(
            "INSERT INTO users(user_id, name, created_at) VALUES(?,?,?)",
            (payload.user_id, payload.name, created),
        )
        return UserOut(user_id=payload.user_id, name=payload.name, created_at=created)


@app.get("/api/users/{user_id}", response_model=UserOut)
def get_user(user_id: str) -> UserOut:
    with db.session_scope() as conn:
        return UserOut(**_row_to_dict(_get_user(conn, user_id)))


@app.post("/api/devices", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
def register_device(payload: DeviceRegister) -> DeviceOut:
    """기기 등록. 같은 기기를 다시 등록하면 소유자/별칭을 갱신한다."""
    with db.session_scope() as conn:
        _get_user(conn, payload.user_id)
        existing = conn.execute(
            "SELECT * FROM devices WHERE device_id=?", (payload.device_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE devices SET user_id=?, label=? WHERE device_id=?",
                (payload.user_id, payload.label or existing["label"], payload.device_id),
            )
        else:
            conn.execute(
                "INSERT INTO devices(device_id, user_id, label, registered_at) VALUES(?,?,?,?)",
                (payload.device_id, payload.user_id, payload.label, db.now_iso()),
            )
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (payload.device_id,)).fetchone()
        return DeviceOut(**_row_to_dict(row))


@app.get("/api/users/{user_id}/devices", response_model=list[DeviceOut])
def list_devices(user_id: str) -> list[DeviceOut]:
    with db.session_scope() as conn:
        _get_user(conn, user_id)
        rows = conn.execute(
            "SELECT * FROM devices WHERE user_id=? ORDER BY registered_at", (user_id,)
        ).fetchall()
        return [DeviceOut(**_row_to_dict(r)) for r in rows]


@app.delete("/api/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def unregister_device(device_id: str) -> None:
    with db.session_scope() as conn:
        _get_device(conn, device_id)
        conn.execute("DELETE FROM devices WHERE device_id=?", (device_id,))


# ---------------------------------------------------------------- 사용자 페이지 조회
def _session_rows(conn: sqlite3.Connection, user_id: str, limit: int) -> list[SessionOut]:
    rows = conn.execute(
        "SELECT * FROM sessions WHERE user_id=? ORDER BY session_id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [SessionOut(**_row_to_dict(r)) for r in rows]


@app.get("/api/users/{user_id}/sessions", response_model=list[SessionOut])
def user_sessions(user_id: str, limit: int = Query(default=30, ge=1, le=200)) -> list[SessionOut]:
    with db.session_scope() as conn:
        _get_user(conn, user_id)
        return _session_rows(conn, user_id, limit)


@app.get("/api/users/{user_id}/summary", response_model=UserSummary)
def user_summary(user_id: str) -> UserSummary:
    """사용자 홈 화면용 집계: 세션 수, 평균/최단 SOL, 온도별 성적."""
    with db.session_scope() as conn:
        user = _get_user(conn, user_id)
        devices = [
            DeviceOut(**_row_to_dict(r))
            for r in conn.execute(
                "SELECT * FROM devices WHERE user_id=? ORDER BY registered_at", (user_id,)
            ).fetchall()
        ]
        agg = conn.execute(
            """SELECT COUNT(*) AS n,
                      SUM(CASE WHEN outcome='onset' THEN 1 ELSE 0 END) AS onsets,
                      AVG(CASE WHEN outcome='onset' THEN sol_min END) AS avg_sol,
                      MIN(CASE WHEN outcome='onset' THEN sol_min END) AS best_sol
                 FROM sessions WHERE user_id=?""",
            (user_id,),
        ).fetchone()
        stats = [
            TempStat(
                target_temp_c=r["target_temp_c"],
                avg_sol_min=round(r["avg_sol"], 2),
                onset_count=r["n"],
            )
            for r in conn.execute(
                """SELECT target_temp_c, AVG(sol_min) AS avg_sol, COUNT(*) AS n
                     FROM sessions
                    WHERE user_id=? AND outcome='onset' AND target_temp_c IS NOT NULL
                    GROUP BY target_temp_c ORDER BY target_temp_c""",
                (user_id,),
            ).fetchall()
        ]
        best_temp = min(stats, key=lambda s: s.avg_sol_min).target_temp_c if stats else None
        return UserSummary(
            user=UserOut(**_row_to_dict(user)),
            devices=devices,
            session_count=agg["n"] or 0,
            onset_count=agg["onsets"] or 0,
            avg_sol_min=round(agg["avg_sol"], 2) if agg["avg_sol"] is not None else None,
            best_sol_min=agg["best_sol"],
            best_temp_c=best_temp,
            temp_stats=stats,
            recent_sessions=_session_rows(conn, user_id, 10),
        )


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: int, samples: int = Query(default=600, ge=0, le=5000)) -> dict[str, Any]:
    with db.session_scope() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "세션을 찾을 수 없습니다.")
        sample_rows = conn.execute(
            "SELECT * FROM samples WHERE session_id=? ORDER BY device_ms LIMIT ?",
            (session_id, samples),
        ).fetchall()
        event_rows = conn.execute(
            "SELECT * FROM events WHERE session_id=? ORDER BY event_id", (session_id,)
        ).fetchall()
        return {
            "session": _row_to_dict(row),
            "samples": [_row_to_dict(r) for r in sample_rows],
            "events": [_row_to_dict(r) for r in event_rows],
        }


# ---------------------------------------------------------------- 브리지 업로드
@app.post("/api/ingest/events", response_model=IngestResult, dependencies=[Depends(require_ingest_key)])
def ingest_event(payload: EventIn) -> IngestResult:
    """펌웨어의 @FLAG / @RESULT 한 줄을 받아 세션 상태를 갱신한다."""
    flag = payload.flag.upper()
    with db.session_scope() as conn:
        device = _get_device(conn, payload.device_id)
        user_id = device["user_id"]
        now = db.now_iso()
        conn.execute("UPDATE devices SET last_seen_at=? WHERE device_id=?", (now, payload.device_id))

        session = _open_session(conn, payload.device_id)
        detail = ""

        if flag == "SESSION_START":
            if session is not None:                       # 이전 세션이 안 닫혔으면 중단 처리
                conn.execute(
                    "UPDATE sessions SET ended_at=?, outcome=CASE outcome WHEN 'running' THEN 'aborted' ELSE outcome END"
                    " WHERE session_id=?",
                    (now, session["session_id"]),
                )
            cur = conn.execute(
                "INSERT INTO sessions(user_id, device_id, started_at, device_start_ms, target_temp_c)"
                " VALUES(?,?,?,?,?)",
                (user_id, payload.device_id, now, payload.device_ms, _value(payload.values, 0)),
            )
            session_id = int(cur.lastrowid)
            detail = "세션 시작"
        else:
            session_id = int(session["session_id"]) if session else None

            if session_id is not None:
                if flag in ("HR_BASELINE", "HR_BASELINE_FALLBACK"):
                    conn.execute(
                        "UPDATE sessions SET resting_bpm=?, threshold_bpm=? WHERE session_id=?",
                        (_value(payload.values, 0), _value(payload.values, 1), session_id),
                    )
                    detail = "안정심박수 기록"
                elif flag in TERMINAL_FLAGS:
                    conn.execute(
                        "UPDATE sessions SET sol_min=?, outcome=? WHERE session_id=?",
                        (_value(payload.values, 0), TERMINAL_FLAGS[flag], session_id),
                    )
                    detail = "입면 결과 기록"
                elif flag in CLOSING_FLAGS:
                    conn.execute(
                        "UPDATE sessions SET ended_at=?,"
                        " outcome=CASE outcome WHEN 'running' THEN 'aborted' ELSE outcome END"
                        " WHERE session_id=?",
                        (now, session_id),
                    )
                    detail = "세션 종료"
            else:
                detail = "진행 중인 세션이 없어 이벤트만 저장했습니다."

        conn.execute(
            "INSERT INTO events(session_id, user_id, device_id, recorded_at, device_ms, flag, v1, v2, raw)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                user_id,
                payload.device_id,
                now,
                payload.device_ms,
                flag,
                _value(payload.values, 0),
                _value(payload.values, 1),
                payload.raw,
            ),
        )
        return IngestResult(stored=1, session_id=session_id, detail=detail)


@app.post("/api/ingest/samples", response_model=IngestResult, dependencies=[Depends(require_ingest_key)])
def ingest_samples(payload: SampleBatch) -> IngestResult:
    """1초 주기 측정 로그를 배치로 받는다. 진행 중인 세션이 없으면 버린다."""
    with db.session_scope() as conn:
        _get_device(conn, payload.device_id)
        now = db.now_iso()
        conn.execute("UPDATE devices SET last_seen_at=? WHERE device_id=?", (now, payload.device_id))
        session = _session_for_samples(conn, payload.device_id)
        if session is None:
            return IngestResult(stored=0, skipped=len(payload.samples), detail="진행 중인 세션 없음")

        start_ms = int(session["device_start_ms"])
        rows = [
            (
                int(session["session_id"]),
                now,
                s.device_ms,
                max(0, (s.device_ms - start_ms) // 1000),
                s.skin_c, s.heater_c, s.target_c, s.duty_pct,
                s.bpm, s.resting_bpm, s.threshold_bpm,
                s.sensor_state, s.safety_state, s.session_state,
                s.quiet_min, 1 if s.asleep else 0,
            )
            for s in payload.samples
        ]
        conn.executemany(
            "INSERT INTO samples(session_id, recorded_at, device_ms, elapsed_s, skin_c, heater_c,"
            " target_c, duty_pct, bpm, resting_bpm, threshold_bpm, sensor_state, safety_state,"
            " session_state, quiet_min, asleep) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        return IngestResult(stored=len(rows), session_id=int(session["session_id"]))


# ---------------------------------------------------------------- 관리자
@app.get("/api/admin/users", response_model=list[AdminUserRow], dependencies=[Depends(require_admin)])
def admin_users() -> list[AdminUserRow]:
    """ID별로 쌓인 데이터 현황 — 관리자 페이지 첫 화면."""
    with db.session_scope() as conn:
        rows = conn.execute(
            """SELECT u.user_id, u.name, u.created_at,
                      (SELECT COUNT(*) FROM devices d WHERE d.user_id=u.user_id) AS device_count,
                      (SELECT COUNT(*) FROM sessions s WHERE s.user_id=u.user_id) AS session_count,
                      (SELECT COUNT(*) FROM sessions s WHERE s.user_id=u.user_id AND s.outcome='onset') AS onset_count,
                      (SELECT AVG(sol_min) FROM sessions s WHERE s.user_id=u.user_id AND s.outcome='onset') AS avg_sol,
                      (SELECT MAX(started_at) FROM sessions s WHERE s.user_id=u.user_id) AS last_session_at
                 FROM users u ORDER BY u.created_at DESC"""
        ).fetchall()
        return [
            AdminUserRow(
                user_id=r["user_id"], name=r["name"], created_at=r["created_at"],
                device_count=r["device_count"], session_count=r["session_count"],
                onset_count=r["onset_count"],
                avg_sol_min=round(r["avg_sol"], 2) if r["avg_sol"] is not None else None,
                last_session_at=r["last_session_at"],
            )
            for r in rows
        ]


@app.get("/api/admin/users/{user_id}", dependencies=[Depends(require_admin)])
def admin_user_detail(user_id: str) -> dict[str, Any]:
    with db.session_scope() as conn:
        user = _get_user(conn, user_id)
        devices = conn.execute("SELECT * FROM devices WHERE user_id=?", (user_id,)).fetchall()
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE user_id=? ORDER BY session_id DESC LIMIT 200", (user_id,)
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM events WHERE user_id=? ORDER BY event_id DESC LIMIT 100", (user_id,)
        ).fetchall()
        return {
            "user": _row_to_dict(user),
            "devices": [_row_to_dict(r) for r in devices],
            "sessions": [_row_to_dict(r) for r in sessions],
            "recent_events": [_row_to_dict(r) for r in events],
        }


@app.get("/api/admin/export/sessions.csv", dependencies=[Depends(require_admin)], response_class=PlainTextResponse)
def admin_export_sessions(user_id: Optional[str] = None) -> PlainTextResponse:
    """세션 단위 CSV 내보내기(엑셀/논문용)."""
    query = (
        "SELECT session_id, user_id, device_id, started_at, ended_at, target_temp_c,"
        " resting_bpm, threshold_bpm, sol_min, outcome FROM sessions"
    )
    params: tuple[Any, ...] = ()
    if user_id:
        query += " WHERE user_id=?"
        params = (user_id,)
    query += " ORDER BY session_id"

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["session_id", "user_id", "device_id", "started_at", "ended_at",
         "target_temp_c", "resting_bpm", "threshold_bpm", "sol_min", "outcome"]
    )
    with db.session_scope() as conn:
        for r in conn.execute(query, params).fetchall():
            writer.writerow([r[k] for k in r.keys()])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv; charset=utf-8")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    """브라우저로 서버 주소를 열었을 때 보여주는 상태 페이지.

    앱이 아니라 '서버가 살아있는지' 확인하는 용도. 앱 화면은 모바일에서 Expo 로 연다.
    """
    with db.session_scope() as conn:
        users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        devices = conn.execute("SELECT COUNT(*) AS n FROM devices").fetchone()["n"]
        sessions = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    return HTMLResponse(f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>DormX 백엔드</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; margin: 0;
         padding: 40px 24px; line-height: 1.6; }}
  main {{ max-width: 640px; margin: 0 auto; }}
  .ok {{ display: inline-block; padding: 4px 10px; border-radius: 999px;
         background: #1baf7a; color: #fff; font-size: 13px; font-weight: 600; }}
  code {{ background: rgba(128,128,128,.18); padding: 2px 6px; border-radius: 4px; }}
  table {{ border-collapse: collapse; margin: 16px 0; }}
  td {{ padding: 4px 16px 4px 0; }}
  ol {{ padding-left: 20px; }}
</style></head>
<body><main>
  <p><span class="ok">서버 실행 중</span></p>
  <h1>DormX 백엔드</h1>
  <p>이 페이지는 서버가 살아있는지 확인하는 용도입니다.
     <strong>사용자·관리자 화면은 이 주소가 아니라 모바일 앱에서</strong> 보입니다.</p>
  <table>
    <tr><td>등록 사용자</td><td><strong>{users}</strong> 명</td></tr>
    <tr><td>등록 기기</td><td><strong>{devices}</strong> 대</td></tr>
    <tr><td>누적 세션</td><td><strong>{sessions}</strong> 회</td></tr>
  </table>
  <h2>앱 여는 순서</h2>
  <ol>
    <li>PC 에서 <code>cd mobile</code> → <code>npm install</code> → <code>npx expo start</code></li>
    <li>폰에 <b>Expo Go</b> 앱을 설치하고 터미널의 QR 코드를 스캔</li>
    <li>앱 첫 화면 <b>서버 주소</b> 칸에 이 PC 의 주소(<code>http://[PC의 LAN IP]:8000</code>)를 입력
        — 주소는 서버를 켠 터미널 맨 위에 찍혀 있습니다</li>
  </ol>
  <p><a href="/docs">API 문서 열기</a></p>
</main></body></html>""")
