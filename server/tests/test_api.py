"""API 통합 테스트: 등록 → 세션 업로드 → 사용자/관리자 조회."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from server.app import db  # noqa: E402
from server.app.main import app  # noqa: E402

INGEST = {"X-API-Key": "dev-ingest-key"}
ADMIN = {"X-Admin-Token": "dev-admin-token"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db(path)
    with TestClient(app) as c:
        yield c


def register(client, user_id="sub01", device_id="DORMX-001"):
    assert client.post("/api/users", json={"user_id": user_id, "name": "테스터"}).status_code == 201
    r = client.post("/api/devices", json={"device_id": device_id, "user_id": user_id, "label": "내 기기"})
    assert r.status_code == 201
    return user_id, device_id


def flag(client, device_id, name, values, ms=0):
    return client.post(
        "/api/ingest/events",
        headers=INGEST,
        json={"device_id": device_id, "flag": name, "device_ms": ms, "values": values},
    )


# ---------------------------------------------------------------- 등록
def test_user_id_must_be_unique(client):
    register(client)
    dup = client.post("/api/users", json={"user_id": "sub01", "name": "다른 사람"})
    assert dup.status_code == 409


def test_device_requires_registered_user(client):
    r = client.post("/api/devices", json={"device_id": "DORMX-009", "user_id": "nobody", "label": ""})
    assert r.status_code == 404


def test_device_reregistration_updates_owner(client):
    register(client)
    client.post("/api/users", json={"user_id": "sub02", "name": "둘째"})
    r = client.post("/api/devices", json={"device_id": "DORMX-001", "user_id": "sub02", "label": "이사감"})
    assert r.status_code == 201
    assert r.json()["user_id"] == "sub02"
    assert client.get("/api/users/sub01/devices").json() == []


def test_invalid_user_id_rejected(client):
    assert client.post("/api/users", json={"user_id": "a b/c", "name": ""}).status_code == 422


# ---------------------------------------------------------------- 업로드 권한
def test_ingest_requires_api_key(client):
    _, device_id = register(client)
    r = client.post("/api/ingest/events", json={"device_id": device_id, "flag": "SESSION_START", "values": [39.0]})
    assert r.status_code == 401


def test_ingest_rejects_unregistered_device(client):
    r = flag(client, "GHOST-1", "SESSION_START", [39.0])
    assert r.status_code == 404


# ---------------------------------------------------------------- 세션 수명주기
def test_full_session_lifecycle(client):
    user_id, device_id = register(client)

    started = flag(client, device_id, "SESSION_START", [39.0], ms=1000)
    session_id = started.json()["session_id"]
    assert started.json()["detail"] == "세션 시작"

    flag(client, device_id, "WARMUP_DONE", [39.0], ms=21000)
    flag(client, device_id, "HR_BASELINE", [66.0, 56.0], ms=51000)

    samples = [
        {
            "device_ms": 1000 + i * 1000, "skin_c": 36.0 + i * 0.1, "heater_c": 38.0,
            "target_c": 39.0, "duty_pct": 40.0, "bpm": 62.0, "resting_bpm": 66.0,
            "threshold_bpm": 56.0, "sensor_state": "ON", "safety_state": "NORMAL",
            "session_state": "RUNNING", "quiet_min": i, "asleep": False,
        }
        for i in range(5)
    ]
    up = client.post("/api/ingest/samples", headers=INGEST, json={"device_id": device_id, "samples": samples})
    assert up.json()["stored"] == 5

    flag(client, device_id, "SLEEP_ONSET", [24.5, 66.0], ms=1_500_000)
    flag(client, device_id, "POWER_OFF", [0, 0], ms=2_100_000)

    detail = client.get(f"/api/sessions/{session_id}").json()
    assert detail["session"]["outcome"] == "onset"
    assert detail["session"]["sol_min"] == 24.5
    assert detail["session"]["resting_bpm"] == 66.0
    assert detail["session"]["ended_at"] is not None
    assert len(detail["samples"]) == 5
    assert detail["samples"][0]["elapsed_s"] == 0
    assert detail["samples"][4]["elapsed_s"] == 4
    assert [e["flag"] for e in detail["events"]][:2] == ["SESSION_START", "WARMUP_DONE"]


def test_no_onset_session_recorded_as_timeout(client):
    _, device_id = register(client)
    flag(client, device_id, "SESSION_START", [38.5])
    flag(client, device_id, "NO_ONSET", [60.0])
    flag(client, device_id, "POWER_OFF", [0, 0])
    sessions = client.get("/api/users/sub01/sessions").json()
    assert sessions[0]["outcome"] == "no_onset"
    assert sessions[0]["sol_min"] == 60.0


def test_new_session_closes_previous_open_one(client):
    _, device_id = register(client)
    flag(client, device_id, "SESSION_START", [39.0])
    flag(client, device_id, "SESSION_START", [38.0])
    sessions = client.get("/api/users/sub01/sessions").json()
    assert len(sessions) == 2
    assert sessions[1]["outcome"] == "aborted"      # 앞선 세션이 정리됨
    assert sessions[0]["outcome"] == "running"


def test_late_samples_attach_to_recently_closed_session(client):
    """브리지가 배치로 올리는 마지막 샘플이 세션 종료 뒤에 도착해도 버리지 않는다."""
    _, device_id = register(client)
    flag(client, device_id, "SESSION_START", [39.0], ms=1000)
    flag(client, device_id, "SLEEP_ONSET", [24.5])
    flag(client, device_id, "POWER_OFF", [0, 0])
    r = client.post(
        "/api/ingest/samples",
        headers=INGEST,
        json={"device_id": device_id, "samples": [{"device_ms": 2000, "skin_c": 38.9}]},
    )
    assert r.json()["stored"] == 1
    detail = client.get(f"/api/sessions/{r.json()['session_id']}").json()
    assert detail["samples"][0]["skin_c"] == 38.9


def test_samples_without_open_session_are_skipped(client):
    _, device_id = register(client)
    r = client.post(
        "/api/ingest/samples",
        headers=INGEST,
        json={"device_id": device_id, "samples": [{"device_ms": 1000, "skin_c": 30.0}]},
    )
    assert r.json() == {"stored": 0, "skipped": 1, "session_id": None, "detail": "진행 중인 세션 없음"}


# ---------------------------------------------------------------- 기기 자동 발견(칩 MAC ID)
def announce(client, device_id, firmware=""):
    return client.post(
        "/api/ingest/announce",
        headers=INGEST,
        json={"device_id": device_id, "firmware": firmware},
    )


def test_unregistered_device_shows_up_as_pending(client):
    """기기 ID 는 칩 MAC 이라 손으로 못 외우므로, 앱이 목록에서 고를 수 있어야 한다."""
    r = announce(client, "DORMX-246F28AABBCC", "v7")
    assert r.json() == {
        "device_id": "DORMX-246F28AABBCC", "registered": False, "user_id": None,
        "detail": "앱에서 이 기기를 등록하세요.",
    }
    pending = client.get("/api/devices/pending").json()
    assert [p["device_id"] for p in pending] == ["DORMX-246F28AABBCC"]
    assert pending[0]["firmware"] == "v7"


def test_registered_device_is_not_pending(client):
    announce(client, "DORMX-246F28AABBCC")
    client.post("/api/users", json={"user_id": "sub01", "name": ""})
    client.post("/api/devices", json={"device_id": "DORMX-246F28AABBCC", "user_id": "sub01", "label": ""})
    assert client.get("/api/devices/pending").json() == []

    again = announce(client, "DORMX-246F28AABBCC")
    assert again.json()["registered"] is True and again.json()["user_id"] == "sub01"
    assert client.get("/api/devices/pending").json() == []


def test_pending_list_hides_old_sightings(client):
    """며칠 전에 잠깐 켰던 기기가 목록을 채우지 않도록 최근 것만 보여준다."""
    announce(client, "DORMX-OLD")
    stale = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(timespec="seconds")
    with db.session_scope() as conn:
        conn.execute("UPDATE pending_devices SET last_seen_at=?", (stale,))

    assert client.get("/api/devices/pending?minutes=60").json() == []
    assert [p["device_id"] for p in client.get("/api/devices/pending?minutes=600").json()] == ["DORMX-OLD"]


# ---------------------------------------------------------------- 아침 수면 평가
def review(client, session_id, rating, note_code, note_text=""):
    return client.post(
        f"/api/sessions/{session_id}/review",
        json={"rating": rating, "note_code": note_code, "note_text": note_text},
    )


def finished_session(client, device_id="DORMX-001", sol=25.0):
    flag(client, device_id, "SESSION_START", [39.0])
    flag(client, device_id, "SLEEP_ONSET", [sol])
    flag(client, device_id, "POWER_OFF", [0, 0])
    return client.get("/api/users/sub01/sessions").json()[0]["session_id"]


def test_review_records_rating_and_note(client):
    _, device_id = register(client)
    sid = finished_session(client, device_id)
    r = review(client, sid, 4, "caffeine")
    assert r.status_code == 200
    body = r.json()
    assert body["rating"] == 4 and body["note_code"] == "caffeine" and body["reviewed_at"]


def test_review_rejects_bad_input(client):
    _, device_id = register(client)
    sid = finished_session(client, device_id)
    assert review(client, sid, 6, "none").status_code == 422          # 별점 범위 밖
    assert review(client, sid, 3, "hangover").status_code == 422      # 없는 특이사항 코드
    assert review(client, sid, 3, "other").status_code == 422         # 기타인데 내용 없음
    assert review(client, sid, 3, "other", "야근").status_code == 200


def test_home_asks_for_review_until_it_is_given(client):
    _, device_id = register(client)
    sid = finished_session(client, device_id)

    summary = client.get("/api/users/sub01/summary").json()
    assert summary["pending_review"]["session_id"] == sid    # 홈 화면에 평가 카드
    assert summary["avg_rating"] is None

    review(client, sid, 5, "none")
    summary = client.get("/api/users/sub01/summary").json()
    assert summary["pending_review"] is None                 # 평가하면 카드가 사라진다
    assert summary["avg_rating"] == 5.0
    assert summary["recent_sessions"][0]["note_code"] == "none"


def test_running_session_is_not_asked_for_review(client):
    _, device_id = register(client)
    flag(client, device_id, "SESSION_START", [39.0])
    assert client.get("/api/users/sub01/summary").json()["pending_review"] is None


def test_admin_sees_average_rating(client):
    _, device_id = register(client)
    sid = finished_session(client, device_id)
    review(client, sid, 4, "alcohol", "")
    row = client.get("/api/admin/users", headers=ADMIN).json()[0]
    assert row["avg_rating"] == 4.0
    csv_text = client.get("/api/admin/export/sessions.csv", headers=ADMIN).text
    assert "rating,note_code,note_text" in csv_text.splitlines()[0]
    assert ",4,alcohol," in csv_text.splitlines()[1]


# ---------------------------------------------------------------- 사용자 화면 집계
def test_user_summary_picks_best_temperature(client):
    _, device_id = register(client)
    for temp, sol in [(39.0, 30.0), (38.0, 20.0), (38.0, 22.0), (40.0, 41.0)]:
        flag(client, device_id, "SESSION_START", [temp])
        flag(client, device_id, "SLEEP_ONSET", [sol])
        flag(client, device_id, "POWER_OFF", [0, 0])

    s = client.get("/api/users/sub01/summary").json()
    assert s["session_count"] == 4
    assert s["onset_count"] == 4
    assert s["best_sol_min"] == 20.0
    assert s["best_temp_c"] == 38.0                  # 평균 SOL 21분으로 가장 짧음
    assert {t["target_temp_c"]: t["onset_count"] for t in s["temp_stats"]} == {38.0: 2, 39.0: 1, 40.0: 1}
    assert len(s["devices"]) == 1


def test_summary_unknown_user_is_404(client):
    assert client.get("/api/users/ghost/summary").status_code == 404


# ---------------------------------------------------------------- 관리자
def test_admin_requires_token(client):
    assert client.get("/api/admin/users").status_code == 401


def test_admin_lists_data_per_user_id(client):
    register(client, "sub01", "DORMX-001")
    register(client, "sub02", "DORMX-002")
    for device_id, sol in [("DORMX-001", 25.0), ("DORMX-002", 18.0), ("DORMX-002", 22.0)]:
        flag(client, device_id, "SESSION_START", [39.0])
        flag(client, device_id, "SLEEP_ONSET", [sol])
        flag(client, device_id, "POWER_OFF", [0, 0])

    rows = {r["user_id"]: r for r in client.get("/api/admin/users", headers=ADMIN).json()}
    assert rows["sub01"]["session_count"] == 1
    assert rows["sub02"]["session_count"] == 2
    assert rows["sub02"]["avg_sol_min"] == 20.0
    assert rows["sub01"]["device_count"] == 1

    detail = client.get("/api/admin/users/sub02", headers=ADMIN).json()
    assert len(detail["sessions"]) == 2
    assert detail["recent_events"][0]["flag"] == "POWER_OFF"


def test_admin_csv_export(client):
    register(client)
    flag(client, "DORMX-001", "SESSION_START", [39.0])
    flag(client, "DORMX-001", "SLEEP_ONSET", [21.0])
    csv_text = client.get("/api/admin/export/sessions.csv", headers=ADMIN).text
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("session_id,user_id,device_id")
    assert "sub01" in lines[1] and "onset" in lines[1]
