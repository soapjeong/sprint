#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""serial_csv_logger.py — ESP32 시리얼 로거 겸 서버 업로드 브리지.

기능
  1) 시리얼(USB)로 들어오는 로그를 CSV/이벤트 로그로 저장 (기존 동작)
  2) --server 를 주면 같은 데이터를 백엔드(FastAPI)로 업로드
     - "[진행상태] ..." 한 줄  -> /api/ingest/samples (배치 업로드)
     - "@FLAG,..." / "@RESULT,..." -> /api/ingest/events (즉시 업로드)
  3) --replay 로 저장해 둔 로그 파일을 재생 (하드웨어 없이 파이프라인 점검용)

예)
  python serial_csv_logger.py --port COM5 \
      --server http://192.168.0.10:8000 --api-key dev-ingest-key --device DORMX-001
"""

import argparse
import csv
import datetime
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------- 로그 파싱
# 펌웨어가 찍는 한글 라벨 -> 서버 필드명
STATUS_FIELDS = {
    "시간": "elapsed_s",
    "피부온도": "skin_c",
    "히터온도": "heater_c",
    "목표": "target_c",
    "히터파워": "duty_pct",
    "심박수": "bpm",
    "안정심박": "resting_bpm",
    "입면기준": "threshold_bpm",
    "센서": "sensor_state",
    "안전": "safety_state",
    "세션": "session_state",
    "연속수면(분)": "quiet_min",
    "판정": "verdict",
}
NUMERIC_FIELDS = {
    "elapsed_s", "skin_c", "heater_c", "target_c", "duty_pct",
    "bpm", "resting_bpm", "threshold_bpm", "quiet_min",
}
CSV_HEADERS = [
    "시간(초)", "피부온도(C)", "히터온도(C)", "목표온도(C)", "PWM(%)", "심박수(BPM)",
    "안정심박(BPM)", "입면기준(BPM)", "센서전원", "안전상태", "세션상태",
    "연속수면(분)", "수면판정",
]
UNITS = ("℃", "초", "%", "BPM")


def _strip_units(value):
    for unit in UNITS:
        value = value.replace(unit, "")
    return value.strip()


def parse_status_line(line):
    """"[진행상태] 시간:12초 | 피부온도:36.4℃ | ..." -> 업로드용 dict.

    형식이 맞지 않으면 None 을 돌려준다(펌웨어를 고쳐도 로거가 죽지 않게).
    """
    if "[진행상태]" not in line:
        return None
    parsed = {}
    for chunk in line.split("[진행상태]", 1)[1].split("|"):
        if ":" not in chunk:
            continue
        label, raw = chunk.split(":", 1)
        field = STATUS_FIELDS.get(label.strip())
        if field is None:
            continue
        value = _strip_units(raw)
        if field in NUMERIC_FIELDS:
            try:
                parsed[field] = float(value)
            except ValueError:
                parsed[field] = None
        else:
            parsed[field] = value
    if "elapsed_s" not in parsed or parsed["elapsed_s"] is None:
        return None

    sample = {
        "device_ms": int(parsed["elapsed_s"] * 1000),
        "asleep": parsed.get("verdict") == "수면중",
    }
    for field in NUMERIC_FIELDS - {"elapsed_s"}:
        sample[field] = parsed.get(field)
    if sample.get("quiet_min") is not None:
        sample["quiet_min"] = int(sample["quiet_min"])
    for field in ("sensor_state", "safety_state", "session_state"):
        sample[field] = parsed.get(field)
    return sample


def parse_device_id_line(line):
    """"@ID,DORMX-246F28AABBCC" -> 기기 ID.

    기기 ID 는 ESP32 칩의 MAC(efuse)에서 만들어지므로 사람이 지정하지 않는다.
    """
    line = line.strip()
    if not line.startswith("@ID,"):
        return None
    device_id = line.split(",", 1)[1].strip()
    return device_id or None


def parse_event_line(line):
    """"@FLAG,<id>,<flag>,<ms>,<v1>,<v2>" / "@RESULT,..." -> 업로드용 dict."""
    line = line.strip()
    if not line.startswith(("@FLAG,", "@RESULT,")):
        return None
    parts = [p.strip() for p in line.split(",")]

    def as_float(text):
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    if parts[0] == "@FLAG":
        if len(parts) < 4:
            return None
        values = [v for v in (as_float(p) for p in parts[4:]) if v is not None]
        return {
            "flag": parts[2],
            "device_ms": int(as_float(parts[3]) or 0),
            "values": values,
            "raw": line[:512],
        }
    # @RESULT,<person>,<temp>,<sol>,<converged>,<bestTemp>,<bestSol>,<nextTemp>
    values = [v for v in (as_float(p) for p in parts[2:]) if v is not None]
    return {"flag": "RESULT", "device_ms": 0, "values": values, "raw": line[:512]}


def status_row_for_csv(line):
    """기존 CSV 저장 형식(라벨 순서 그대로)."""
    row = []
    for chunk in line.split("[진행상태]", 1)[1].split("|"):
        if ":" in chunk:
            row.append(_strip_units(chunk.split(":", 1)[1]))
    return row


# ---------------------------------------------------------------- 서버 업로드
class ServerUploader:
    """샘플은 모아서, 이벤트는 즉시 서버로 올린다. 실패해도 로깅은 계속된다."""

    def __init__(self, base_url, api_key, device_id, batch=20, flush_interval=5.0, timeout=5.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.device_id = device_id
        self.batch = batch
        self.flush_interval = flush_interval
        self.timeout = timeout
        self._samples = []
        self._lock = threading.Lock()
        self._events = queue.Queue()
        self._stop = threading.Event()
        self._threads = []
        self.failures = 0

    # --- 내부 HTTP ---
    def _post(self, path, payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json", "X-API-Key": self.api_key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post_safe(self, path, payload, label):
        try:
            self._post(path, payload)
            return True
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            print(f"[업로드 실패] {label} HTTP {exc.code} {detail}")
        except Exception as exc:                      # 네트워크 단절 등
            print(f"[업로드 실패] {label} {exc}")
        self.failures += 1
        return False

    # --- 외부 API ---
    def start(self):
        t = threading.Thread(target=self._sample_loop, daemon=True)
        e = threading.Thread(target=self._event_loop, daemon=True)
        self._threads = [t, e]
        t.start()
        e.start()

    def add_sample(self, sample):
        if not self.device_id:            # 기기 ID 를 아직 모르면 보낼 곳이 없다
            return
        with self._lock:
            self._samples.append(sample)
            ready = len(self._samples) >= self.batch
        if ready:
            self.flush_samples()

    def set_device_id(self, device_id):
        """기기가 알려준 ID 로 갈아탄다(수동 지정한 값이 없을 때만)."""
        if self.device_id == device_id:
            return False
        self.flush_samples()          # 이전 기기 것으로 올라가지 않도록 먼저 비운다
        self.device_id = device_id
        return True

    def announce(self, device_id, firmware=""):
        self._post_safe(
            "/api/ingest/announce",
            {"device_id": device_id, "firmware": firmware},
            f"announce {device_id}",
        )

    def add_event(self, event):
        # 이벤트(세션 시작/종료 등)는 즉시 올라가므로, 그 전에 쌓인 샘플을 먼저 비워
        # "세션이 닫힌 뒤 도착한 샘플"이 생기지 않게 한다.
        self.flush_samples()
        self._events.put(event)

    def flush_samples(self):
        with self._lock:
            pending, self._samples = self._samples, []
        if not pending or not self.device_id:
            return
        ok = self._post_safe(
            "/api/ingest/samples",
            {"device_id": self.device_id, "samples": pending},
            f"samples x{len(pending)}",
        )
        if not ok:                                    # 다음 주기에 다시 시도
            with self._lock:
                self._samples = pending[-200:] + self._samples

    def _sample_loop(self):
        while not self._stop.wait(self.flush_interval):
            self.flush_samples()

    def _event_loop(self):
        while True:
            try:
                event = self._events.get(timeout=0.5)
            except queue.Empty:
                if self._stop.is_set():
                    return
                continue
            if not self.device_id:
                continue
            payload = dict(event)
            payload["device_id"] = self.device_id
            self._post_safe("/api/ingest/events", payload, f"event {event['flag']}")

    def close(self):
        self.flush_samples()
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)


# ---------------------------------------------------------------- 시리얼 로거
def pick_port_interactively():
    from serial.tools import list_ports

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
    def __init__(self, port, baud, outdir, uploader=None, replay=None, replay_delay=0.0,
                 device_id_fixed=False):
        self.port = port
        self.baud = baud
        self.outdir = outdir
        self.uploader = uploader
        self.replay = replay
        self.replay_delay = replay_delay
        self.device_id_fixed = device_id_fixed   # --device 로 직접 지정했으면 기기 통보를 무시
        os.makedirs(self.outdir, exist_ok=True)

        tag = timestamp_tag()
        self.csv_path = os.path.join(self.outdir, f"sensor_{tag}.csv")
        self.event_path = os.path.join(self.outdir, f"events_{tag}.log")
        # 엑셀 한글 깨짐 방지 utf-8-sig
        self.csv_file = open(self.csv_path, "w", newline="", encoding="utf-8-sig")
        self.csv_writer = csv.writer(self.csv_file)
        self.event_file = open(self.event_path, "w", encoding="utf-8")

        self._header_written = False
        self._stop = threading.Event()
        self.ser = None

        print("[로깅 시작]")
        print(f"  센서 CSV : {self.csv_path}")
        print(f"  이벤트 로그: {self.event_path}")
        if replay:
            print(f"  재생 파일: {replay}")
        else:
            print(f"  포트={self.port}  baud={self.baud}")
        if uploader:
            print(f"  서버 업로드: {uploader.base_url}  "
                  f"기기={uploader.device_id or '기기가 알려줄 때까지 대기(@ID)'}")
        print("  종료하려면 Ctrl+C\n")

    # --- 시리얼 ---
    def connect(self):
        import serial

        while not self._stop.is_set():
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=1)
                time.sleep(2.0)
                self.ser.reset_input_buffer()
                print(f"[연결됨] {self.port} @ {self.baud}bps")
                return
            except serial.SerialException as exc:
                print(f"[연결 실패] {exc}  -> 2초 후 재시도")
                time.sleep(2.0)

    # --- 한 줄 처리 ---
    def handle_line(self, line):
        line = line.strip()
        if not line:
            return

        if "[진행상태]" in line:
            if not self._header_written:
                self.csv_writer.writerow(CSV_HEADERS)
                self._header_written = True
                self.csv_file.flush()
            try:
                row = status_row_for_csv(line)
                if row:
                    self.csv_writer.writerow(row)
                    self.csv_file.flush()     # 엑셀에서 실시간으로 보이도록 강제 배출
                if self.uploader:
                    sample = parse_status_line(line)
                    if sample:
                        self.uploader.add_sample(sample)
                print(line)
            except Exception:
                print(f"[데이터 파싱 에러] {line}")
            return

        # 기기가 부팅하며 알려주는 고유 ID (칩 MAC 기반)
        device_id = parse_device_id_line(line)
        if device_id and self.uploader and not self.device_id_fixed:
            if self.uploader.set_device_id(device_id):
                print(f"[기기 인식] {device_id} — 이 ID 로 업로드합니다.")
            self.uploader.announce(device_id)

        # 이벤트 및 안내 메시지: 상태 플래그(@FLAG,...) / 세션 결과(@RESULT,...) / 안내(#, =)
        if line.startswith(("#", "@", "=")) or "ESP32" in line:
            tagged = f"[{now_iso()}] {line}"
            print(tagged)
            self.event_file.write(tagged + "\n")
            self.event_file.flush()
            if self.uploader:
                event = parse_event_line(line)
                if event:
                    self.uploader.add_event(event)
            return

        tagged = f"[{now_iso()}] (unrecognized) {line}"
        print(tagged)
        self.event_file.write(tagged + "\n")
        self.event_file.flush()

    # --- 루프 ---
    def reader_loop(self):
        import serial

        while not self._stop.is_set():
            try:
                if self.ser is None or not self.ser.is_open:
                    self.connect()
                raw = self.ser.readline()
                if not raw:
                    continue
                self.handle_line(raw.decode("utf-8", errors="replace"))
            except serial.SerialException as exc:
                print(f"[시리얼 오류] {exc}  -> 재연결 시도")
                try:
                    if self.ser:
                        self.ser.close()
                except Exception:
                    pass
                self.ser = None
                time.sleep(1.0)

    def replay_loop(self):
        with open(self.replay, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if self._stop.is_set():
                    break
                self.handle_line(line)
                if self.replay_delay:
                    time.sleep(self.replay_delay)
        print("[재생 완료]")

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
                except Exception:
                    print("[전송 실패] 시리얼 연결을 확인하세요.")

    def run(self):
        if self.replay:
            self.replay_loop()
            self.close()
            return
        self.connect()
        threading.Thread(target=self.reader_loop, daemon=True).start()
        try:
            self.writer_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def close(self):
        self._stop.set()
        if self.uploader:
            self.uploader.close()
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.csv_file.close()
        self.event_file.close()
        print(f"\n[종료] 저장된 파일:\n  {self.csv_path}\n  {self.event_path}")


def main():
    parser = argparse.ArgumentParser(description="ESP32 수면 온도 최적화기 시리얼 로거 / 업로드 브리지")
    parser.add_argument("--port", default=None, help="시리얼 포트 (예: COM5, /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=115200, help="baud rate (기본 115200)")
    parser.add_argument("--outdir", default="./logs", help="로그 저장 폴더 (기본 ./logs)")
    parser.add_argument("--server", default=None, help="업로드할 서버 주소 (예: http://192.168.0.10:8000)")
    parser.add_argument("--api-key", default=os.environ.get("INGEST_API_KEY", ""), help="서버 업로드 API 키")
    parser.add_argument("--device", default=None,
                        help="기기 ID 직접 지정(보통 불필요 — 기기가 @ID 로 알려준다)")
    parser.add_argument("--replay", default=None, help="시리얼 대신 재생할 로그 파일")
    parser.add_argument("--replay-delay", type=float, default=0.0, help="재생 시 줄 간 지연(초)")
    args = parser.parse_args()

    uploader = None
    if args.server:
        # 기기 ID 는 ESP32 가 부팅하며 "@ID,..." 로 알려준다. --device 는 수동 우선 지정용.
        uploader = ServerUploader(args.server, args.api_key, args.device or "")
        uploader.start()
        if args.device:
            uploader.announce(args.device)

    port = None if args.replay else (args.port or pick_port_interactively())
    logger = SerialCsvLogger(
        port, args.baud, args.outdir,
        uploader=uploader, replay=args.replay, replay_delay=args.replay_delay,
        device_id_fixed=bool(args.device),
    )
    logger.run()


if __name__ == "__main__":
    main()
