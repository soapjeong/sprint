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
| `server/` | FastAPI + SQLite 백엔드 (사용자·기기 등록, 세션 DB, 관리자 조회) |
| `mobile/` | Expo(React Native) 앱 — 사용자 페이지 / 관리자 페이지 |
| `streamlit_app.py` | 초기 연구용 대시보드(레거시) |
| `tests/`, `server/tests/` | 브리지 파싱 · API 통합 테스트 |

## 빠른 시작

```bash
# 1) 백엔드
pip install -r server/requirements.txt
ADMIN_TOKEN=my-admin INGEST_API_KEY=my-key \
  uvicorn server.app.main:app --host 0.0.0.0 --port 8000

# 2) 앱 (첫 화면에서 서버 주소 + 사용자 ID + 기기 등록)
cd mobile && npm install && npx expo start

# 3) 기기 연결 (앱에서 등록한 기기 ID 를 --device 에 그대로)
python serial_csv_logger.py --port /dev/ttyUSB0 \
  --server http://192.168.0.10:8000 --api-key my-key --device DORMX-001
```

하드웨어 없이 파이프라인만 확인하려면:

```bash
python serial_csv_logger.py --replay tests/data/sample_serial.log \
  --server http://127.0.0.1:8000 --api-key my-key --device DORMX-001
```

## 검사

```bash
python -m pytest tests server/tests -q   # 브리지 + API
firmware/test/run_tests.sh               # 펌웨어 로직 (하드웨어 불필요)
cd mobile && npm run typecheck           # 앱 타입 검사
```

자세한 내용은 `firmware/README.md`, `server/README.md`, `mobile/README.md` 참고.
