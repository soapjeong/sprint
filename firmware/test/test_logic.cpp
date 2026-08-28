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
  g_sensorsActive = true;
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
  check("start 전: 센서 정지", !g_sensorsActive && g_mpuAsleep && g_maxShutdown);
  check("start 전: 히터 NTC 측정 안 함(NaN)", isnan(readHeaterTempC()));

  lastControlMs = g_fakeMillis; lastLogMs = g_fakeMillis;
  startSession();
  check("start 직후: WARMUP 상태", sessionState == SESS_WARMUP);
  check("start 직후: 전 센서 측정 시작", g_sensorsActive && !g_maxShutdown && !g_mpuAsleep);
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
  check("입면 확정: 세션 OFF", sessionState == SESS_OFF);
  check("입면 확정: 히터 정지", SETPOINT_C == 0 && g_lastDuty == 0);
  check("입면 확정: 전 센서 정지", !g_sensorsActive && g_mpuAsleep && g_maxShutdown);
  check("입면 확정: 기기 전원 종료(딥슬립)", g_deepSleepCalled);

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
  check("60분 미입면: 전 센서 정지", !g_sensorsActive && g_mpuAsleep && g_maxShutdown);
  check("60분 미입면: 기기 전원 종료(딥슬립)", g_deepSleepCalled);
  check("60분 미입면: SOL 60분으로 기록",
        g_profile.nBins == 1 && fabsf(binMean(&g_profile.bins[0]) - 60.0f) < 0.01f);

  printf("\n%s (실패 %d건)\n", fails ? "일부 실패" : "모든 검증 통과", fails);
  return fails ? 1 : 0;
}
