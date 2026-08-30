# 클라우드 배포 (PC 를 켜두지 않아도 앱이 도는 구조)

배포하면 이렇게 바뀐다.

| | 배포 전 | 배포 후 |
|---|---|---|
| 앱에서 기록 보기 | 내 PC 가 켜져 있어야 함 | 언제든 가능 |
| 측정(브리지) | PC 필요 | **측정하는 밤에만** PC 필요 |
| 주소 | `http://192.168.x.x:8000` | `https://<앱이름>.fly.dev` |

> 브리지(ESP32 ↔ 서버)는 여전히 PC 가 필요하다. 이것까지 없애려면 ESP32 에 Wi-Fi 업로드를
> 넣거나, 라즈베리파이가 브리지를 대신 돌리면 된다.

## 배포 전에 반드시

서버가 인터넷에 열리므로 **기본 토큰으로는 기동되지 않는다**(의도된 동작).
`ADMIN_TOKEN`, `INGEST_API_KEY` 를 직접 만들어 넣어야 한다.

```bash
python -c "import secrets; print('ADMIN_TOKEN =', secrets.token_urlsafe(24)); print('INGEST_API_KEY =', secrets.token_urlsafe(24))"
```

사용자 데이터는 비밀번호 로그인으로 보호된다(앱에서 가입 시 설정). 관리자 토큰은 전체
사용자 데이터를 볼 수 있으니 연구 책임자만 알고 있어야 한다.

## Fly.io (권장 — SQLite 를 볼륨에 그대로 유지)

```bash
# 1) 설치 및 로그인
#    Windows PowerShell: iwr https://fly.io/install.ps1 -useb | iex
fly auth signup            # 또는 fly auth login

# 2) 앱 생성 (fly.toml 의 app 이름은 전 세계에서 유일해야 하므로 필요하면 바꾼다)
fly launch --no-deploy --copy-config

# 3) SQLite 가 살 볼륨 — 머신과 같은 리전에 만든다
fly volumes create dormx_data --size 1 --region nrt

# 4) 비밀값 등록
fly secrets set ADMIN_TOKEN=여기에_생성한_값 INGEST_API_KEY=여기에_생성한_값

# 5) 배포
fly deploy

# 6) 주소 확인
fly status        # https://<앱이름>.fly.dev
curl https://<앱이름>.fly.dev/api/health
```

`fly.toml` 은 요청이 없으면 머신을 재우고(`auto_stop_machines`), 요청이 오면 깨운다.
첫 요청이 몇 초 걸릴 수 있지만 비용은 거의 들지 않는다.

**SQLite 라서 머신은 1대로 유지해야 한다.** 여러 대로 늘리면 DB 파일이 갈라진다.

```bash
fly scale count 1
```

### 백업

```bash
fly ssh console -C "sqlite3 /data/sleep.db .dump" > backup.sql   # 덤프
fly ssh sftp get /data/sleep.db ./sleep.db                        # 파일 통째로
```

## Railway / Render

둘 다 이 저장소의 `Dockerfile` 을 그대로 쓴다.

1. 새 프로젝트 → GitHub 저장소 연결 → Dockerfile 자동 인식
2. 환경변수 `ADMIN_TOKEN`, `INGEST_API_KEY` 추가
3. **영구 디스크(볼륨)를 `/data` 에 붙인다** — 안 붙이면 재배포마다 데이터가 사라진다
   (Render 무료 플랜은 디스크를 붙일 수 없으므로 유료 플랜이나 Fly.io 를 쓴다)

## 배포 후 설정

**앱**: 첫 화면 서버 주소를 `https://<앱이름>.fly.dev` 로 입력한다.
기본값을 바꾸려면 `mobile/app.json` 의 `extra.defaultServerUrl` 을 수정한다.
HTTPS 로만 접속한다면 `mobile/app.json` 의 `usesCleartextTraffic` 설정은 지워도 된다.

**브리지**(측정하는 밤에 PC 에서):

```powershell
python serial_csv_logger.py --port COM5 `
  --server https://<앱이름>.fly.dev --api-key 발급한_INGEST_API_KEY
```

## 로컬 개발은 그대로

`python server/run.py` 는 로컬 전용이라 기본 토큰을 허용한다(`SLEEP_ALLOW_DEV_TOKENS=1` 자동).
