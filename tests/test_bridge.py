"""시리얼 브리지: 로그 파싱과 서버 업로드 페이로드 검증."""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import serial_csv_logger as bridge  # noqa: E402
from server.app import db  # noqa: E402
from server.app.main import app  # noqa: E402

SAMPLE_LOG = os.path.join(ROOT, "tests", "data", "sample_serial.log")
STATUS_LINE = (
    "[진행상태] 시간:51초 | 피부온도:34.8℃ | 히터온도:36.2℃ | 목표:39.0℃ | 히터파워:82% | "
    "심박수:64BPM | 안정심박:66BPM | 입면기준:56BPM | 센서:ON | 안전:NORMAL | 세션:RUNNING | "
    "연속수면(분):3 | 판정: 깨어있음"
)


def test_parse_status_line():
    s = bridge.parse_status_line(STATUS_LINE)
    assert s["device_ms"] == 51_000
    assert s["skin_c"] == 34.8 and s["heater_c"] == 36.2 and s["target_c"] == 39.0
    assert s["duty_pct"] == 82.0 and s["bpm"] == 64.0
    assert s["resting_bpm"] == 66.0 and s["threshold_bpm"] == 56.0
    assert s["sensor_state"] == "ON" and s["session_state"] == "RUNNING"
    assert s["quiet_min"] == 3 and s["asleep"] is False


def test_parse_status_line_marks_sleep():
    line = STATUS_LINE.replace("판정: 깨어있음", "판정: 수면중")
    assert bridge.parse_status_line(line)["asleep"] is True


def test_csv_row_matches_headers():
    assert len(bridge.status_row_for_csv(STATUS_LINE)) == len(bridge.CSV_HEADERS)


def test_non_status_lines_ignored():
    assert bridge.parse_status_line("# 센서 측정 정지") is None
    assert bridge.parse_event_line("# 그냥 안내문") is None


def test_parse_device_id_line():
    assert bridge.parse_device_id_line("@ID,DORMX-246F28AABBCC") == "DORMX-246F28AABBCC"
    assert bridge.parse_device_id_line("# 기기 ID = DORMX-1") is None


def test_parse_flag_and_result_lines():
    e = bridge.parse_event_line("@FLAG,sub01,SLEEP_ONSET,1500000,24.50,66.00")
    assert e == {
        "flag": "SLEEP_ONSET", "device_ms": 1_500_000, "values": [24.5, 66.0],
        "raw": "@FLAG,sub01,SLEEP_ONSET,1500000,24.50,66.00",
    }
    r = bridge.parse_event_line("@RESULT,sub01,39.0,24.50,0,39.0,24.50,38.0")
    assert r["flag"] == "RESULT" and r["values"][:2] == [39.0, 24.5]


@pytest.fixture()
def captured_upload(tmp_path, monkeypatch):
    """실제 HTTP 대신 페이로드를 모아두는 업로더로 로그 파일을 재생한다."""
    posts: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        bridge.ServerUploader, "_post",
        lambda self, path, payload: posts.append((path, payload)) or {},
    )
    uploader = bridge.ServerUploader("http://test", "dev-ingest-key", "", batch=1000)
    logger = bridge.SerialCsvLogger(None, 115200, str(tmp_path), uploader=uploader, replay=SAMPLE_LOG)
    logger.uploader.start()
    logger.run()
    return posts


def test_device_id_comes_from_firmware(captured_upload):
    """--device 없이도 기기가 알려준 MAC 기반 ID 로 업로드된다."""
    announces = [p for path, p in captured_upload if path.endswith("/announce")]
    assert announces and announces[0]["device_id"] == "DORMX-246F28AABBCC"
    assert all(p["device_id"] == "DORMX-246F28AABBCC" for path, p in captured_upload)


def test_uploads_keep_firmware_order(captured_upload):
    """세션 시작 이벤트보다 샘플이 먼저 도착하면 서버가 버리므로 순서가 유지돼야 한다."""
    kinds = [p.rsplit("/", 1)[-1] for p, _ in captured_upload]
    assert kinds[0] == "announce"
    assert kinds.index("events") < kinds.index("samples")


def test_replay_uploads_events_and_samples(captured_upload):
    events = [p for path, p in captured_upload if path.endswith("/events")]
    samples = [p for path, p in captured_upload if path.endswith("/samples")]
    assert [e["flag"] for e in events] == [
        "SESSION_START", "WARMUP_DONE", "HR_BASELINE", "SLEEP_ONSET",
        "RESULT", "COOLDOWN_START", "SESSION_DONE", "POWER_OFF",
    ]
    assert all(e["device_id"] == "DORMX-246F28AABBCC" for e in events)
    uploaded = [s for batch in samples for s in batch["samples"]]
    assert len(uploaded) == 6
    assert uploaded[0]["session_state"] == "WARMUP" and uploaded[0]["duty_pct"] == 0.0
    assert uploaded[-1]["asleep"] is True


