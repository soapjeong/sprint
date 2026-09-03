// 하드웨어 없이 스케치 로직만 검증하는 호스트 테스트. firmware/test/run_tests.sh 로 실행.
#include <Arduino.h>
#include <cstdio>

extern unsigned long g_fakeMillis;
extern bool g_deepSleepCalled;
extern bool g_verbose;
extern int  g_lastDuty;
extern bool g_forceBeat;
extern bool g_mpuAsleep;
extern bool g_maxShutdown;
extern bool g_mlxAsleep;

#include "sketch_under_test.inc"   // run_tests.sh 가 build/ 에 생성 (setup/loop 이름만 변경)

static int fails = 0;
static void check(const char* what, bool ok) {
  printf("%-56s %s\n", what, ok ? "PASS" : "FAIL");
  if (!ok) fails++;
}

// ---- 1초 제어주기만 흉내내는 헬퍼(안전 로직 단독 검증용) ----
static SafetyState step(float skin, float heater) {
  g_fakeMillis += CONTROL_PERIOD_MS;
  safetyState = evaluateSafety(skin, heater, lastLoggedSkinC, lastLoggedHeaterC, safetyState, g_fakeMillis);
  lastLoggedSkinC = skin; lastLoggedHeaterC = heater;
  return safetyState;
}

static void resetSafety() {
  safetyState = STATE_NORMAL;
  lastLoggedSkinC = NAN; lastLoggedHeaterC = NAN;
  clearFaultPending();
}

// ---- 실제 loop() 를 1초 진행시킨다 ----
static void stepLoop() {
  g_fakeMillis += CONTROL_PERIOD_MS;
  sketch_loop();
}

