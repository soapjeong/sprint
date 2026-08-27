#include <Arduino.h>
#include <cstdio>
#include <cassert>

extern unsigned long g_fakeMillis;
extern bool g_deepSleepCalled;
extern bool g_verbose;

#include "sketch_under_test.inc"   // run_tests.sh 가 build/ 에 생성

static int fails = 0;
static void check(const char* what, bool ok) {
  printf("%-58s %s\n", what, ok ? "PASS" : "FAIL");
  if (!ok) fails++;
}

// 1초 제어주기 시뮬레이션
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

int main() {
  // ---------- [변경 3] 이상 온도 5초 지속 시에만 FAULT ----------
  resetSafety();
  step(35.0f, 35.0f);
  for (int i = 0; i < 5; i++) step(43.0f, 35.0f);           // 감지 후 4초 경과 시점까지
  check("과열 4초 경과: 아직 FAULT 아님", safetyState == STATE_NORMAL);
  check("과열 감시 중: 히터는 예방 차단됨", g_preFaultCutoff == true);
  step(43.0f, 35.0f);                                        // 감지 후 5초 경과
  check("과열 5초 경과: FAULT_OVERTEMP_SKIN 래치", safetyState == STATE_FAULT_OVERTEMP_SKIN);

  resetSafety();
  step(35.0f, 35.0f);
  for (int i = 0; i < 3; i++) step(43.0f, 35.0f);            // 3초만 과열
  step(35.0f, 35.0f);                                        // 정상 복귀
  check("과열 3초 후 복귀: FAULT 아님", safetyState == STATE_NORMAL);
  check("복귀 후 예방 차단 해제", g_preFaultCutoff == false);
  for (int i = 0; i < 10; i++) step(35.0f, 35.0f);
  check("이후 계속 정상 유지", safetyState == STATE_NORMAL);

  resetSafety();
  step(35.0f, 35.0f);
  step(38.0f, 35.0f);                                        // 1초 내 +3.0C 스파이크
  check("스파이크 직후: 아직 FAULT 아님", safetyState == STATE_NORMAL);
  step(35.1f, 35.0f);                                        // 온도 원복 -> 노이즈로 판단
  check("스파이크 후 원복: FAULT 아님", safetyState == STATE_NORMAL);
  resetSafety();
  step(35.0f, 35.0f);
  for (int i = 0; i < 6; i++) step(38.0f + 0.01f*i, 35.0f);  // 스파이크 후 고온 유지
  check("스파이크 5초 유지: FAULT_SPIKE_SKIN 래치", safetyState == STATE_FAULT_SPIKE_SKIN);

  resetSafety();
  for (int i = 0; i < 6; i++) step(NAN, 35.0f);
  check("센서 이상 5초 유지: FAULT_SENSOR", safetyState == STATE_FAULT_SENSOR);

  // ---------- [변경 1] 안정심박수 캘리브레이션 ----------
  resetSafety();
  g_maxOk = true; g_mpuOk = true;
  g_fakeMillis = 100000;
  startSession();
  check("start 직후 20초 폐기 구간", calibState == CAL_DISCARD);

  // 폐기 구간 동안 들어온 비트는 저장되지 않아야 한다
  for (int i = 0; i < 20; i++) { latestBpm = 90; calibBpmSum += 0; }
  g_fakeMillis += 19000; updateCalibration(g_fakeMillis);
  check("19초 시점: 여전히 폐기 구간", calibState == CAL_DISCARD);
  g_fakeMillis += 1000;  updateCalibration(g_fakeMillis);
  check("20초 경과: 수집 구간 진입", calibState == CAL_COLLECT);
  check("폐기 구간 데이터는 버려짐", calibBpmCount == 0);

  // 30초 수집: 평균 70 BPM
  for (int i = 0; i < 30; i++) { calibBpmSum += 70.0; calibBpmCount++; }
  g_fakeMillis += 30000; updateCalibration(g_fakeMillis);
  check("30초 후 안정심박수 확정", calibState == CAL_READY);
  check("안정심박수 = 70 BPM", fabsf(g_restingBpm - 70.0f) < 0.01f);
  check("입면 기준 = 안정심박수 - 10", fabsf(g_onsetHrThreshold - 60.0f) < 0.01f);

  // ---------- [변경 1] 입면 판정: 기준 이하 + 무동작 20분 ----------
  // 19에폭 조용 -> 아직 입면 아님
  for (int e = 0; e < 19; e++) {
    epochMotionAccum = 1.0f;
    epochHrCount = 60; epochHrSum = 58.0 * 60; epochHrAbove = 2;
    g_fakeMillis += EPOCH_DURATION_MS;
    evaluateEpochAndOnset(g_fakeMillis);
  }
  check("19분 유지: 아직 입면 아님", !isAsleepConfirmed && continuousQuietEpochs == 19);

  // 심박은 낮지만 몸을 뒤척인 에폭 -> 카운터 리셋
  epochMotionAccum = 50.0f;
  epochHrCount = 60; epochHrSum = 58.0 * 60; epochHrAbove = 0;
  g_fakeMillis += EPOCH_DURATION_MS;
  evaluateEpochAndOnset(g_fakeMillis);
  check("움직임 발생: 연속 카운터 리셋", continuousQuietEpochs == 0 && !isAsleepConfirmed);

  // 움직임은 없지만 심박이 기준 위 -> 카운터 리셋 유지
  epochMotionAccum = 0.5f;
  epochHrCount = 60; epochHrSum = 65.0 * 60; epochHrAbove = 40;
  g_fakeMillis += EPOCH_DURATION_MS;
  evaluateEpochAndOnset(g_fakeMillis);
  check("심박 기준 초과: 입면 아님", continuousQuietEpochs == 0 && !isAsleepConfirmed);

  // 20에폭 연속 조용 -> 입면 확정
  for (int e = 0; e < 20; e++) {
    epochMotionAccum = 1.0f;
    epochHrCount = 60; epochHrSum = 55.0 * 60; epochHrAbove = 1;
    g_fakeMillis += EPOCH_DURATION_MS;
    evaluateEpochAndOnset(g_fakeMillis);
  }
  check("20분 연속 유지: 입면 확정", isAsleepConfirmed);
  check("입면 확정 후 COOLDOWN 진입", sessionState == SESS_COOLDOWN);

  // ---------- [변경 2] 60분 미입면 -> 기기 종료 ----------
  resetSafety();
  g_deepSleepCalled = false;
  profileClear(&g_profile);
  g_fakeMillis = 500000;
  startSession();
  g_fakeMillis += SESSION_MAX_MS - 1000;
  updateSession(g_fakeMillis);
  check("59분 59초: 아직 세션 진행 중", sessionState == SESS_RUNNING);
  g_fakeMillis += 1000;
  updateSession(g_fakeMillis);
  check("60분 미입면: 세션 OFF", sessionState == SESS_OFF);
  check("60분 미입면: 딥슬립 진입(전원 종료)", g_deepSleepCalled);
  check("60분 미입면: 목표온도 0으로 해제", SETPOINT_C == 0);
  check("60분 미입면: SOL 60분으로 기록", g_profile.nBins == 1 && fabsf(binMean(&g_profile.bins[0]) - 60.0f) < 0.01f);

  printf("\n%s (실패 %d건)\n", fails ? "일부 실패" : "모든 검증 통과", fails);
  return fails ? 1 : 0;
}
