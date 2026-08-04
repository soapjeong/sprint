#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 백엔드 — 시리얼 연결을 단독 소유하는 서버.

기존 구조의 문제(로거가 시리얼 포트를 독점 -> 컨트롤러를 따로 만들 수 없음)를 해결하기 위해,
serial_csv_logger.py가 하던 시리얼 읽기/쓰기 + CSV/이벤트 로깅을 이 서버 하나로 흡수했다.
그 위에 REST(명령 전송/상태 조회)와 WebSocket(실시간 push)을 얹어 폰 컨트롤 페이지와
Streamlit 대시보드가 각자 이 서버 하나만 보고 동작하게 한다.

실행: python run.py  (자세한 옵션은 README 참고)
"""

import asyncio
import os
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .connection import SerialDeviceConnection
from .log_writer import SessionLogWriter
from .models import CommandRequest
from .parsing import START_REJECTED_MARKER, now_iso, parse_progress_line, parse_result_event
from .state import state

# ---------------------------------------------------------------------------
# 펌웨어(.ino)와 동일한 안전 상수. UI에서도 한 번 더 제한을 걸기 위해 여기서도 노출한다.
# ---------------------------------------------------------------------------
SEARCH_MIN = 37.5
SEARCH_MAX = 40.5
SESSION_MAX_SEC = 60 * 60

ALLOWED_EXACT_COMMANDS = {"start", "abort", "report", "reset_profile", "r"}
ALLOWED_PREFIX_COMMANDS = ("id ", "set ")

PHONE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "phone")


def get_lan_ip() -> str:
    """실제로 패킷을 보내지 않고(오프라인 LAN에서도 동작) 이 머신의 LAN IP를 알아낸다."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def handle_device_line(line: str) -> None:
    """장치 리더 스레드에서 호출됨 (asyncio 루프 스레드가 아님) -> state.schedule_broadcast로 넘긴다."""
    line = line.strip()
    if not line:
        return

    if "[진행상태]" in line:
        csv_row, status = parse_progress_line(line)
        state.latest_status = status
        if state.log_writer:
            state.log_writer.write_progress_row(csv_row)
        state.schedule_broadcast({"type": "status", "data": status})
        return

    if line.startswith(("#", "@RESULT", "=")) or "ESP32" in line:
        tagged = f"[{now_iso()}] {line}"
        if state.log_writer:
            state.log_writer.write_event_line(tagged)

        if line.startswith("@RESULT"):
            result = parse_result_event(line)
            if result:
                state.latest_result = result
                state.schedule_broadcast({"type": "result", "data": result})
                return

        state.schedule_broadcast({
            "type": "error" if START_REJECTED_MARKER in line else "event",
            "message": line,
            "ts": now_iso(),
        })
        return

    tagged = f"[{now_iso()}] (unrecognized) {line}"
    if state.log_writer:
        state.log_writer.write_event_line(tagged)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.loop = asyncio.get_event_loop()

    log_dir = os.environ.get("SLEEP_LOG_DIR", "./logs")
    state.log_writer = SessionLogWriter(log_dir)

    serial_port = os.environ.get("SLEEP_SERIAL_PORT") or None
    baud = int(os.environ.get("SLEEP_SERIAL_BAUD", "115200"))
    state.device = SerialDeviceConnection(port=serial_port, baud=baud)
    state.device.start(handle_device_line)

    http_port = os.environ.get("SLEEP_HTTP_PORT", "8000")
    print(f"[백엔드] 센서 CSV : {state.log_writer.csv_path}")
    print(f"[백엔드] 이벤트 로그: {state.log_writer.event_path}")
    print(f"[백엔드] 폰 컨트롤 페이지: http://{get_lan_ip()}:{http_port}/")

    yield

    if state.device:
        state.device.stop()
    if state.log_writer:
        state.log_writer.close()


app = FastAPI(title="Sleep Onset Optimizer Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def get_status():
    device = state.device
    return {
        "connected": device.is_connected() if device else False,
        "port": device.port if device else None,
        "status": state.latest_status,
        "last_result": state.latest_result,
        "csv_path": state.log_writer.csv_path if state.log_writer else None,
        "event_path": state.log_writer.event_path if state.log_writer else None,
        "limits": {
            "search_min_c": SEARCH_MIN,
            "search_max_c": SEARCH_MAX,
            "session_max_sec": SESSION_MAX_SEC,
        },
    }


@app.get("/api/network")
async def get_network():
    return {"lan_ip": get_lan_ip(), "http_port": int(os.environ.get("SLEEP_HTTP_PORT", "8000"))}


@app.post("/api/command")
async def send_command(req: CommandRequest):
    text = req.cmd.strip()
    if not text:
        raise HTTPException(400, detail="빈 명령입니다.")

    is_known = text in ALLOWED_EXACT_COMMANDS or text.startswith(ALLOWED_PREFIX_COMMANDS)
    if not is_known:
        raise HTTPException(400, detail=f"알 수 없는 명령: {text}")

    # start를 실제로 시리얼에 쓰기 전에, 마지막으로 파싱된 안전상태로 FAULT 여부를 먼저 확인한다.
    # (펌웨어도 동일한 이유로 FAULT 중 start를 거부하지만, 여기서 먼저 걸러 왕복 없이 즉시 에러를 준다.)
    if text == "start":
        safety = state.latest_status.get("safety_state") if state.latest_status else None
        if safety and safety != "NORMAL":
            raise HTTPException(
                409,
                detail=f"START 거부: FAULT 상태({safety}). 먼저 'r' 명령으로 해제하세요.",
            )

    if text.startswith("set "):
        try:
            target = float(text[4:].strip())
        except ValueError:
            raise HTTPException(400, detail="set 명령의 온도 값이 올바르지 않습니다.")
        if not (SEARCH_MIN <= target <= SEARCH_MAX):
            raise HTTPException(
                400,
                detail=f"온도는 {SEARCH_MIN}~{SEARCH_MAX}℃ 범위여야 합니다.",
            )

    device = state.device
    if not device or not device.is_connected():
        raise HTTPException(503, detail="ESP32 시리얼이 연결되어 있지 않습니다.")

    try:
        device.write_line(text)
    except Exception as e:
        raise HTTPException(503, detail=str(e))

    return {"status": "sent", "cmd": text}


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    state.websockets.add(websocket)
    try:
        if state.latest_status:
            await websocket.send_json({"type": "status", "data": state.latest_status})
        if state.latest_result:
            await websocket.send_json({"type": "result", "data": state.latest_result})
        while True:
            # 클라이언트는 아무것도 보내지 않지만, 연결 종료를 감지하기 위해 계속 대기한다.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.websockets.discard(websocket)


# API/WS 라우트를 먼저 등록한 뒤 마지막에 정적 파일을 "/"에 마운트해야
# /api/*, /ws/live가 정적 파일 라우트보다 먼저 매칭된다.
app.mount("/", StaticFiles(directory=PHONE_DIR, html=True), name="phone")
