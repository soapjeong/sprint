# 백엔드 API 서버 (FastAPI + SQLite)

앱의 사용자 페이지/관리자 페이지가 같이 쓰는 서버. ESP32 로그는 PC 시리얼 브리지를 통해 올라온다.

```
ESP32 --USB--> serial_csv_logger.py --HTTP--> FastAPI --> SQLite
                                                   ^
                                          모바일 앱(사용자/관리자)
```

## 실행

```bash
pip install -r server/requirements.txt
# 토큰은 반드시 바꿔서 실행할 것 (기본값은 개발용)
ADMIN_TOKEN=... INGEST_API_KEY=... \
  uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

- DB 파일 위치: `SLEEP_DB_PATH` (기본 `server/data/sleep.db`)
- 앱에서 접속할 주소는 PC의 LAN IP (`http://192.168.0.x:8000`). `localhost` 는 폰에서 열리지 않는다.
- 대화형 API 문서: `http://<서버>:8000/docs`

## 인증

| 대상 | 헤더 | 환경변수 |
|------|------|----------|
| 시리얼 브리지 업로드 | `X-API-Key` | `INGEST_API_KEY` |
| 관리자 조회 | `X-Admin-Token` | `ADMIN_TOKEN` |
| 사용자 조회 | 없음(ID 기반) | - |

연구/데모 수준의 보호다. 외부 공개 시에는 사용자 계정 인증(예: JWT)으로 교체해야 한다.

## 엔드포인트

**사용자 (앱 첫 화면 · 사용자 페이지)**

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/users` | 사용자 ID 등록 (중복 시 409) |
| GET | `/api/users/{id}` | ID 존재 확인(기존 ID로 로그인) |
| POST | `/api/devices` | 기기 등록 / 소유자 변경 |
| GET | `/api/users/{id}/devices` | 내 기기 목록 |
| DELETE | `/api/devices/{device_id}` | 기기 등록 해제 |
| GET | `/api/users/{id}/summary` | 세션 수, 평균·최단 SOL, 온도별 성적, 최근 세션 |
| GET | `/api/users/{id}/sessions` | 세션 목록 |
| GET | `/api/sessions/{session_id}` | 세션 + 측정 샘플 + 이벤트 |

**브리지 업로드** (`X-API-Key`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/ingest/events` | `@FLAG` / `@RESULT` 한 줄 → 세션 상태 갱신 |
| POST | `/api/ingest/samples` | 1초 주기 측정값 배치 |

**관리자** (`X-Admin-Token`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/admin/users` | ID별 세션 수·입면 수·평균 SOL·최근 활동 |
| GET | `/api/admin/users/{id}` | 해당 ID의 기기/세션/이벤트 전체 |
| GET | `/api/admin/export/sessions.csv` | 세션 CSV 내보내기(`?user_id=` 필터) |

## 세션이 만들어지는 규칙

펌웨어 플래그가 그대로 세션 수명주기가 된다.

| 플래그 | 서버 동작 |
|--------|-----------|
| `SESSION_START` | 새 세션 생성(이전에 안 닫힌 세션은 `aborted` 로 정리), 목표 온도 기록 |
| `HR_BASELINE` / `..._FALLBACK` | 안정심박수·입면 기준 기록 |
| `SLEEP_ONSET` | `outcome=onset`, SOL 기록 |
| `NO_ONSET` | `outcome=no_onset`, SOL 60분 기록 |
| `SESSION_DONE` / `POWER_OFF` | 세션 종료 시각 기록 |

측정 샘플은 진행 중인 세션에 붙는다. 브리지가 배치로 올리는 특성상 종료 이벤트보다 늦게
도착하는 묶음이 있어, 방금(10분 이내) 끝난 세션까지는 받아준다.

## 테스트

```bash
python -m pytest tests server/tests -q
```
