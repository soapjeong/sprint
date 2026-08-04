#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESP32와의 통신 어댑터를 인터페이스로 분리한 모듈.

지금은 USB 시리얼(SerialDeviceConnection)만 구현하지만, DeviceConnection 인터페이스만
지키면 나머지 백엔드 코드(main.py)는 손대지 않고 나중에 WiFiDeviceConnection이나
BLEDeviceConnection으로 교체할 수 있다.

SerialDeviceConnection의 재연결 로직은 기존 serial_csv_logger.py의 connect()/reader_loop()를
그대로 이식했다.
"""

import abc
import threading
import time
from typing import Callable, Optional


class DeviceConnection(abc.ABC):
    """ESP32(또는 그 후속 통신 방식)와 한 줄 단위 텍스트를 주고받기 위한 인터페이스."""

    @abc.abstractmethod
    def start(self, on_line: Callable[[str], None]) -> None:
        """백그라운드로 연결을 맺고, 매 수신 줄마다 on_line(line)을 호출한다. 즉시 반환된다."""

    @abc.abstractmethod
    def write_line(self, text: str) -> None:
        """개행 없이 한 줄을 보낸다 (개행은 구현체가 붙인다). 연결 안 됐으면 예외를 던진다."""

    @abc.abstractmethod
    def is_connected(self) -> bool:
        ...

    @abc.abstractmethod
    def stop(self) -> None:
        ...


class SerialDeviceConnection(DeviceConnection):
    """USB 시리얼로 ESP32에 연결. baud=115200 고정 프로토콜."""

    def __init__(self, port: Optional[str] = None, baud: int = 115200):
        import serial  # 이 어댑터 안에서만 pyserial에 의존한다
        from serial.tools import list_ports

        self._serial_module = serial
        self._list_ports = list_ports
        self._fixed_port = port
        self.port = port
        self.baud = baud
        self.ser = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()

    def _resolve_port(self) -> Optional[str]:
        if self._fixed_port:
            return self._fixed_port
        ports = list(self._list_ports.comports())
        return ports[0].device if ports else None

    def _connect(self) -> None:
        serial = self._serial_module
        while not self._stop.is_set():
            port = self._resolve_port()
            if not port:
                print("[연결 실패] 연결된 시리얼 장치를 찾지 못함 -> 2초 후 재탐색")
                time.sleep(2.0)
                continue
            self.port = port
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=1)
                time.sleep(2.0)
                self.ser.reset_input_buffer()
                print(f"[연결됨] {self.port} @ {self.baud}bps")
                return
            except serial.SerialException as e:
                print(f"[연결 실패] {e}  -> 2초 후 재시도")
                time.sleep(2.0)

    def start(self, on_line: Callable[[str], None]) -> None:
        thread = threading.Thread(target=self._run, args=(on_line,), daemon=True)
        thread.start()

    def _run(self, on_line: Callable[[str], None]) -> None:
        self._connect()
        self._reader_loop(on_line)

    def _reader_loop(self, on_line: Callable[[str], None]) -> None:
        serial = self._serial_module
        while not self._stop.is_set():
            try:
                if self.ser is None or not self.ser.is_open:
                    self._connect()
                raw = self.ser.readline()
                if not raw:
                    continue
                try:
                    line = raw.decode("utf-8", errors="replace")
                except Exception:
                    continue
                on_line(line)
            except serial.SerialException as e:
                print(f"[시리얼 오류] {e}  -> 재연결 시도")
                try:
                    if self.ser:
                        self.ser.close()
                except Exception:
                    pass
                self.ser = None
                time.sleep(1.0)

    def write_line(self, text: str) -> None:
        with self._write_lock:
            if not (self.ser and self.ser.is_open):
                raise RuntimeError("시리얼이 연결되어 있지 않습니다.")
            self.ser.write((text + "\n").encode("utf-8"))

    def is_connected(self) -> bool:
        return bool(self.ser and self.ser.is_open)

    def stop(self) -> None:
        self._stop.set()
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
