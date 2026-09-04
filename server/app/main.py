"""ESP32 수면 온도 최적화기 — 사용자/관리자 공용 API 서버.

경로 구조
  공개(앱 사용자)   : /api/users, /api/devices, /api/users/{id}/...
  브리지 업로드     : /api/ingest/*            (X-API-Key)
  관리자            : /api/admin/*             (X-Admin-Token)
"""
from __future__ import annotations

import io
import csv
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .models import (
    AdminUserRow,
    AnnounceResult,
    AuthResult,
    CommandAck,
    CommandOut,
    CommandRequest,
    DeviceAnnounce,
    DeviceStatus,
    DeviceOut,
    DeviceRegister,
    EventIn,
    HeartbeatIn,
    IngestResult,
    LoginRequest,
    PendingDevice,
    SampleBatch,
    SessionOut,
    SessionReview,
    TempStat,
    UserCreate,
    UserOut,
    UserSummary,
)
from .security import (
    check_startup_config,
    dev_tokens_allowed,
    hash_password,
    new_access_token,
    require_admin,
    require_ingest_key,
    verify_password,
)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    problems = check_startup_config()
    if problems:
        message = " ".join(problems)
        if not dev_tokens_allowed():
            # 인터넷에 공개된 서버가 기본 토큰으로 뜨는 것을 막는다.
            raise RuntimeError(
                f"{message} ADMIN_TOKEN / INGEST_API_KEY 환경변수를 설정하세요. "
                "(로컬 개발이면 SLEEP_ALLOW_DEV_TOKENS=1)"
            )
        print(f"[경고] {message} 로컬 개발 모드로 실행합니다.")
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
# 펌웨어가 NO_ONSET 과 함께 보내는 원인 코드
NO_ONSET_REASONS = {0: "unknown", 1: "hr_high", 2: "motion", 3: "sensor"}
# 세션이 닫힌 뒤에도 이 시간(초) 안에 도착한 샘플은 그 세션에 붙인다
LATE_SAMPLE_WINDOW_S = 600
# 이 기록을 만든 start 경로(펌웨어가 SESSION_START 의 v2 로 보낸다)
START_SOURCES = {1: "button", 2: "app"}
# 같은 start 를 두 번 받은 경우(브리지 재연결·기기 리부팅) 새 기록을 만들지 않는 시간(초).
# 관리자 페이지의 "기기 사용"은 start 를 누른 횟수와 1:1 로 맞아야 한다.
START_DEDUP_WINDOW_S = 60


# ---------------------------------------------------------------- helpers
def _row_to_dict(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _num(value: Any, digits: int | None = None) -> Optional[float]:
    """집계 결과를 float 으로 통일한다(PostgreSQL 의 AVG 는 Decimal 을 준다)."""
    if value is None:
        return None
    return round(float(value), digits) if digits is not None else float(value)


def current_user(x_user_token: str = Header(default="")) -> str:
    """X-User-Token 을 사용자 ID 로 바꾼다. 없거나 모르는 토큰이면 401."""
    if not x_user_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다.")
    with db.session_scope() as conn:
        row = conn.execute(
            "SELECT user_id FROM auth_tokens WHERE token=?", (x_user_token,)
        ).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 만료되었습니다. 다시 로그인하세요.")
        conn.execute("UPDATE auth_tokens SET last_used_at=? WHERE token=?", (db.now_iso(), x_user_token))
        return str(row["user_id"])


def _require_self(caller: str, user_id: str) -> None:
    if caller != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "다른 사용자의 데이터에는 접근할 수 없습니다.")


def _issue_token(conn: Any, user_id: str) -> str:
    token = new_access_token()
    conn.execute(
        "INSERT INTO auth_tokens(token, user_id, created_at) VALUES(?,?,?)",
        (token, user_id, db.now_iso()),
    )
    return token


def _get_user(conn: Any, user_id: str) -> Any:
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"등록되지 않은 사용자입니다: {user_id}")
    return row


def _get_device(conn: Any, device_id: str) -> Any:
    row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"등록되지 않은 기기입니다: {device_id}")
    return row


