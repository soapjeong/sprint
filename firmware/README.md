# ESP32 입면 온도 탐색기 펌웨어 (v4)

`sleep_temp_optimizer/sleep_temp_optimizer.ino` — MLX90614(피부온도) 기반 PID 가온 +
MPU6050/MAX30102 기반 입면(SOL) 추정 + 세션별 최적 온도 탐색.

## v3 → v4 변경 요약

### 1. 안정심박수 자동 캘리브레이션 후 입면 판정
| 구간 | 시간 | 동작 |
|------|------|------|
| `CAL_DISCARD` | start 후 0~20초 | 심박 데이터를 노이즈로 간주하고 **폐기** |
| `CAL_COLLECT` | 20~50초 | 30초간 평균을 내어 **이번 세션의 안정심박수**로 저장 |
| `CAL_READY` | 이후 | 입면 기준 = `안정심박수 - 10 BPM` 으로 판정 시작 |

- 입면 조건: 심박이 기준값 이하 **20분 연속 유지** + 같은 구간에 **움직임 없음**.
  (1분 에폭 단위로 평균 심박·누적 움직임을 판정하고, 20에폭 연속 만족 시 확정)
- 확정 시 호스트(서버)로 상태 플래그 전송: `@FLAG,<person>,SLEEP_ONSET,<millis>,<SOL분>,<안정심박>`
- 30초 동안 유효 비트를 못 얻으면 최대 3회 재측정하고, 그래도 실패하면 기본값(60 BPM)으로
  낮춘 뒤 움직임 위주로 판정한다(`@FLAG,...,HR_BASELINE_FALLBACK,...`).

### 2. 60분 미입면 시 기기 전원 종료
`SESSION_MAX_MS`(60분) 안에 입면이 확정되지 않으면 SOL을 60분으로 기록·저장하고
`@FLAG,...,NO_ONSET` / `@FLAG,...,POWER_OFF` 전송 후 히터를 끄고 딥슬립으로 들어간다.
시작 버튼(GPIO32)을 누르면 다시 깨어난다. 딥슬립 대신 대기만 하려면
`POWER_OFF_USE_DEEP_SLEEP` 을 `0` 으로 바꾼다.

### 3. 이상 온도는 5초 이상 지속될 때만 FAULT
- 과열/급상승/센서 이상이 감지되면 **히터 출력은 즉시 0**으로 끊되(`g_preFaultCutoff`),
  FAULT 래치는 같은 이상 상태가 `FAULT_PERSIST_MS`(5초) 이상 연속될 때만 한다.
- 5초 안에 정상으로 돌아오면 순간 노이즈로 보고 FAULT 없이 가온을 재개한다.
- 급상승(spike)은 감지 시점 온도를 기준으로, 온도가 0.5℃ 이상 내려올 때까지 이상 상태로 본다.

## 호스트로 보내는 상태 플래그

```
@FLAG,<person>,<flag>,<millis>,<v1>,<v2>
```
`SESSION_START` / `HR_BASELINE` / `HR_BASELINE_FALLBACK` / `SLEEP_ONSET` /
`NO_ONSET` / `SESSION_DONE` / `FAULT` / `POWER_OFF`

`serial_csv_logger.py` 가 `@` 로 시작하는 줄을 이벤트 로그(`logs/events_*.log`)에 기록한다.

## 로직 테스트 (하드웨어 불필요)

```
firmware/test/run_tests.sh
```
Arduino 라이브러리 스텁으로 스케치를 그대로 컴파일해 안전 판정·캘리브레이션·입면 판정·
세션 종료 로직을 검증한다.