int main() {
  // =====================================================================
  // [변경 3] 이상 온도가 5초 이상 지속될 때만 FAULT
  // =====================================================================
  g_tempSensorsActive = true;
  resetSafety();
  step(35.0f, 35.0f);
  for (int i = 0; i < 5; i++) step(43.0f, 35.0f);            // 감지 후 4초 경과까지
  check("과열 4초 경과: 아직 FAULT 아님", safetyState == STATE_NORMAL);
  check("과열 감시 중: 히터는 예방 차단됨", g_preFaultCutoff == true);
  step(43.0f, 35.0f);                                        // 감지 후 5초 경과
  check("과열 5초 경과: FAULT_OVERTEMP_SKIN 래치", safetyState == STATE_FAULT_OVERTEMP_SKIN);

  resetSafety();
  step(35.0f, 35.0f);
  for (int i = 0; i < 3; i++) step(43.0f, 35.0f);            // 3초만 과열
  step(35.0f, 35.0f);
  check("과열 3초 후 복귀: FAULT 아님", safetyState == STATE_NORMAL);
  check("복귀 후 예방 차단 해제", g_preFaultCutoff == false);

  resetSafety();
  step(35.0f, 35.0f);
  step(38.0f, 35.0f);                                        // 1초 내 +3.0C 스파이크
  step(35.1f, 35.0f);                                        // 곧바로 원복
  check("스파이크 후 원복: 노이즈로 보고 FAULT 아님", safetyState == STATE_NORMAL);
  resetSafety();
  step(35.0f, 35.0f);
  for (int i = 0; i < 6; i++) step(38.0f + 0.01f*i, 35.0f);  // 고온 유지
  check("스파이크 5초 유지: FAULT_SPIKE_SKIN 래치", safetyState == STATE_FAULT_SPIKE_SKIN);

  resetSafety();
  for (int i = 0; i < 6; i++) step(NAN, 35.0f);
  check("센서 이상 5초 유지: FAULT_SENSOR", safetyState == STATE_FAULT_SENSOR);

  // =====================================================================
  // [변경 4] start 전 센서 정지 / start 후 20초 워밍업(데이터 폐기·히터 OFF)
  // =====================================================================
  resetSafety();
  g_mlxOk = true; g_maxOk = true; g_mpuOk = true;
  setSensorsActive(false);
  sessionState = SESS_IDLE;
  g_fakeMillis = 100000;
  check("start 전: 센서 정지",
        !g_bioSensorsActive && !g_tempSensorsActive && g_mpuAsleep && g_maxShutdown);
  check("start 전: 히터 NTC 측정 안 함(NaN)", isnan(readHeaterTempC()));

  lastControlMs = g_fakeMillis; lastLogMs = g_fakeMillis;
  startSession();
  check("start 직후: WARMUP 상태", sessionState == SESS_WARMUP);
  check("start 직후: 전 센서 측정 시작",
        g_bioSensorsActive && g_tempSensorsActive && !g_maxShutdown && !g_mpuAsleep);
  check("워밍업 중: 온도 측정은 수행", !isnan(readHeaterTempC()));

  // 워밍업 19초: 심박이 들어와도 버리고, 히터는 계속 꺼져 있어야 한다
  g_forceBeat = true;
  bool heaterOffDuringWarmup = true;
  for (int i = 0; i < 19; i++) {
    stepLoop();
    if (g_lastDuty != 0) heaterOffDuringWarmup = false;
  }
  check("워밍업 중: 히터 출력 0 유지", heaterOffDuringWarmup);
  check("워밍업 중: 심박 데이터 폐기", calibBpmCount == 0 && epochHrCount == 0);
  check("워밍업 중: 안전 판정 보류(직전값 없음)", isnan(lastLoggedSkinC));
  check("워밍업 19초: 아직 WARMUP", sessionState == SESS_WARMUP);

  stepLoop();                                   // 20초 경과
  check("워밍업 20초: RUNNING 전환", sessionState == SESS_RUNNING);
  check("워밍업 종료: 안정심박수 수집 시작", calibState == CAL_COLLECT);

  stepLoop();                                   // 가온 시작 (피부 30C < 목표)
  check("워밍업 종료 후: 히터 가동", g_lastDuty > 0);

  // =====================================================================
  // [변경 1] 워밍업 후 30초 평균 = 안정심박수, 기준 = 안정심박수 - 10
  // =====================================================================
  for (int i = 0; i < 28; i++) stepLoop();      // 1초에 1비트 = 60 BPM
  check("30초 수집 중: 아직 확정 전", calibState == CAL_COLLECT);
  stepLoop();
  check("30초 후: 안정심박수 확정", calibState == CAL_READY);
  check("안정심박수 = 60 BPM", fabsf(g_restingBpm - 60.0f) < 0.5f);
  check("입면 기준 = 안정심박수 - 10", fabsf(g_onsetHrThreshold - (g_restingBpm - 10.0f)) < 0.01f);
  g_forceBeat = false;

  // =====================================================================
  // [변경 1+5] 20분 유지 시 입면 확정 -> 히터·센서 정지 후 기기 종료
  // =====================================================================
  g_deepSleepCalled = false;
  for (int e = 0; e < 19; e++) {
    epochMotionAccum = 1.0f;
    epochHrCount = 60; epochHrSum = 48.0 * 60; epochHrAbove = 1;
    g_fakeMillis += EPOCH_DURATION_MS;
    evaluateEpochAndOnset(g_fakeMillis);
  }
  check("19분 유지: 아직 입면 아님", !isAsleepConfirmed && continuousQuietEpochs == 19);

  epochMotionAccum = 50.0f;                     // 뒤척임 -> 카운터 리셋
  epochHrCount = 60; epochHrSum = 48.0 * 60; epochHrAbove = 0;
  g_fakeMillis += EPOCH_DURATION_MS;
  evaluateEpochAndOnset(g_fakeMillis);
  check("움직임 발생: 연속 카운터 리셋", continuousQuietEpochs == 0 && !isAsleepConfirmed);

  epochMotionAccum = 0.5f;                      // 심박이 기준 위 -> 카운터 리셋
  epochHrCount = 60; epochHrSum = 58.0 * 60; epochHrAbove = 40;
  g_fakeMillis += EPOCH_DURATION_MS;
  evaluateEpochAndOnset(g_fakeMillis);
  check("심박 기준 초과: 입면 아님", continuousQuietEpochs == 0 && !isAsleepConfirmed);

  for (int e = 0; e < 20; e++) {
    epochMotionAccum = 1.0f;
    epochHrCount = 60; epochHrSum = 45.0 * 60; epochHrAbove = 1;
    g_fakeMillis += EPOCH_DURATION_MS;
    evaluateEpochAndOnset(g_fakeMillis);
  }
  check("20분 연속 유지: 입면 확정", isAsleepConfirmed);
  check("입면 확정: COOLDOWN(가온 유지) 진입", sessionState == SESS_COOLDOWN);
  check("입면 확정: 생체 센서 즉시 정지", !g_bioSensorsActive && g_mpuAsleep && g_maxShutdown);
  check("입면 확정: 온도 센서는 유지(PID/과열 감시)", g_tempSensorsActive);
  check("입면 확정: 목표 온도 유지", fabsf(SETPOINT_C - sessionTemp) < 0.01f);
  check("입면 확정 직후: 아직 종료되지 않음", !g_deepSleepCalled);

  // 가온 유지 10분: 히터가 계속 동작해야 한다
  lastControlMs = g_fakeMillis; lastLogMs = g_fakeMillis;
  bool heaterRanDuringCooldown = false;
  for (unsigned long t = 0; t < HEATING_DURATION_MS - 2000; t += CONTROL_PERIOD_MS) {
    stepLoop();
    if (g_lastDuty > 0) heaterRanDuringCooldown = true;
  }
  check("가온 유지 중: 히터 동작", heaterRanDuringCooldown && sessionState == SESS_COOLDOWN);
  check("가온 유지 중: 생체 센서는 계속 정지", !g_bioSensorsActive);

  stepLoop(); stepLoop();                       // 10분 경과
  check("가온 10분 종료: 세션 OFF", sessionState == SESS_OFF);
  check("가온 10분 종료: 히터 정지", SETPOINT_C == 0 && g_lastDuty == 0);
  check("가온 10분 종료: 온도 센서까지 정지", !g_tempSensorsActive);
  check("가온 10분 종료: 기기 전원 종료(딥슬립)", g_deepSleepCalled);

  // =====================================================================
  // [변경 2+5] 60분 미입면 -> 히터·센서 정지 후 기기 종료
  // =====================================================================
  resetSafety();
  g_deepSleepCalled = false;
  profileClear(&g_profile);
  sessionState = SESS_IDLE;
  g_fakeMillis = 5000000;
  startSession();
  g_fakeMillis += SESSION_MAX_MS - 1000;
  updateSession(g_fakeMillis);
  check("59분 59초: 아직 세션 진행 중", sessionState == SESS_RUNNING);
  g_fakeMillis += 1000;
  updateSession(g_fakeMillis);
  check("60분 미입면: 세션 OFF", sessionState == SESS_OFF);
  check("60분 미입면: 전 센서 정지",
        !g_bioSensorsActive && !g_tempSensorsActive && g_mpuAsleep && g_maxShutdown);
  check("60분 미입면: 기기 전원 종료(딥슬립)", g_deepSleepCalled);
  check("60분 미입면: SOL 60분으로 기록",
        g_profile.nBins == 1 && fabsf(binMean(&g_profile.bins[0]) - 60.0f) < 0.01f);

  // =====================================================================
  // [변경 7] 기기 ID 는 칩 MAC(efuse)에서 만들어진다
  // =====================================================================
  buildDeviceId();
  check("기기 ID = MAC 기반 DORMX-24 6F 28 AA BB CC",
        strcmp(g_deviceId, "DORMX-246F28AABBCC") == 0);

  // =====================================================================
  // 미입면 원인 집계 — 관리자 화면에 "왜 못 잤는지"를 남긴다
  // =====================================================================
  calibState = CAL_READY;
  epochsBlockedHr = epochsBlockedMotion = epochsBlockedSensor = 0;
  epochsBlockedHr = 12; epochsBlockedMotion = 3;
  check("심박이 주로 막았으면 원인=심박", noOnsetReason() == NO_ONSET_REASON_HR);
  epochsBlockedMotion = 20;
  check("움직임이 더 많았으면 원인=움직임", noOnsetReason() == NO_ONSET_REASON_MOTION);
  epochsBlockedSensor = 40;
  check("심박 샘플이 계속 부족했으면 원인=센서", noOnsetReason() == NO_ONSET_REASON_SENSOR);
  epochsBlockedHr = epochsBlockedMotion = epochsBlockedSensor = 0;
  check("막힌 적이 없으면 원인=알 수 없음", noOnsetReason() == NO_ONSET_REASON_UNKNOWN);
  calibState = CAL_FAILED;
  check("안정심박수를 못 잡았으면 원인=센서", noOnsetReason() == NO_ONSET_REASON_SENSOR);

  printf("\n%s (실패 %d건)\n", fails ? "일부 실패" : "모든 검증 통과", fails);
  return fails ? 1 : 0;
}
