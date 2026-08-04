# 수면 온도 최적화기 — IoT 헬스케어 백엔드 리팩터링

ESP32 기반 개인 맞춤 입면(수면 개시) 온도 탐색기의 PC측 소프트웨어입니다. 시리얼 포트를
백엔드 서버 하나가 단독으로 소유하면서, 그 위에 REST/WebSocket을 얹어 **폰에서 실시간으로
조종**할 수 있게 리팩터링했습니다.

## 구조

```
backend/                 FastAPI 백엔드 — 시리얼 연결을 단독으로 소유
  connection.py             DeviceConnection 인터페이스 + SerialDeviceConnection 구현
  mock_connection.py        DeviceConnection의 하드웨어 없는 테스트용 구현 (--mock)
  parsing.py                "[진행상태]" / "@RESULT" 원문 파싱
  log_writer.py             CSV/이벤트 로그 파일 기록 (기존 파일 포맷 그대로)
  state.py                  서버 프로세스 내 공유 상태 + WebSocket 브로드캐스트
  main.py                   REST API, WebSocket, 정적 파일(폰 페이지) 서빙
run.py                   백엔드 실행 스크립트 (CLI 옵션)
phone/index.html         폰 전용 경량 컨트롤 페이지 (반응형, 바닐라 HTML/JS, 빌드 불필요)
phone/simulator.html     ESP32 없이 값을 직접 주입해서 테스트하는 시뮬레이터 페이지
realtime_dashboard.py    기존 Streamlit 대시보드 (읽기 전용, PC용 상세 분석)
logs/                     센서 CSV / 이벤트 로그 저장 폴더 (백엔드가 기록)
sleep_onset_temp_optimizer_v3_real_hw.ino   ESP32 펌웨어 (프로토콜 변경 없음)
```

기존에 `serial_csv_logger.py`가 시리얼 포트를 독점하고 있어서 컨트롤러를 따로 만들 수
없었던 문제를, "시리얼을 소유하는 유일한 프로세스 = 백엔드"로 만들어 해결했습니다.
Streamlit과 폰 페이지는 모두 이 백엔드만 바라봅니다(Streamlit은 로그 파일을, 폰 페이지는
REST+WebSocket을 통해).

## 실행 순서

### 1. 패키지 설치

```bash
pip install -r requirements.txt
```

### 2. 백엔드 실행 (ESP32가 USB로 연결되어 있어야 함)

```bash
python run.py
# 시리얼 포트를 자동으로 못 찾으면:
python run.py --serial-port /dev/ttyUSB0     # macOS/Linux
python run.py --serial-port COM5             # Windows
```

시작하면 콘솔에 아래처럼 출력됩니다. `[연결됨]`이 뜨면 ESP32와 정상 연결된 것이고,
안 뜨면 2초마다 자동 재시도합니다(펌웨어를 나중에 켜도 됩니다).

```
[백엔드] 센서 CSV : ./logs/sensor_20260101_120000.csv
[백엔드] 이벤트 로그: ./logs/events_20260101_120000.log
[연결됨] /dev/ttyUSB0 @ 115200bps
[백엔드] 폰 컨트롤 페이지: http://192.168.0.23:8000/
```

**이 `http://<LAN IP>:8000/` 이 폰에서 접속할 URL입니다.** 콘솔 출력 외에도, 백엔드가
켜져 있는 동안 브라우저에서 `http://<PC의 LAN IP>:8000/api/network` 를 열면 언제든 다시
확인할 수 있습니다. 폰과 PC/라즈베리파이가 같은 Wi-Fi에 있어야 합니다.

### 3. 폰에서 조종

폰 브라우저로 위 URL(`http://<LAN IP>:8000/`)에 접속하면 바로 컨트롤 페이지가 뜹니다.
별도 서버를 띄울 필요 없이 백엔드가 정적 파일까지 서빙합니다.

### 4. ESP32가 아직 없거나 연결이 안 될 때 — Mock 모드

하드웨어 없이도 백엔드/폰 페이지를 전부 테스트할 수 있습니다.

```bash
python run.py --mock
```

이 경우 시리얼 대신 `http://<LAN IP>:8000/simulator.html` 에서 슬라이더로 값을 직접
주입할 수 있습니다. 주입한 값은 실제 ESP32가 보낸 것과 동일한 경로(파싱 → CSV/이벤트
로깅 → WebSocket 브로드캐스트)를 그대로 타므로, `index.html`(실제 컨트롤 화면)을 다른
탭/폰에서 열어두면 시뮬레이터에서 값을 바꿀 때마다 그대로 반영되는 걸 볼 수 있습니다.
"FAULT 발생" 같은 프리셋 버튼으로 안전 경고 화면도 하드웨어 없이 테스트할 수 있습니다.

