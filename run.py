#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
백엔드 서버 실행 스크립트.

    python run.py                          # 시리얼 포트 자동 탐색, 0.0.0.0:8000
    python run.py --serial-port /dev/ttyUSB0
    python run.py --serial-port COM5 --port 8080

--host를 0.0.0.0(기본값)으로 유지해야 같은 Wi-Fi의 폰에서 PC의 LAN IP로 접속할 수 있다.
"""

import argparse
import os


def main():
    parser = argparse.ArgumentParser(description="ESP32 수면 온도 최적화기 백엔드 서버")
    parser.add_argument("--serial-port", default=None, help="시리얼 포트 (예: COM5, /dev/ttyUSB0). 생략 시 자동 탐색")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--logdir", default="./logs", help="CSV/이벤트 로그 저장 폴더")
    parser.add_argument("--host", default="0.0.0.0", help="폰에서 접속하려면 0.0.0.0 유지")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.serial_port:
        os.environ["SLEEP_SERIAL_PORT"] = args.serial_port
    os.environ["SLEEP_SERIAL_BAUD"] = str(args.baud)
    os.environ["SLEEP_LOG_DIR"] = args.logdir
    os.environ["SLEEP_HTTP_PORT"] = str(args.port)

    import uvicorn

    uvicorn.run("backend.main:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