def _open_session(conn: Any, device_id: str) -> Optional[Any]:
    return conn.execute(
        "SELECT * FROM sessions WHERE device_id=? AND ended_at IS NULL ORDER BY session_id DESC LIMIT 1",
        (device_id,),
    ).fetchone()


def _session_for_samples(conn: Any, device_id: str) -> Optional[Any]:
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


def _repeat_start(session: Optional[Any]) -> bool:
    """이미 열린 기록이 방금 시작된 것이라면, 이번 SESSION_START 는 같은 start 의 재수신이다.

    브리지가 다시 붙거나 기기가 부팅 직후 한 번 더 보고할 때 "기기 사용" 기록이
    두 줄로 늘어나는 것을 막는다(관리자 페이지는 start 를 누른 횟수만 세야 한다).
    """
    if session is None:
        return False
    try:
        started = datetime.fromisoformat(session["started_at"])
    except (ValueError, TypeError):
        return False
    return (datetime.now(timezone.utc) - started).total_seconds() <= START_DEDUP_WINDOW_S


def _value(values: list[float], idx: int) -> Optional[float]:
    return values[idx] if len(values) > idx else None


# ---------------------------------------------------------------- 사용자 / 기기 등록
@app.post("/api/users", response_model=AuthResult, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate) -> AuthResult:
    """첫 화면에서 사용자 ID와 비밀번호를 등록한다. 이미 있으면 409."""
    with db.session_scope() as conn:
        if conn.execute("SELECT 1 FROM users WHERE user_id=?", (payload.user_id,)).fetchone():
            raise HTTPException(status.HTTP_409_CONFLICT, "이미 사용 중인 ID 입니다.")
        created = db.now_iso()
        salt, digest = hash_password(payload.password)
        conn.execute(
            "INSERT INTO users(user_id, name, created_at, password_salt, password_hash)"
            " VALUES(?,?,?,?,?)",
            (payload.user_id, payload.name, created, salt, digest),
        )
        token = _issue_token(conn, payload.user_id)
        return AuthResult(
            user=UserOut(user_id=payload.user_id, name=payload.name, created_at=created),
            access_token=token,
        )