### 5. (선택) PC에서 상세 분석 대시보드

```bash
streamlit run realtime_dashboard.py
```

사이드바의 "로그 폴더 경로"는 기본값(`./logs`)이 백엔드와 동일하므로 보통 그대로 두면
됩니다. 상단의 "📱 폰 컨트롤 페이지 열기" 버튼은 백엔드의 `/api/network`를 조회해서
자동으로 LAN URL을 채워줍니다(백엔드 주소는 사이드바에서 변경 가능, 기본 `http://localhost:8000`).

## 안전상태(FAULT) 발생 시 대처법

폰 화면 상단에 빨간 경고 배너가 뜨고 진동/알림음이 울립니다. FAULT 상태에서는 펌웨어가
히터를 하드컷오프하므로 화상 등 위험은 없지만, 세션은 재시작해야 합니다.

1. 배너에 표시된 원인 확인 (예: `피부 과열 감지`, `히터 온도 급상승 감지`, `센서 오류` 등)
2. 원인이 된 실제 문제(센서 접촉 불량, 히터 필름 위치 등)를 먼저 점검
3. 피부/히터 온도가 재가동 기준(피부 39℃, 히터 42℃) 이하로 떨어질 때까지 대기
4. 폰 화면에 노출되는 "🔓 강제중단 해제(r)" 버튼을 눌러 FAULT 해제
   - 온도가 아직 기준 이상이면 서버가 거부 응답을 돌려주고 토스트로 안내합니다.
5. 필요하면 "▶ 작동 시작"으로 세션을 다시 시작합니다.

FAULT 상태에서 "작동 시작"을 누르면, 실제로 시리얼에 명령을 보내기 전에 백엔드가
마지막으로 수신한 안전상태를 확인해 즉시 거부(HTTP 409)하고 사유를 화면에 표시합니다.

## 펌웨어 프로토콜

`backend/parsing.py`, `backend/main.py`는 펌웨어(`sleep_onset_temp_optimizer_v3_real_hw.ino`)의
시리얼 프로토콜을 그대로 따릅니다(변경 없음): baud 115200, 명령 `id <name>` / `start` /
`abort` / `set <c>` / `report` / `reset_profile` / `r`, 상태 로그 `[진행상태] ...`,
결과 이벤트 `@RESULT,...`. 온도 탐색 범위(`SEARCH_MIN`~`SEARCH_MAX`, 37.5~40.5℃)는
백엔드와 폰 UI에서 이중으로 제한합니다.

CSV/이벤트 로그의 `시간(초)` 컬럼은 펌웨어 원본 그대로(ESP32 부팅 이후 경과시간, `millis()`
기준)이며 건드리지 않았습니다. 다만 세션 상대 경과시간(60분 자동 종료 카운트다운 등)은 이
값으로 계산하면 부팅 시점에 따라 틀어지므로, 백엔드가 세션이 실제로 시작된 시각을 별도로
기억해 `session_elapsed_sec`(WebSocket/`/api/status` 응답에만 존재, CSV에는 없음)를 계산해서
내려줍니다.

## 센서 노이즈 / 안정화 구간 처리

폰 컨트롤 페이지의 실시간 그래프는 두 가지를 적용합니다 (모두 화면 표시 전용이며, CSV 원본
로그는 손대지 않습니다):

- **센서 안정화 구간 제외**: 세션이 `RUNNING`/`COOLDOWN`으로 바뀐 직후 10초(`STABILIZE_SEC`)
  동안은 그래프에 데이터를 찍지 않습니다. 큰 숫자 카드(피부온도 등)는 이 구간에도 그대로
  실시간으로 보여줍니다.
- **이상치(노이즈) 필터**: 피부온도 값에 중앙값(median-of-3) 필터를 적용해 튀는 값 하나가
  그래프에 뾰족한 스파이크로 나타나지 않게 합니다. 안전 판정(FAULT)에 쓰이는 원본 값이나
  CSV 로그에는 영향을 주지 않습니다 — 펌웨어의 급상승 감지(`SPIKE_JUMP_C`)는 이 필터와
  무관하게 원본 값으로 그대로 동작합니다.

## 향후 확장

`backend/connection.py`의 `DeviceConnection`은 인터페이스로 분리되어 있어서, 지금의
`SerialDeviceConnection`을 나중에 `WiFiDeviceConnection`이나 `BLEDeviceConnection`으로
바꿔도 `main.py` 이하 REST/WebSocket/로깅 로직은 그대로 재사용할 수 있습니다(생성자에서
`state.device = ...` 한 줄만 교체).
