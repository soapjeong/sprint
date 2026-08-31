# 무료로 서버 올리기 (내 PC 를 켜두지 않아도 앱이 도는 구조)

| | 지금(로컬) | 배포 후 |
|---|---|---|
| 앱에서 기록 보기 | 내 PC 가 켜져 있어야 함 | 언제든 가능 |
| 측정(브리지) | PC 필요 | **측정하는 밤에만** PC 필요 |
| 주소 | `http://192.168.x.x:8000` | `https://<이름>.onrender.com` |

> 브리지(ESP32 ↔ 서버)는 여전히 PC 가 필요하다. USB 로 기기를 물고 있어야 하기 때문이다.

## 무료 조합: Render(웹) + Neon(데이터베이스)

2026년 기준으로 **완전 무료 + 데이터 영구 보관**이 되는 현실적인 조합이다.

| | 무료 조건 | 주의 |
|---|---|---|
| **Render** 웹 서비스 | 512MB RAM, 월 750시간 | 15분 유휴 시 잠들고, 다음 요청에 **최대 1분** 걸림 |
| **Neon** PostgreSQL | 0.5GB, **기간 제한 없음** | 유휴 시 절전, 첫 질의에서 자동 기동 |

Render 자체 무료 PostgreSQL 은 **30일 후 만료**되므로 쓰지 않는다.
Fly.io 는 신규 가입 무료 티어가 없어졌다(카드 등록 + 종량제).

브리지는 잠든 서버를 깨우는 동안 자동으로 재시도하므로(최대 약 1분) 데이터는 유실되지 않는다.

## 1. Neon 에서 데이터베이스 만들기

1. https://neon.com 가입 → New Project (리전은 아무거나, 가까운 곳)
2. 연결 문자열(Connection string)을 복사한다:
   `postgresql://user:password@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`

## 2. 토큰 만들기

```powershell
python -c "import secrets; print('ADMIN_TOKEN =', secrets.token_urlsafe(24)); print('INGEST_API_KEY =', secrets.token_urlsafe(24))"
```

## 3. Render 에 올리기

1. https://render.com 가입 → **New +** → **Blueprint** → 이 GitHub 저장소 선택
   (저장소 루트의 `render.yaml` 을 읽어 Docker 로 빌드한다)
2. 환경변수 세 개를 입력한다.

   | 이름 | 값 |
   |------|-----|
   | `DATABASE_URL` | 1단계에서 복사한 Neon 연결 문자열 |
   | `ADMIN_TOKEN` | 2단계에서 만든 값 |
   | `INGEST_API_KEY` | 2단계에서 만든 값 |

3. Deploy 후 주소 확인: `https://<이름>.onrender.com/api/health` → `{"status":"ok"}`

Blueprint 대신 **New + → Web Service → Docker** 로 직접 만들어도 결과는 같다.

## 4. 앱과 브리지에 새 주소 넣기

**앱**: 첫 화면 서버 주소에 `https://<이름>.onrender.com` 입력 → [서버 연결 확인].
기본값을 바꾸려면 `mobile/app.json` 의 `extra.defaultServerUrl` 을 수정한다.
HTTPS 로만 접속한다면 `mobile/app.json` 의 `usesCleartextTraffic` 은 지워도 된다.

**브리지**(측정하는 밤에 PC 에서):

```powershell
python serial_csv_logger.py --port COM5 `
  --server https://<이름>.onrender.com --api-key 발급한_INGEST_API_KEY
```

## 잠드는 게 신경 쓰이면

- Render 무료는 월 750시간이라 한 서비스를 계속 깨워두는 것도 한도 안에 들어간다.
  UptimeRobot 같은 무료 모니터링에서 `https://<이름>.onrender.com/api/health` 를
  10분마다 호출하게 두면 사실상 상시 가동이 된다.
- 콜드스타트가 실제로 문제 되는 구간은 브리지 업로드뿐인데, 브리지가 재시도하므로
  기록이 사라지지는 않는다.

## 데이터 백업

Neon 대시보드에서 SQL 로 내려받거나, 관리자 CSV 를 쓴다.

```
GET https://<이름>.onrender.com/api/admin/export/sessions.csv
  헤더: X-Admin-Token: 발급한_ADMIN_TOKEN
```

## 로컬 개발은 그대로

`DATABASE_URL` 이 없으면 예전처럼 `server/data/sleep.db`(SQLite)를 쓴다.
`python server/run.py` 는 로컬 전용이라 기본 토큰도 허용한다.

## 데이터 옮기기(선택)

이미 로컬에 쌓인 SQLite 데이터를 Neon 으로 옮기려면:

```bash
python server/migrate_sqlite_to_postgres.py \
  --sqlite server/data/sleep.db --postgres "postgresql://...neon.tech/neondb?sslmode=require"
```
