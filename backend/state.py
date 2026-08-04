#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""서버 프로세스 안에서 공유하는 상태: 최신 상태값, 최신 결과, 연결된 WebSocket들."""

import asyncio
from typing import Optional

from fastapi import WebSocket

from .connection import DeviceConnection
from .log_writer import SessionLogWriter


class AppState:
    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.websockets: set[WebSocket] = set()
        self.latest_status: Optional[dict] = None
        self.latest_result: Optional[dict] = None
        self.results: list[dict] = []
        # 펌웨어의 "시간(초)" 필드는 세션 기준이 아니라 ESP32 부팅 이후 전체 경과시간(millis())이라
        # 세션이 실제로 시작된 시각을 백엔드가 따로 기억해서 세션 상대 경과시간을 계산한다.
        self.session_started_at: Optional[float] = None
        self.last_session_state: Optional[str] = None
        self.log_writer: Optional[SessionLogWriter] = None
        self.device: Optional[DeviceConnection] = None

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in list(self.websockets):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.websockets.discard(ws)

    def schedule_broadcast(self, message: dict) -> None:
        """장치 리더 스레드(별도 OS 스레드)에서 안전하게 호출하기 위한 진입점."""
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.broadcast(message)))


state = AppState()