def test_uploaded_payloads_are_accepted_by_server(tmp_path, monkeypatch, captured_upload):
    """브리지가 만든 페이로드를 그대로 서버에 넣어 세션이 완성되는지 확인."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "e2e.db"))
    monkeypatch.setenv("SLEEP_ALLOW_DEV_TOKENS", "1")
    db.init_db(str(tmp_path / "e2e.db"))
    with TestClient(app) as client:
        signup = client.post(
            "/api/users", json={"user_id": "sub01", "name": "테스터", "password": "sleep-pass-1"}
        )
        headers = {"X-User-Token": signup.json()["access_token"]}
        client.post(
            "/api/devices",
            headers=headers,
            json={"device_id": "DORMX-246F28AABBCC", "user_id": "sub01", "label": "침대"},
        )
        for path, payload in captured_upload:
            r = client.post("/api" + path.split("/api", 1)[1], headers={"X-API-Key": "dev-ingest-key"}, json=payload)
            assert r.status_code == 200, r.text

        summary = client.get("/api/users/sub01/summary", headers=headers).json()
        assert summary["session_count"] == 1
        assert summary["onset_count"] == 1
        assert summary["best_sol_min"] == 24.5
        assert summary["best_temp_c"] == 39.0

        session_id = summary["recent_sessions"][0]["session_id"]
        detail = client.get(f"/api/sessions/{session_id}", headers=headers).json()
        assert detail["session"]["resting_bpm"] == 66.0
        assert detail["session"]["threshold_bpm"] == 56.0
        assert detail["session"]["ended_at"] is not None
        assert len(detail["samples"]) == 6


# ---------------------------------------------------------------- 앱 명령 / 연결 상태
class FakeSerial:
    def __init__(self, ok=True):
        self.is_open = True
        self.ok = ok
        self.written = []

    def write(self, data):
        if not self.ok:
            raise OSError("포트가 닫혔습니다")
        self.written.append(data.decode())


def make_logger(tmp_path, **kwargs):
    return bridge.SerialCsvLogger(None, 115200, str(tmp_path), replay=None, **kwargs)


def test_link_state_distinguishes_cable_and_power(tmp_path):
    """'연결 안 됨'과 '기기 무응답(전원/배터리)'을 앱에서 구분할 수 있어야 한다."""
    logger = make_logger(tmp_path)
    assert logger.link_state() == "no_port"          # 포트 자체가 없음

    logger.ser = FakeSerial()
    assert logger.link_state() == "no_data"          # 포트는 열렸는데 로그가 없음

    logger.handle_line("[진행상태] 시간:1초 | 피부온도:30.0℃ | 세션:IDLE")
    assert logger.link_state() == "online"

    logger.last_line_at -= bridge.SILENT_LIMIT_SEC + 1
    assert logger.link_state() == "no_data"          # 로그가 끊긴 지 오래됨
    logger.close()


def test_app_command_is_written_to_serial(tmp_path, monkeypatch):
    posts = []
    monkeypatch.setattr(bridge.ServerUploader, "_post",
                        lambda self, path, payload: posts.append((path, payload)) or {})
    monkeypatch.setattr(bridge.ServerUploader, "_get",
                        lambda self, path: [{"command_id": 7, "command": "start"}])
    uploader = bridge.ServerUploader("http://test", "key", "DORMX-1")
    logger = make_logger(tmp_path, uploader=uploader)
    logger.ser = FakeSerial()

    for command in uploader.take_commands():
        ok = logger.send_serial(command["command"])
        uploader.ack_command(command["command_id"], ok, "시리얼 전송")
    assert logger.ser.written == ["start\n"]

    uploader.start()
    uploader.close()
    acks = [p for path, p in posts if "ack" in path]
    assert acks and acks[0]["status"] == "done"
    logger.close()


def test_failed_command_is_reported_as_failed(tmp_path, monkeypatch):
    posts = []
    monkeypatch.setattr(bridge.ServerUploader, "_post",
                        lambda self, path, payload: posts.append((path, payload)) or {})
    uploader = bridge.ServerUploader("http://test", "key", "DORMX-1")
    logger = make_logger(tmp_path, uploader=uploader)
    logger.ser = FakeSerial(ok=False)          # 기기가 빠졌거나 꺼진 상태

    ok = logger.send_serial("start")
    uploader.ack_command(7, ok, "기기가 연결되어 있지 않음")
    uploader.start()
    uploader.close()
    assert not ok
    assert [p["status"] for path, p in posts if "ack" in path] == ["failed"]
    logger.close()
