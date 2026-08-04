#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESP32 하드웨어 없이 백엔드/프론트엔드를 테스트하기 위한 가짜 DeviceConnection.

connection.py의 DeviceConnection 인터페이스만 구현하므로, main.py 입장에서는
SerialDeviceConnection과 완전히 동일하게 다뤄진다. 실제 시리얼 대신, REST로 들어온
값을 inject_line()을 통해 주입하면 그 뒤(parsing -> CSV/이벤트 로깅 -> WebSocket 브로드캐스트)는
실제 장치가 보낸 것과 동일한 경로를 그대로 탄다.
"""

from typing import Callable, Optional

from .connection import DeviceConnection


class MockDeviceConnection(DeviceConnection):
    def __init__(self):
        self._on_line: Optional[Callable[[str], None]] = None

    def start(self, on_line: Callable[[str], None]) -> None:
        self._on_line = on_line

    def inject_line(self, line: str) -> None:
        if self._on_line:
            self._on_line(line)

    def write_line(self, text: str) -> None:
        # 실제 하드웨어가 없으므로 명령은 콘솔에만 기록한다.
        print(f"[MOCK] 명령 수신(전송 안 함): {text}")

    def is_connected(self) -> bool:
        return True

    def stop(self) -> None:
        self._on_line = None
