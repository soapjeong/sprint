#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serial_csv_logger.py (한글 라벨 대응 및 실시간 엑셀 저장 패치 버전)
"""

import argparse
import csv
import datetime
import os
import sys
import threading
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial이 설치되어 있지 않습니다. 먼저 다음 명령으로 설치하세요:")
    print("    pip install pyserial")
    sys.exit(1)

def pick_port_interactively():
    ports = list(list_ports.comports())
    if not ports:
        print("연결된 시리얼 장치를 찾지 못했습니다. --port 옵션으로 직접 지정하세요.")
        sys.exit(1)
    if len(ports) == 1:
        print(f"시리얼 포트 자동 선택: {ports[0].device} ({ports[0].description})")
        return ports[0].device
    print("연결된 시리얼 포트가 여러 개 있습니다:")
    for i, p in enumerate(ports):
        print(f"  [{i}] {p.device}  -  {p.description}")
    idx = input("사용할 포트 번호를 입력하세요: ").strip()
    try:
        return ports[int(idx)].device
    except (ValueError, IndexError):
        print("잘못된 입력입니다.")
        sys.exit(1)

def timestamp_tag():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def now_iso():
    return datetime.datetime.now().isoformat(timespec="milliseconds")

class SerialCsvLogger:
    def __init__(self, port, baud, outdir):
        self.port = port
        self.baud = baud
        self.outdir = outdir
        os.makedirs(self.outdir, exist_ok=True)

        tag = timestamp_tag()
        self.csv_path = os.path.join(self.outdir, f"sensor_{tag}.csv")
        self.event_path = os.path.join(self.outdir, f"events_{tag}.log")

        self.csv_file = open(self.csv_path, "w", newline="", encoding="utf-8-sig") # 엑셀 한글 깨짐 방지 utf-8-sig
        self.csv_writer = csv.writer(self.csv_file)
        self.event_file = open(self.event_path, "w", encoding="utf-8")

        self._header_written = False
        self._stop = threading.Event()
        self.ser = None

        print(f"[로깅 시작]")
        print(f"  센서 CSV : {self.csv_path}")
        print(f"  이벤트 로그: {self.event_path}")
        print(f"  포트={self.port}  baud={self.baud}")
        print("  종료하려면 Ctrl+C\n")

    def connect(self):
        while not self._stop.is_set():
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=1)
                time.sleep(2.0)
                self.ser.reset_input_buffer()
                print(f"[연결됨] {self.port} @ {self.baud}bps")
                return
            except serial.SerialException as e:
                print(f"[연결 실패] {e}  -> 2초 후 재시도")
                time.sleep(2.0)

    def handle_line(self, line):
        line = line.strip()
        if not line:
            return

        # ★ 아두이노가 보내는 "[진행상태]" 데이터를 잡아서 엑셀용으로 정리하는 부분 ★
        if "[진행상태]" in line:
            if not self._header_written:
                # 파이썬이 알아서 CSV 첫 줄(헤더)을 만들어줍니다.
                headers = ["시간(초)", "피부온도(C)", "히터온도(C)", "목표온도(C)", "PWM(%)", "심박수(BPM)",
                           "안정심박(BPM)", "입면기준(BPM)", "센서전원", "안전상태", "세션상태",
                           "연속수면(분)", "수면판정"]
                self.csv_writer.writerow(headers)
                self._header_written = True
                self.csv_file.flush()

            try:
                # 불필요한 글자를 잘라내고 순수 데이터만 추출합니다.
                parts = line.replace("[진행상태]", "").split("|")
                row = []
                for p in parts:
                    if ":" in p:
                        val = p.split(":")[1].strip()
                        # 단위(글자) 제거하여 엑셀에서 바로 그래프를 그릴 수 있게 숫자만 남김
                        val = val.replace("℃", "").replace("초", "").replace("%", "").replace("BPM", "")
                        row.append(val)
                
                # CSV에 저장하고 ★강제 배출(flush)★하여 엑셀에서 실시간으로 보이게 함
                if row:
                    self.csv_writer.writerow(row)
                    self.csv_file.flush() 
                    
                print(line) # 콘솔(터미널)에는 원래대로 한글 출력
            except Exception as e:
                print(f"[데이터 파싱 에러] {line}")
            return

        # 이벤트 및 안내 메시지: 상태 플래그(@FLAG,...) / 세션 결과(@RESULT,...) / 안내(#, =)
        if line.startswith(("#", "@", "=")) or "ESP32" in line:
            tagged = f"[{now_iso()}] {line}"
            print(tagged)
            self.event_file.write(tagged + "\n")
            self.event_file.flush()
            return

        # 그 외 알 수 없는 형식
        tagged = f"[{now_iso()}] (unrecognized) {line}"
        print(tagged)
        self.event_file.write(tagged + "\n")
        self.event_file.flush()

    def reader_loop(self):
        while not self._stop.is_set():
            try:
                if self.ser is None or not self.ser.is_open:
                    self.connect()
                raw = self.ser.readline()
                if not raw:
                    continue
                try:
                    line = raw.decode("utf-8", errors="replace")
                except Exception:
                    continue
                self.handle_line(line)
            except serial.SerialException as e:
                print(f"[시리얼 오류] {e}  -> 재연결 시도")
                try:
                    if self.ser:
                        self.ser.close()
                except Exception:
                    pass
                self.ser = None
                time.sleep(1.0)

    def writer_loop(self):
        while not self._stop.is_set():
            try:
                cmd = input()
            except EOFError:
                break
            if self._stop.is_set():
                break
            if self.ser and self.ser.is_open:
                try:
                    self.ser.write((cmd + "\n").encode("utf-8"))
                except serial.SerialException:
                    print("[전송 실패] 시리얼 연결을 확인하세요.")

    def run(self):
        self.connect()
        reader_thread = threading.Thread(target=self.reader_loop, daemon=True)
        reader_thread.start()
        try:
            self.writer_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def close(self):
        self._stop.set()
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.csv_file.close()
        self.event_file.close()
        print(f"\n[종료] 저장된 파일:\n  {self.csv_path}\n  {self.event_path}")

def main():
    parser = argparse.ArgumentParser(description="ESP32 수면 온도 최적화기 시리얼 로거")
    parser.add_argument("--port", default=None, help="시리얼 포트 (예: COM5, /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=115200, help="baud rate (기본 115200)")
    parser.add_argument("--outdir", default="./logs", help="로그 저장 폴더 (기본 ./logs)")
    args = parser.parse_args()

    port = args.port or pick_port_interactively()
    logger = SerialCsvLogger(port, args.baud, args.outdir)
    logger.run()

if __name__ == "__main__":
    main()