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
# 무료 호스팅은 유휴 상태에서 잠들었다가 첫 요청에 1분 가까이 걸리기도 한다.
RETRY_DELAYS = (2, 5, 15, 30)
COMMAND_POLL_SEC = 3.0      # 앱 버튼을 얼마나 빨리 기기에 전달할지
HEARTBEAT_SEC = 15.0        # 기기 연결 상태 보고 주기
SILENT_LIMIT_SEC = 20.0     # 포트는 열렸는데 이 시간 동안 로그가 없으면 "응답 없음"
class ServerUploader:
    """서버 업로드 담당.

    샘플과 이벤트를 **하나의 큐에 순서대로** 넣고 한 스레드가 차례로 보낸다.
    (세션 시작 이벤트보다 샘플이 먼저 도착하면 서버가 버리기 때문에 순서가 중요하다.)
    실패해도 로깅은 계속되며, 잠들어 있는 서버는 재시도로 깨운다.
    """

    def __init__(self, base_url, api_key, device_id, batch=20, flush_interval=5.0, timeout=15.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.device_id = device_id
        self.batch = batch
        self.flush_interval = flush_interval
        self.timeout = timeout
        self._samples = []
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._threads = []
        self.failures = 0

    # --- 내부 HTTP ---
    def _get(self, path):
        req = urllib.request.Request(
            self.base_url + path, headers={"X-API-Key": self.api_key}, method="GET"
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

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

    def _post_safe(self, path, payload, label, retries=0):
        delays = RETRY_DELAYS[:retries]
        for attempt in range(retries + 1):
            try:
                self._post(path, payload)
                if attempt:
                    print(f"[업로드 성공] {label} (재시도 {attempt}회)")
                return True
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:200]
                print(f"[업로드 실패] {label} HTTP {exc.code} {detail}")
                if exc.code < 500:            # 400 대는 다시 보내도 같은 결과다
                    break
            except Exception as exc:          # 네트워크 단절, 서버 기동 대기 등
                print(f"[업로드 실패] {label} {exc}")
            if attempt < len(delays):
                wait = delays[attempt]
                print(f"  → {wait}초 후 재시도합니다({attempt + 1}/{retries}).")
                if self._stop.wait(wait):
                    break
        self.failures += 1
        return False

    # --- 외부 API ---
    def start(self):
        worker = threading.Thread(target=self._worker, daemon=True)
        timer = threading.Thread(target=self._flush_loop, daemon=True)
        self._threads = [worker, timer]
        worker.start()
        timer.start()

    def set_device_id(self, device_id):
        """기기가 알려준 ID 로 갈아탄다(수동 지정한 값이 없을 때만)."""
        if self.device_id == device_id:
            return False
        self.flush_samples()          # 이전 기기 것으로 올라가지 않도록 먼저 비운다
        self.device_id = device_id
        return True

    def announce(self, device_id, firmware=""):
        # 잠들어 있는 무료 호스팅을 깨우는 첫 요청이라 넉넉히 기다린다
        self._queue.put(("announce", {"device_id": device_id, "firmware": firmware}))

    def add_sample(self, sample):
        if not self.device_id:            # 기기 ID 를 아직 모르면 보낼 곳이 없다
            return
        with self._lock:
            self._samples.append(sample)
            ready = len(self._samples) >= self.batch
        if ready:
            self.flush_samples()

    def add_event(self, event):
        # 이벤트보다 앞서 측정된 샘플이 뒤늦게 도착하지 않도록 먼저 큐에 넣는다
        self.flush_samples()
        self._queue.put(("event", dict(event)))

    def flush_samples(self):
        with self._lock:
            pending, self._samples = self._samples, []
        if pending and self.device_id:
            self._queue.put(("samples", pending))

    def take_commands(self):
        """앱이 눌러 둔 명령을 가져온다(없으면 빈 목록)."""
        if not self.device_id:
            return []
        try:
            return self._get(f"/api/ingest/commands?device_id={self.device_id}")
        except Exception:
            return []                      # 서버가 잠깐 죽어도 로깅은 계속된다

    def ack_command(self, command_id, ok, detail=""):
        self._queue.put(("ack", {"command_id": command_id,
                                 "status": "done" if ok else "failed", "detail": detail}))

    def heartbeat(self, link_state):
        if self.device_id:
            self._queue.put(("heartbeat", {"device_id": self.device_id, "link_state": link_state}))

    # --- 전송 스레드 ---
    def _worker(self):
        while True:
            try:
                kind, payload = self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._stop.is_set():
                    return
                continue
            if not self.device_id:
                continue
            if kind == "samples":
                self._post_safe(
                    "/api/ingest/samples",
                    {"device_id": self.device_id, "samples": payload},
                    f"samples x{len(payload)}",
                    retries=1,
                )
            elif kind == "event":
                # 이벤트를 놓치면 그 세션 데이터 전체가 버려지므로 끈질기게 재시도한다
                body = dict(payload)
                body["device_id"] = self.device_id
                self._post_safe(
                    "/api/ingest/events", body, f"event {payload['flag']}", retries=len(RETRY_DELAYS)
                )
            elif kind == "announce":
                self._post_safe(
                    "/api/ingest/announce",
                    payload,
                    f"announce {payload['device_id']}",
                    retries=len(RETRY_DELAYS),
                )
            elif kind == "ack":
                body = {"status": payload["status"], "detail": payload["detail"]}
                self._post_safe(
                    f"/api/ingest/commands/{payload['command_id']}/ack", body, "command ack", retries=1
                )
            elif kind == "heartbeat":
                # 상태 보고는 실패해도 다음 주기에 다시 보내므로 재시도하지 않는다
                try:
                    self._post("/api/ingest/heartbeat", payload)
                except Exception:
                    pass

    def _flush_loop(self):
        while not self._stop.wait(self.flush_interval):
            self.flush_samples()

    def close(self):
        self.flush_samples()
        # 큐에 남은 것을 모두 보낼 시간을 준다
        deadline = time.time() + 30
        while not self._queue.empty() and time.time() < deadline:
            time.sleep(0.1)
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5.0)


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
        self.last_line_at = 0.0                  # 마지막으로 기기 로그를 받은 시각
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
        self.last_line_at = time.time()

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

    def send_serial(self, text):
        """기기에 시리얼 명령을 넣는다. 성공 여부를 돌려준다."""
        if not (self.ser and self.ser.is_open):
            return False
        try:
            self.ser.write((text + "\n").encode("utf-8"))
            return True
        except Exception as exc:
            print(f"[명령 전송 실패] {text} {exc}")
            return False

    def link_state(self):
        """앱에 보여줄 연결 상태 — 케이블 문제와 기기 전원 문제를 구분한다."""
        if self.replay:
            return "online"
        if not (self.ser and self.ser.is_open):
            return "no_port"
        if self.last_line_at and (time.time() - self.last_line_at) <= SILENT_LIMIT_SEC:
            return "online"
        return "no_data"

    def command_loop(self):
        """앱에서 누른 시작/중지 버튼을 받아 기기에 넣고, 상태를 주기적으로 보고한다."""
        last_beat = 0.0
        while not self._stop.wait(COMMAND_POLL_SEC):
            if not self.uploader:
                continue
            for command in self.uploader.take_commands():
                name = command.get("command", "")
                print(f"[앱 명령] {name}")
                ok = self.send_serial(name)
                self.uploader.ack_command(
                    command.get("command_id"), ok,
                    "시리얼 전송" if ok else "기기가 연결되어 있지 않음",
                )
            now = time.time()
            if now - last_beat >= HEARTBEAT_SEC:
                last_beat = now
                self.uploader.heartbeat(self.link_state())

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
        threading.Thread(target=self.command_loop, daemon=True).start()
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
