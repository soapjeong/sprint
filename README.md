# DormX — 개인 맞춤 입면 온도 최적화 시스템

수면 시작(입면) 시점을 감지해 개인별로 가장 잘 맞는 가온 온도를 찾아가는 시스템.
ESP32 기기, PC 브리지, 백엔드, 모바일 앱으로 구성된다.

```
[ESP32 기기]  --USB 시리얼-->  [PC 브리지]  --HTTP-->  [FastAPI + SQLite]
 가온 PID/안전                  로그 저장·업로드           │
 입면 판정                                                 ├── 사용자 페이지 (모바일 앱)
                                                           └── 관리자 페이지 (모바일 앱)
```

| 폴더 | 내용 |
|------|------|
| `firmware/` | ESP32 펌웨어 (PID 가온, 안전 감시, 안정심박수 기준 입면 판정) + 하드웨어 없이 도는 로직 테스트 |
| `serial_csv_logger.py` | PC 브리지 — 시리얼 로그를 CSV 로 저장하고 서버로 업로드 |
| `server/` | FastAPI 백엔드 — 로그인, 기기 등록, 세션 DB, 관리자 조회 (로컬 SQLite / 배포 PostgreSQL) |
| `mobile/` | Expo(React Native) 앱 — 사용자 페이지 / 관리자 페이지 |
| `streamlit_app.py` | 초기 연구용 대시보드(레거시) |
| `tests/`, `server/tests/` | 브리지 파싱 · API 통합 테스트 |

## 빠른 시작

```bash
# 1) 백엔드 (레포 루트에서)
pip install -r server/requirements.txt
python server/run.py        # 앱에 입력할 서버 주소와 토큰을 출력해 준다

# 2) 앱 (첫 화면에서 서버 주소 + 사용자 ID + 기기 등록)
cd mobile && npm install && npm run web    # 브라우저 미리보기 (폰으로 보려면 mobile/README.md)

# 3) 기기 연결 — 기기 ID 는 칩 MAC 에서 자동 인식된다(--device 불필요)
python serial_csv_logger.py --port /dev/ttyUSB0 \
  --server http://192.168.0.10:8000 --api-key my-key
```

하드웨어 없이 파이프라인만 확인하려면:

```bash
python serial_csv_logger.py --replay tests/data/sample_serial.log \
  --server http://127.0.0.1:8000 --api-key my-key
```

## 검사

```bash
python -m pytest tests server/tests -q   # 브리지 + API
firmware/test/run_tests.sh               # 펌웨어 로직 (하드웨어 불필요)
cd mobile && npm run typecheck           # 앱 타입 검사
```

## 서버를 무료로 올려두기

PC 를 켜두지 않아도 앱이 돌게 하려면 `server/DEPLOY.md` 참고 —
Render(웹, 무료) + Neon(PostgreSQL, 무료·기간 제한 없음) 조합이다.
`DATABASE_URL` 이 있으면 PostgreSQL, 없으면 로컬 SQLite 로 동작한다.

자세한 내용은 `firmware/README.md`, `server/README.md`, `server/DEPLOY.md`, `mobile/README.md` 참고.