@app.post("/api/auth/login", response_model=AuthResult)
def login(payload: LoginRequest) -> AuthResult:
    with db.session_scope() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (payload.user_id,)).fetchone()
        # ID 가 있는지 없는지 알려주지 않는다(계정 열거 방지)
        if row is None or not row["password_hash"] or not verify_password(
            payload.password, row["password_salt"], row["password_hash"]
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ID 또는 비밀번호가 올바르지 않습니다.")
        token = _issue_token(conn, payload.user_id)
        return AuthResult(
            user=UserOut(user_id=row["user_id"], name=row["name"], created_at=row["created_at"]),
            access_token=token,
        )


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(x_user_token: str = Header(default="")) -> None:
    with db.session_scope() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE token=?", (x_user_token,))


@app.get("/api/users/{user_id}", response_model=UserOut)
def get_user(user_id: str, caller: str = Depends(current_user)) -> UserOut:
    _require_self(caller, user_id)
    with db.session_scope() as conn:
        return UserOut(**_row_to_dict(_get_user(conn, user_id)))


@app.post("/api/devices", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
def register_device(payload: DeviceRegister, caller: str = Depends(current_user)) -> DeviceOut:
    _require_self(caller, payload.user_id)
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
        conn.execute("DELETE FROM pending_devices WHERE device_id=?", (payload.device_id,))
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (payload.device_id,)).fetchone()
        return DeviceOut(**_row_to_dict(row))


@app.get("/api/devices/pending", response_model=list[PendingDevice])
def pending_devices(
    minutes: int = Query(default=120, ge=1, le=1440),
    caller: str = Depends(current_user),
) -> list[PendingDevice]:
    """아직 등록되지 않은 채 신호를 보내온 기기 목록.

    기기 ID 는 칩 MAC 에서 만들어져 사람이 외울 수 없으므로, 앱은 이 목록에서 골라 등록한다.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with db.session_scope() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_devices WHERE last_seen_at >= ? ORDER BY last_seen_at DESC",
            (cutoff,),
        ).fetchall()
        return [PendingDevice(**_row_to_dict(r)) for r in rows]


@app.get("/api/users/{user_id}/devices", response_model=list[DeviceOut])
def list_devices(user_id: str, caller: str = Depends(current_user)) -> list[DeviceOut]:
    _require_self(caller, user_id)
    with db.session_scope() as conn:
        _get_user(conn, user_id)
        rows = conn.execute(
            "SELECT * FROM devices WHERE user_id=? ORDER BY registered_at", (user_id,)
        ).fetchall()
        return [DeviceOut(**_row_to_dict(r)) for r in rows]


@app.delete("/api/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def unregister_device(device_id: str, caller: str = Depends(current_user)) -> None:
    with db.session_scope() as conn:
        device = _get_device(conn, device_id)
        _require_self(caller, str(device["user_id"]))
        conn.execute("DELETE FROM devices WHERE device_id=?", (device_id,))


@app.post("/api/devices/{device_id}/commands", response_model=CommandOut,
          status_code=status.HTTP_201_CREATED)
def queue_command(
    device_id: str, payload: CommandRequest, caller: str = Depends(current_user)
) -> CommandOut:
    """앱의 버튼을 기기까지 전달한다. 브리지가 가져가 시리얼로 넣는다."""
    with db.session_scope() as conn:
        device = _get_device(conn, device_id)
        _require_self(caller, str(device["user_id"]))
        now = db.now_iso()
        command_id = db.insert_returning_id(
            conn,
            "INSERT INTO device_commands(device_id, command, requested_by, created_at)"
            " VALUES(?,?,?,?)",
            (device_id, payload.command, caller, now),
            "command_id",
        )
        row = conn.execute(
            "SELECT * FROM device_commands WHERE command_id=?", (command_id,)
        ).fetchone()
        return CommandOut(**_row_to_dict(row))


ONLINE_WINDOW_S = 45     # 이 시간 안에 하트비트가 있었으면 '연결됨'으로 본다


@app.get("/api/devices/{device_id}/status", response_model=DeviceStatus)
def device_status(device_id: str, caller: str = Depends(current_user)) -> DeviceStatus:
    """홈 화면 한 장을 그리는 데 필요한 것만 모아서 준다."""
    with db.session_scope() as conn:
        device = _get_device(conn, device_id)
        _require_self(caller, str(device["user_id"]))

        online = False
        if device["link_state"] == "online" and device["link_seen_at"]:
            try:
                seen = datetime.fromisoformat(str(device["link_seen_at"]))
                online = (datetime.now(timezone.utc) - seen).total_seconds() <= ONLINE_WINDOW_S
            except ValueError:
                online = False

        session = _open_session(conn, device_id)
        session_out = SessionOut(**_row_to_dict(session)) if session else None

        state = safety = None
        skin = duty = None
        warmup_done = False
        if session is not None:
            sample = conn.execute(
                "SELECT * FROM samples WHERE session_id=? ORDER BY sample_id DESC LIMIT 1",
                (session["session_id"],),
            ).fetchone()
            if sample is not None:
                state = sample["session_state"]
                safety = sample["safety_state"]
                skin = _num(sample["skin_c"])
                duty = _num(sample["duty_pct"])
            warmup_done = conn.execute(
                "SELECT 1 FROM events WHERE session_id=? AND flag='WARMUP_DONE' LIMIT 1",
                (session["session_id"],),
            ).fetchone() is not None

        target = _num(session["target_temp_c"]) if session else None
        if target is None:
            last = conn.execute(
                "SELECT target_temp_c FROM sessions WHERE device_id=? AND target_temp_c IS NOT NULL"
                " ORDER BY session_id DESC LIMIT 1",
                (device_id,),
            ).fetchone()
            target = _num(last["target_temp_c"]) if last else None

        pending = conn.execute(
            "SELECT command FROM device_commands WHERE device_id=? AND status IN ('pending','sent')"
            " ORDER BY command_id DESC LIMIT 1",
            (device_id,),
        ).fetchone()

        return DeviceStatus(
            device=DeviceOut(**_row_to_dict(device)),
            online=online,
            session=session_out,
            session_state=state,
            safety_state=safety,
            skin_c=skin,
            duty_pct=duty,
            warmup_done=warmup_done,
            target_temp_c=target,
            pending_command=pending["command"] if pending else None,
        )


@app.get("/api/devices/{device_id}/commands/{command_id}", response_model=CommandOut)
def command_status(
    device_id: str, command_id: int, caller: str = Depends(current_user)
) -> CommandOut:
    """앱이 '기기에 전달됐는지' 확인할 때 쓴다."""
    with db.session_scope() as conn:
        device = _get_device(conn, device_id)
        _require_self(caller, str(device["user_id"]))
        row = conn.execute(
            "SELECT * FROM device_commands WHERE command_id=? AND device_id=?",
            (command_id, device_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "명령을 찾을 수 없습니다.")
        return CommandOut(**_row_to_dict(row))


# ---------------------------------------------------------------- 사용자 페이지 조회
def _session_rows(conn: Any, user_id: str, limit: int) -> list[SessionOut]:
    rows = conn.execute(
        "SELECT * FROM sessions WHERE user_id=? ORDER BY session_id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [SessionOut(**_row_to_dict(r)) for r in rows]


@app.get("/api/users/{user_id}/sessions", response_model=list[SessionOut])
def user_sessions(
    user_id: str,
    limit: int = Query(default=30, ge=1, le=200),
    caller: str = Depends(current_user),
) -> list[SessionOut]:
    _require_self(caller, user_id)
    with db.session_scope() as conn:
        _get_user(conn, user_id)
        return _session_rows(conn, user_id, limit)


@app.get("/api/users/{user_id}/summary", response_model=UserSummary)
def user_summary(user_id: str, caller: str = Depends(current_user)) -> UserSummary:
    _require_self(caller, user_id)
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
                      MIN(CASE WHEN outcome='onset' THEN sol_min END) AS best_sol,
                      AVG(rating) AS avg_rating
                 FROM sessions WHERE user_id=?""",
            (user_id,),
        ).fetchone()
        # 끝났지만 아직 별점을 남기지 않은 가장 최근 세션 -> 홈 화면 평가 카드
        pending = conn.execute(
            """SELECT * FROM sessions
                WHERE user_id=? AND reviewed_at IS NULL AND ended_at IS NOT NULL
                  AND outcome IN ('onset','no_onset')
                ORDER BY session_id DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        stats = [
            TempStat(
                target_temp_c=_num(r["target_temp_c"]) or 0.0,
                avg_sol_min=_num(r["avg_sol"], 2) or 0.0,
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
            avg_sol_min=_num(agg["avg_sol"], 2),
            best_sol_min=_num(agg["best_sol"]),
            best_temp_c=best_temp,
            temp_stats=stats,
            recent_sessions=_session_rows(conn, user_id, 10),
            pending_review=SessionOut(**_row_to_dict(pending)) if pending else None,
            avg_rating=_num(agg["avg_rating"], 2),
        )


@app.get("/api/sessions/{session_id}")
def session_detail(
    session_id: int,
    samples: int = Query(default=600, ge=0, le=5000),
    caller: str = Depends(current_user),
) -> dict[str, Any]:
    with db.session_scope() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "세션을 찾을 수 없습니다.")
        _require_self(caller, str(row["user_id"]))
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


@app.post("/api/sessions/{session_id}/review", response_model=SessionOut)
def review_session(
    session_id: int, payload: SessionReview, caller: str = Depends(current_user)
) -> SessionOut:
    """아침에 남기는 수면 평가(별점 + 특이사항). 다시 보내면 덮어쓴다."""
    with db.session_scope() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "세션을 찾을 수 없습니다.")
        _require_self(caller, str(row["user_id"]))
        conn.execute(
            "UPDATE sessions SET rating=?, note_code=?, note_text=?, reviewed_at=? WHERE session_id=?",
            (payload.rating, payload.note_code, payload.note_text.strip(), db.now_iso(), session_id),
        )
        updated = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return SessionOut(**_row_to_dict(updated))


# ---------------------------------------------------------------- 브리지 업로드
@app.post("/api/ingest/announce", response_model=AnnounceResult, dependencies=[Depends(require_ingest_key)])
def ingest_announce(payload: DeviceAnnounce) -> AnnounceResult:
    """브리지가 기기 부팅(@ID,...)을 감지했을 때 호출.

    등록된 기기면 접속 시각만 갱신하고, 미등록이면 pending 목록에 올려 앱에서 고를 수 있게 한다.
    """
    now = db.now_iso()
    with db.session_scope() as conn:
        device = conn.execute(
            "SELECT * FROM devices WHERE device_id=?", (payload.device_id,)
        ).fetchone()
        if device is not None:
            conn.execute("UPDATE devices SET last_seen_at=? WHERE device_id=?", (now, payload.device_id))
            return AnnounceResult(
                device_id=payload.device_id, registered=True, user_id=device["user_id"],
                detail="등록된 기기",
            )
        conn.execute(
            "INSERT INTO pending_devices(device_id, first_seen_at, last_seen_at, firmware)"
            " VALUES(?,?,?,?)"
            " ON CONFLICT(device_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,"
            " firmware=excluded.firmware",
            (payload.device_id, now, now, payload.firmware),
        )
        return AnnounceResult(
            device_id=payload.device_id, registered=False, detail="앱에서 이 기기를 등록하세요.",
        )


@app.get("/api/ingest/commands", response_model=list[CommandOut],
         dependencies=[Depends(require_ingest_key)])
def take_commands(device_id: str = Query(...)) -> list[CommandOut]:
    """브리지가 폴링해서 가져간다. 가져간 명령은 sent 로 표시한다."""
    with db.session_scope() as conn:
        rows = conn.execute(
            "SELECT * FROM device_commands WHERE device_id=? AND status='pending'"
            " ORDER BY command_id LIMIT 5",
            (device_id,),
        ).fetchall()
        now = db.now_iso()
        out = []
        for row in rows:
            conn.execute(
                "UPDATE device_commands SET status='sent', sent_at=? WHERE command_id=?",
                (now, row["command_id"]),
            )
            data = _row_to_dict(row)
            data.update(status="sent", sent_at=now)
            out.append(CommandOut(**data))
        return out


@app.post("/api/ingest/commands/{command_id}/ack", response_model=CommandOut,
          dependencies=[Depends(require_ingest_key)])
def ack_command(command_id: int, payload: CommandAck) -> CommandOut:
    with db.session_scope() as conn:
        row = conn.execute(
            "SELECT * FROM device_commands WHERE command_id=?", (command_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "명령을 찾을 수 없습니다.")
        conn.execute(
            "UPDATE device_commands SET status=?, acked_at=?, detail=? WHERE command_id=?",
            (payload.status, db.now_iso(), payload.detail, command_id),
        )
        updated = conn.execute(
            "SELECT * FROM device_commands WHERE command_id=?", (command_id,)
        ).fetchone()
        return CommandOut(**_row_to_dict(updated))


@app.post("/api/ingest/heartbeat", response_model=DeviceOut,
          dependencies=[Depends(require_ingest_key)])
def heartbeat(payload: HeartbeatIn) -> DeviceOut:
    """브리지가 보는 기기 상태를 갱신한다.

    online  : 시리얼 포트가 열려 있고 최근에 로그가 들어왔다
    no_data : 포트는 열렸는데 로그가 끊겼다(기기 전원/배터리 확인)
    no_port : 포트 자체가 없다(케이블/기기 연결 확인)
    """
    with db.session_scope() as conn:
        _get_device(conn, payload.device_id)
        now = db.now_iso()
        conn.execute(
            "UPDATE devices SET link_state=?, link_seen_at=?, battery_pct=?,"
            " last_seen_at=CASE WHEN ?='online' THEN ? ELSE last_seen_at END"
            " WHERE device_id=?",
            (payload.link_state, now, payload.battery_pct, payload.link_state, now, payload.device_id),
        )
        row = conn.execute(
            "SELECT * FROM devices WHERE device_id=?", (payload.device_id,)
        ).fetchone()
        return DeviceOut(**_row_to_dict(row))


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
            source = START_SOURCES.get(int(_value(payload.values, 1) or 0), "app")
            repeat = _repeat_start(session)
            if repeat:
                # 같은 start 를 다시 받은 것뿐이므로 기록을 새로 만들지 않는다.
                session_id = int(session["session_id"])
                conn.execute(
                    "UPDATE sessions SET device_start_ms=?, target_temp_c=?, start_source=? WHERE session_id=?",
                    (payload.device_ms, _value(payload.values, 0), source, session_id),
                )
                detail = "같은 start 재수신 — 기존 기록 유지"
            else:
                if session is not None:                   # 이전 세션이 안 닫혔으면 중단 처리
                    conn.execute(
                        "UPDATE sessions SET ended_at=?, outcome=CASE outcome WHEN 'running' THEN 'aborted' ELSE outcome END"
                        " WHERE session_id=?",
                        (now, session["session_id"]),
                    )
                session_id = db.insert_returning_id(
                    conn,
                    "INSERT INTO sessions(user_id, device_id, started_at, device_start_ms, target_temp_c, start_source)"
                    " VALUES(?,?,?,?,?,?)",
                    (user_id, payload.device_id, now, payload.device_ms, _value(payload.values, 0), source),
                    "session_id",
                )
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
                        "UPDATE sessions SET sol_min=?, outcome=?, onset_at=?, failure_reason=?"
                        " WHERE session_id=?",
                        (
                            _value(payload.values, 0),
                            TERMINAL_FLAGS[flag],
                            now if flag == "SLEEP_ONSET" else None,
                            NO_ONSET_REASONS.get(int(_value(payload.values, 1) or 0), "unknown")
                            if flag == "NO_ONSET" else None,
                            session_id,
                        ),
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
                      (SELECT AVG(rating) FROM sessions s WHERE s.user_id=u.user_id) AS avg_rating,
                      (SELECT MAX(started_at) FROM sessions s WHERE s.user_id=u.user_id) AS last_session_at
                 FROM users u ORDER BY u.created_at DESC"""
        ).fetchall()
        return [
            AdminUserRow(
                user_id=r["user_id"], name=r["name"], created_at=r["created_at"],
                device_count=r["device_count"], session_count=r["session_count"],
                onset_count=r["onset_count"],
                avg_sol_min=_num(r["avg_sol"], 2),
                avg_rating=_num(r["avg_rating"], 2),
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
        "SELECT session_id, user_id, device_id, started_at, start_source, ended_at, target_temp_c,"
        " resting_bpm, threshold_bpm, sol_min, outcome, onset_at, failure_reason,"
        " rating, note_code, note_text FROM sessions"
    )
    params: tuple[Any, ...] = ()
    if user_id:
        query += " WHERE user_id=?"
        params = (user_id,)
    query += " ORDER BY session_id"

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["session_id", "user_id", "device_id", "started_at", "start_source", "ended_at",
         "target_temp_c", "resting_bpm", "threshold_bpm", "sol_min", "outcome",
         "onset_at", "failure_reason", "rating", "note_code", "note_text"]
    )
    with db.session_scope() as conn:
        for r in conn.execute(query, params).fetchall():
            writer.writerow([r[k] for k in r.keys()])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv; charset=utf-8")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# 관리자 대시보드(admin-web/)는 사용자 앱과 완전히 분리된 별도 사이트다.
# 여기에 얹어두면 배포가 하나로 끝나지만, 정적 파일이라 다른 곳에 따로 올려도 된다.
ADMIN_SITE_DIR = Path(__file__).resolve().parent.parent.parent / "admin-web"
ADMIN_SITE_AVAILABLE = ADMIN_SITE_DIR.is_dir()
if ADMIN_SITE_AVAILABLE:
    app.mount("/admin", StaticFiles(directory=ADMIN_SITE_DIR, html=True), name="admin")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    """브라우저로 서버 주소를 열었을 때 보여주는 상태 페이지.

    앱이 아니라 '서버가 살아있는지' 확인하는 용도. 앱 화면은 모바일에서 Expo 로 연다.
    """
    with db.session_scope() as conn:
        users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        devices = conn.execute("SELECT COUNT(*) AS n FROM devices").fetchone()["n"]
        sessions = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    admin_link = (
        ' · <a href="/admin/">관리자 대시보드</a>(연구 운영용, 토큰 필요)'
        if ADMIN_SITE_AVAILABLE else ""
    )
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
  <p><a href="/docs">API 문서 열기</a>{admin_link}</p>
</main></body></html>""")
