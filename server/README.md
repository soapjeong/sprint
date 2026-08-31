# 백엔드 API 서버 (FastAPI)

데이터베이스는 두 가지를 지원한다. `DATABASE_URL` 이 있으면 **PostgreSQL**(배포용),
없으면 `SLEEP_DB_PATH` 의 **SQLite 파일**(로컬 개발). 질의는 한 벌만 쓰고 엔진 차이는
`server/app/db.py` 가 흡수한다. 무료 배포 절차는 [DEPLOY.md](DEPLOY.md).

앱의 사용자 페이지/관리자 페이지가 같이 쓰는 서버. ESP32 로그는 PC 시리얼 브리지를 통해 올라온다.

```
ESP32 --USB--> serial_csv_logger.py --HTTP--> FastAPI --> SQLite
                                                   ^
                                          모바일 앱(사용자/관리자)
```

## 실행

```bash
pip install -r server/requirements.txt
python server/run.py            # 접속 주소·토큰을 출력하고 서버를 띄운다
```

`run.py` 는 실행 위치와 상관없이 동작한다(`python C:\Users\...\sprint\server\run.py` 도 가능).
직접 uvicorn 을 쓰려면 **레포 루트에서** 실행해야 한다 — 다른 폴더에서 실행하면
`ModuleNotFoundError: No module named 'server'` 가 난다.

```bash
cd <레포 루트>
ADMIN_TOKEN=... INGEST_API_KEY=... \
  uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

- DB 위치: `DATABASE_URL`(PostgreSQL) 또는 `SLEEP_DB_PATH`(SQLite, 기본 `server/data/sleep.db`)
- 앱에서 접속할 주소는 PC의 LAN IP (`http://192.168.0.x:8000`). `localhost` 는 폰에서 열리지 않는다.
- 대화형 API 문서: `http://<서버>:8000/docs`

## 인증

| 대상 | 헤더 | 발급 방법 |
|------|------|-----------|
| 앱 사용자 | `X-User-Token` | 가입/로그인(`/api/users`, `/api/auth/login`) 시 발급 |
| 시리얼 브리지 업로드 | `X-API-Key` | 환경변수 `INGEST_API_KEY` |
| 관리자 조회 | `X-Admin-Token` | 환경변수 `ADMIN_TOKEN` |

- 사용자 데이터(`/api/users/{id}/*`, `/api/sessions/*`)는 **본인 토큰으로만** 접근된다.
  남의 ID 를 알아도 403 이다. 비밀번호는 scrypt 로 해시해 저장한다(평문 저장 없음).
- 로그인 실패 응답은 "ID 없음"과 "비밀번호 틀림"을 구분하지 않는다(계정 열거 방지).
- 기본 토큰(`dev-admin-token` / `dev-ingest-key`)으로는 서버가 기동을 거부한다.
  `server/run.py` 로 실행하면 로컬 개발로 보고 자동 허용한다(`SLEEP_ALLOW_DEV_TOKENS=1`).
  같은 Wi-Fi 를 여럿이 쓰는 곳이라면 토큰을 직접 정해서 실행하는 편이 안전하다.

## 테스트를 PostgreSQL 로도 돌리기

```bash
TEST_DATABASE_URL="postgresql://..." python -m pytest server/tests -q
```

## 엔드포인트

**사용자 (앱 첫 화면 · 사용자 페이지)**

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/users` | 가입 — ID·비밀번호 등록, 접근 토큰 발급 (중복 시 409) |
| POST | `/api/auth/login` | 로그인 — 접근 토큰 발급 |
| POST | `/api/auth/logout` | 이 기기의 토큰 폐기 |
| GET | `/api/users/{id}` | 내 정보 |
| POST | `/api/devices` | 기기 등록 / 소유자 변경 |
| GET | `/api/devices/pending` | 등록되지 않은 채 신호를 보내온 기기 목록(앱의 "연결된 기기 찾기") |
| GET | `/api/users/{id}/devices` | 내 기기 목록 |
| DELETE | `/api/devices/{device_id}` | 기기 등록 해제 |
| GET | `/api/users/{id}/summary` | 세션 수, 평균·최단 SOL, 온도별 성적, 최근 세션 |
| GET | `/api/users/{id}/sessions` | 세션 목록 |
| GET | `/api/sessions/{session_id}` | 세션 + 측정 샘플 + 이벤트 |
| POST | `/api/sessions/{session_id}/review` | 아침 수면 평가(별점 1~5 + 특이사항) |

**브리지 업로드** (`X-API-Key`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/ingest/announce` | 기기 부팅(`@ID,...`) 통보 — 미등록이면 pending 목록에 올린다 |
| POST | `/api/ingest/events` | `@FLAG` / `@RESULT` 한 줄 → 세션 상태 갱신 |
| POST | `/api/ingest/samples` | 1초 주기 측정값 배치 |

**관리자** (`X-Admin-Token`) — 사용자 앱과 분리된 `admin-web/` 대시보드가 쓴다

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/admin/users` | ID별 세션 수·입면 수·평균 SOL·최근 활동 |
| GET | `/api/admin/users/{id}` | 해당 ID의 기기/세션/이벤트 전체 |
| GET | `/api/admin/export/sessions.csv` | 세션 CSV 내보내기(`?user_id=` 필터) |

## 관리자 대시보드

`admin-web/` 의 정적 사이트를 서버가 `/admin/` 에 얹어 서비스한다(`https://<서버>/admin/`).
사용자 앱에는 관리자 화면이 없고, 앱에서 여기로 넘어가는 경로도 없다.
토큰은 브라우저 탭 세션에만 보관된다(탭을 닫으면 지워짐).

완전히 다른 곳에 올리고 싶으면 `admin-web/` 폴더만 정적 호스팅에 올리거나
`python admin-web/serve.py` 로 따로 띄우면 된다(서버 주소는 화면에서 입력).

## 기기 등록 흐름

기기 ID 는 ESP32 칩의 MAC 에서 만들어져 사람이 외울 수 없다. 그래서 이렇게 등록한다.

1. 기기를 USB 로 연결하고 브리지 실행 → 브리지가 `@ID,...` 를 보고 `/api/ingest/announce` 호출
2. 미등록 기기이므로 `pending_devices` 에 올라감 (측정 데이터는 이 시점엔 404 로 거절)
3. 앱 첫 화면에서 **연결된 기기 찾기** → 목록에서 선택 → `/api/devices` 로 등록
4. 이후 업로드부터 그 사용자 ID 로 쌓인다

## 아침 수면 평가

세션이 끝나면(`onset` / `no_onset`) 그 세션은 평가 대기 상태가 되고,
`/api/users/{id}/summary` 의 `pending_review` 에 실려 앱 홈 화면에 평가 카드가 뜬다.
별점(1~5)과 특이사항(`alcohol` / `caffeine` / `none` / `other`)을 저장하면 카드가 사라진다.
`other` 는 `note_text` 가 비어 있으면 422 로 거절한다.

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
