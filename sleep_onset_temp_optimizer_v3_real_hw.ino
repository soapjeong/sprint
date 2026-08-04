/*
 * ============================================================================
 *  ESP32 개인 맞춤 입면 온도 탐색기  — 실제 하드웨어 통합 버전 (v3)
 *  (Personalized Sleep-Onset Temperature Optimizer for real ESP32 kit)
 * ============================================================================
 */

#include <Wire.h>
#include <Preferences.h>
#include <math.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_MLX90614.h>
#include "MAX30105.h"
#include "heartRate.h"

// ===========================================================================
//  핀 / 하드웨어 설정
// ===========================================================================
static const int   HEATER_PWM_PIN = 25;   // MOSFET(IRLML2502) 게이트
static const int   NTC_PIN        = 34;   // NTC 서미스터(히터 표면) 아날로그 핀
static const int   START_BTN_PIN  = 32;   // 세션 시작 버튼 (선택, INPUT_PULLUP)

// ------- NTC 전압 분배기 / ADC (히터 표면 온도, 안전감시 전용) -------
static const float V_SUPPLY_MV     = 3300.0f;
static const float SERIES_R        = 10000.0f;
static const int   ADC_SAMPLES     = 16;
#define THERMISTOR_INVERTED 0   // 온도 올렸는데 값이 내려가면 1 <-> 0 전환

// ------- 서미스터 변환 (0=Steinhart-Hart, 1=Beta) -------
#define USE_BETA_EQUATION 0
static const double SH_A = 1.009249522e-03;
static const double SH_B = 2.378405444e-04;
static const double SH_C = 2.019202697e-07;
static const float  BETA        = 3950.0f;
static const float  R0_NOMINAL  = 10000.0f;
static const float  T0_KELVIN   = 298.15f;
static const float  T_SENSE_MIN_C = -40.0f;
static const float  T_SENSE_MAX_C = 150.0f;

// ------- PID (MLX90614 기준 초기값 — 재튜닝 필요) -------
static float Kp = 10.0f, Ki = 0.5f, Kd = 2.0f;
static const float INTEGRAL_WINDUP_LIMIT = 50.0f;

// ------- PWM (ESP32 Core v3.x, ledcAttach 기반) -------
static const int PWM_FREQ_HZ  = 5000;
static const int PWM_RES_BITS = 8;                    // 0~255
static const int PWM_MAX      = (1 << PWM_RES_BITS) - 1;

// ------- 제어 주기 -------
static const unsigned long CONTROL_PERIOD_MS = 1000;  // 1초 (안전감시 spike 판정과 동일 주기)
static const unsigned long LOG_PERIOD_MS     = 1000;

// ===========================================================================
//  안전(Watchdog) — 히터(NTC) / 피부(MLX) 이중 감시
// ===========================================================================
static const float SKIN_HARD_LIMIT_C   = 42.0f;  // 피부 표면 절대 상한
static const float HEATER_HARD_LIMIT_C = 45.0f;  // 히터 필름 절대 상한(피부보다 약간 높게)
static const float SPIKE_JUMP_C        = 2.0f;   // 1제어주기(1초) 내 급상승 한계
static const float SKIN_REARM_C        = 39.0f;  // 재가동 허용 온도(피부)
static const float HEATER_REARM_C      = 42.0f;  // 재가동 허용 온도(히터)

enum SafetyState {
  STATE_NORMAL = 0,
  STATE_FAULT_OVERTEMP_SKIN,
  STATE_FAULT_OVERTEMP_HEATER,
  STATE_FAULT_SPIKE_SKIN,
  STATE_FAULT_SPIKE_HEATER,
  STATE_FAULT_SENSOR
};

// ===========================================================================
//  세션 상태
// ===========================================================================
enum SessionState { SESS_IDLE = 0, SESS_RUNNING, SESS_COOLDOWN, SESS_DONE };

// ===========================================================================
//  입면(Sleep Onset) 추정 — 코드①의 "1분 에폭 누적" 알고리즘
// ===========================================================================
static const unsigned long EPOCH_DURATION_MS   = 60000UL; // 1분 에폭
static const int           REQUIRED_SLEEP_EPOCHS = 5;    // 연속 10에폭(10분) 조용하면 입면 확정 ***********5분으로 고침(잠시)
static const float         MOTION_EPOCH_THRESHOLD = 5.0f; // 에폭 누적 움직임 임계값(가속도 변화합)
static const int           HR_SLEEP_BASELINE_BPM  = 65;   // 에폭 평균 심박이 이 값 이하면 "안정"
static const unsigned long SESSION_MAX_MS = 60UL * 60 * 1000; // 세션 최대(미입면 타임아웃) 60분

// 입면 확정 후에도 이 시간만큼 목표온도로 가온을 유지(코드①의 HEATING_DURATION)
static const unsigned long HEATING_DURATION_MS = 10UL * 60000UL; // 10분(예시, 조정 가능)

// ===========================================================================
//  적응형 온도 탐색 파라미터 (코드②의 개인화 파이프라인)
// ===========================================================================
static const int   MAX_BINS      = 16;
static const float SEARCH_START  = 39.0f;  // 첫 세션 온도(생물학적 목표 38~40°C 중앙값)
static const float SEARCH_MIN    = 37.5f;
static const float SEARCH_MAX    = 40.5f;  // SKIN_HARD_LIMIT(42) 대비 여유 확보
static const float SEARCH_STEP0  = 1.0f;
static const float SEARCH_TOL    = 0.3f;
static const float BIN_WIDTH     = 0.5f;

struct Bin { float temp; float solSumMin; uint16_t count; };
struct Profile {
  uint8_t nBins;
  Bin     bins[MAX_BINS];
  float   lastTemp;
};
struct SearchResult { float nextTemp; bool converged; float bestTemp; float bestSol; };

// ===========================================================================
//  함수 프로토타입
// ===========================================================================
static float heaterVoltageToResistance(float vNodeMv);
static float heaterResistanceToTempC(float rOhm);
static float readHeaterTempC();

static SafetyState evaluateSafety(float skinC, float heaterC,
                                   float lastSkinC, float lastHeaterC,
                                   SafetyState current);
static const char* stateName(SafetyState s);
static const char* sessName(SessionState s);

static float clampSearch(float t);
static float roundToBin(float t);
static int   findBin(const Profile* p, float temp);
static void  recordResult(Profile* p, float temp, float solMin);
static float binMean(const Bin* b);
static bool  parabolaVertex(float x1,float y1,float x2,float y2,float x3,float y3,float* vx);
static float ensureSpacing(const Profile* p, float t);
static SearchResult nextTemperature(const Profile* p);

static void  pwmSetup();
static void  pwmWrite(int duty);
static float computePID(float setpoint, float tempC, float dtSec);
static void  resetPID();

static void  pollMotionAndHR();       // 매 루프: 움직임/심박 누적 (Non-blocking)
static void  evaluateEpochAndOnset(unsigned long now); // 1분마다: 입면 판정

static void  profileClear(Profile* p);
static void  loadProfile(const char* id);
static void  saveProfile(const char* id);
static void  eraseProfile(const char* id);

static void  startSession();
static void  onSleepOnsetConfirmed(unsigned long onsetMs);
static void  finalizeNoOnset();
static void  updateSession(unsigned long now);

static void  printCsvHeader();
static void  logCsv(unsigned long t, float skinC, float heaterC, int duty);
static void  printReport();
static void  handleSerial(float skinC, float heaterC);

// ===========================================================================
//  전역 상태
// ===========================================================================
static SafetyState  safetyState  = STATE_NORMAL;
static SessionState sessionState = SESS_IDLE;

// 센서 객체
static Adafruit_MPU6050  mpu;
static Adafruit_MLX90614 mlx;
static MAX30105          particleSensor;
static bool g_mpuOk = false, g_mlxOk = false, g_maxOk = false;

// PID 내부
static float pidIntegral = 0.0f, lastSkinTempC = NAN;
static bool  pidPrimed = false;
static float dbgP = 0, dbgI = 0, dbgD = 0;

// 안전감시용 직전값
static float lastLoggedSkinC = NAN, lastLoggedHeaterC = NAN;

// ---- 입면 추정(에폭) 상태 ----
static unsigned long lastEpochStartMs = 0;
static float epochMotionAccum = 0.0f;
static float prevAx = 0, prevAy = 0, prevAz = 0;
static long  epochHrSum = 0;
static int   epochHrCount = 0;
static int   continuousQuietEpochs = 0;
static bool  isAsleepConfirmed = false;

// MAX30102 비트 검출용
static long  lastBeatMs = 0;
static float latestBpm = 0;

// ---- 세션 ----
static unsigned long sessionStartMs = 0;
static unsigned long cooldownEndMs  = 0;
static float sessionTemp   = SEARCH_START;
static float SETPOINT_C    = 0;
static bool  manualTempSet = false;

// 타이밍
static unsigned long lastControlMs = 0, lastLogMs = 0;

// 프로파일 / NVS
static Profile     g_profile;
static char        g_personId[16] = "default";
static Preferences prefs;

// ===========================================================================
//  ---- NTC(히터) 온도 변환 : 안전감시 전용 ----
// ===========================================================================
static float heaterVoltageToResistance(float vNodeMv) {
  if (vNodeMv <= 1.0f) return NAN;
  if (vNodeMv >= V_SUPPLY_MV - 1.0f) return NAN;
#if not THERMISTOR_INVERTED
  return SERIES_R * vNodeMv / (V_SUPPLY_MV - vNodeMv);
#else
  return SERIES_R * (V_SUPPLY_MV - vNodeMv) / vNodeMv;
#endif
}

static float heaterResistanceToTempC(float rOhm) {
  if (isnan(rOhm) || rOhm <= 0.0f) return NAN;
#if USE_BETA_EQUATION
  float invT = (1.0f/T0_KELVIN) + (1.0f/BETA) * logf(rOhm / R0_NOMINAL);
  return (1.0f/invT) - 273.15f;
#else
  double lnR = log((double)rOhm);
  double invT = SH_A + SH_B*lnR + SH_C*lnR*lnR*lnR;
  return (float)(1.0/invT - 273.15);
#endif
}

static float readHeaterTempC() {
  uint32_t acc = 0;
  for (int i = 0; i < ADC_SAMPLES; i++) acc += analogReadMilliVolts(NTC_PIN);
  float mv = (float)acc / ADC_SAMPLES;
  return heaterResistanceToTempC(heaterVoltageToResistance(mv));
}

// ===========================================================================
//  ---- 안전 평가 (히터 NTC + 피부 MLX 이중 감시, 래치 유지) ----
// ===========================================================================
static SafetyState evaluateSafety(float skinC, float heaterC,
                                   float lastSkinC, float lastHeaterC,
                                   SafetyState current) {
  // 센서 이상(범위 초과/NaN)
  if (isnan(skinC) || skinC < T_SENSE_MIN_C || skinC > T_SENSE_MAX_C) return STATE_FAULT_SENSOR;
  if (isnan(heaterC) || heaterC < T_SENSE_MIN_C || heaterC > T_SENSE_MAX_C) return STATE_FAULT_SENSOR;

  // 이미 래치된 FAULT는 재가동(REARM) 조건 전까지 유지
  if (current != STATE_NORMAL) return current;

  // 절대 상한
  if (skinC   >= SKIN_HARD_LIMIT_C)   return STATE_FAULT_OVERTEMP_SKIN;
  if (heaterC >= HEATER_HARD_LIMIT_C) return STATE_FAULT_OVERTEMP_HEATER;

  // 1초(CONTROL_PERIOD_MS) 내 급상승 — 열폭주/센서오작동 감지
  if (!isnan(lastSkinC)   && (skinC   - lastSkinC)   >= SPIKE_JUMP_C) return STATE_FAULT_SPIKE_SKIN;
  if (!isnan(lastHeaterC) && (heaterC - lastHeaterC) >= SPIKE_JUMP_C) return STATE_FAULT_SPIKE_HEATER;

  return STATE_NORMAL;
}

static const char* stateName(SafetyState s) {
  switch (s) {
    case STATE_NORMAL: return "NORMAL";
    case STATE_FAULT_OVERTEMP_SKIN: return "FAULT_OVERTEMP_SKIN";
    case STATE_FAULT_OVERTEMP_HEATER: return "FAULT_OVERTEMP_HEATER";
    case STATE_FAULT_SPIKE_SKIN: return "FAULT_SPIKE_SKIN";
    case STATE_FAULT_SPIKE_HEATER: return "FAULT_SPIKE_HEATER";
    case STATE_FAULT_SENSOR: return "FAULT_SENSOR";
    default: return "?";
  }
}
static const char* sessName(SessionState s) {
  switch (s) {
    case SESS_IDLE: return "IDLE";
    case SESS_RUNNING: return "RUNNING";
    case SESS_COOLDOWN: return "COOLDOWN";
    case SESS_DONE: return "DONE";
    default: return "?";
  }
}

// ===========================================================================
//  ---- 개인화 탐색 알고리즘  ----
// ===========================================================================
static float clampSearch(float t) {
  if (t < SEARCH_MIN) return SEARCH_MIN;
  if (t > SEARCH_MAX) return SEARCH_MAX;
  return t;
}
static float roundToBin(float t) { return roundf(t / BIN_WIDTH) * BIN_WIDTH; }

static int findBin(const Profile* p, float temp) {
  float key = roundToBin(temp);
  for (int i = 0; i < p->nBins; i++)
    if (fabsf(p->bins[i].temp - key) < BIN_WIDTH * 0.5f) return i;
  return -1;
}

static void recordResult(Profile* p, float temp, float solMin) {
  float key = roundToBin(temp);
  int idx = findBin(p, temp);
  if (idx < 0) {
    if (p->nBins >= MAX_BINS) return;
    idx = p->nBins++;
    p->bins[idx].temp = key;
    p->bins[idx].solSumMin = 0;
    p->bins[idx].count = 0;
  }
  p->bins[idx].solSumMin += solMin;
  p->bins[idx].count     += 1;
  p->lastTemp = key;
}

static float binMean(const Bin* b) { return b->solSumMin / b->count; }

static bool parabolaVertex(float x1,float y1,float x2,float y2,float x3,float y3,float* vx) {
  float denom = (x1-x2)*(x1-x3)*(x2-x3);
  if (fabsf(denom) < 1e-9f) return false;
  float A = (x3*(y2-y1) + x2*(y1-y3) + x1*(y3-y2)) / denom;
  float B = (x3*x3*(y1-y2) + x2*x2*(y3-y1) + x1*x1*(y2-y3)) / denom;
  if (A <= 1e-6f) return false;
  *vx = -B/(2.0f*A);
  return true;
}

static float ensureSpacing(const Profile* p, float t) {
  if (findBin(p, t) < 0) return t;
  for (float d = BIN_WIDTH; d <= SEARCH_STEP0*2; d += BIN_WIDTH) {
    if (findBin(p, clampSearch(t-d)) < 0) return clampSearch(t-d);
    if (findBin(p, clampSearch(t+d)) < 0) return clampSearch(t+d);
  }
  return t;
}

static SearchResult nextTemperature(const Profile* p) {
  SearchResult r; r.converged = false; r.nextTemp = SEARCH_START;
  r.bestTemp = NAN; r.bestSol = NAN;

  int n = p->nBins;
  if (n == 0) { r.nextTemp = SEARCH_START; return r; }

  int best = 0;
  for (int i = 1; i < n; i++)
    if (binMean(&p->bins[i]) < binMean(&p->bins[best])) best = i;
  r.bestTemp = p->bins[best].temp;
  r.bestSol  = binMean(&p->bins[best]);

  if (n == 1) {
    float cand = clampSearch(r.bestTemp - SEARCH_STEP0);
    if (findBin(p,cand) >= 0) cand = clampSearch(r.bestTemp + SEARCH_STEP0);
    r.nextTemp = ensureSpacing(p, cand);
    return r;
  }

  if (n == 2) {
    int worse = (best==0) ? 1 : 0;
    float dir = (r.bestTemp - p->bins[worse].temp);
    float sign = (dir >= 0) ? +1.0f : -1.0f;
    float cand = clampSearch(r.bestTemp + sign*SEARCH_STEP0);
    if (findBin(p,cand) >= 0) cand = clampSearch(r.bestTemp - sign*SEARCH_STEP0);
    r.nextTemp = ensureSpacing(p, cand);
    return r;
  }

  int order[MAX_BINS];
  for (int i = 0; i < n; i++) order[i] = i;
  for (int i = 0; i < n-1; i++)
    for (int j = 0; j < n-1-i; j++)
      if (p->bins[order[j]].temp > p->bins[order[j+1]].temp) {
        int t = order[j]; order[j] = order[j+1]; order[j+1] = t;
      }
  int bpos = 0; for (int i = 0; i < n; i++) if (order[i] == best) { bpos = i; break; }
  int lo = (bpos > 0) ? bpos-1 : bpos;
  int hi = (bpos < n-1) ? bpos+1 : bpos;
  if (lo == bpos) hi = (bpos+2 < n) ? bpos+2 : n-1;
  if (hi == bpos) lo = (bpos-2 >= 0) ? bpos-2 : 0;

  int i1 = order[lo], i2 = order[bpos], i3 = order[hi];
  float vx;
  bool ok = parabolaVertex(
      p->bins[i1].temp, binMean(&p->bins[i1]),
      p->bins[i2].temp, binMean(&p->bins[i2]),
      p->bins[i3].temp, binMean(&p->bins[i3]), &vx);

  float cand;
  if (ok) {
    cand = clampSearch(vx);
    float maxStep = SEARCH_STEP0;
    if (cand > r.bestTemp + maxStep) cand = r.bestTemp + maxStep;
    if (cand < r.bestTemp - maxStep) cand = r.bestTemp - maxStep;
  } else {
    cand = clampSearch(r.bestTemp - SEARCH_STEP0*0.5f);
    if (findBin(p,cand) >= 0) cand = clampSearch(r.bestTemp + SEARCH_STEP0*0.5f);
  }

  if (fabsf(cand - r.bestTemp) < SEARCH_TOL && findBin(p, cand) >= 0) {
    r.converged = true;
    r.nextTemp  = r.bestTemp;
    return r;
  }
  r.nextTemp = ensureSpacing(p, cand);
  return r;
}

// ===========================================================================
//  PWM (ESP32 Core v3.x)
// ===========================================================================
static void pwmSetup() { ledcAttach(HEATER_PWM_PIN, PWM_FREQ_HZ, PWM_RES_BITS); }
static void pwmWrite(int duty) {
  if (duty < 0) duty = 0;
  if (duty > PWM_MAX) duty = PWM_MAX;
  ledcWrite(HEATER_PWM_PIN, duty);
}

// ===========================================================================
//  PID (제어 목표 = 피부 온도 / MLX90614)
// ===========================================================================
static float computePID(float setpoint, float tempC, float dtSec) {
  float error = setpoint - tempC;

  pidIntegral += error * dtSec;
  if (pidIntegral > INTEGRAL_WINDUP_LIMIT) pidIntegral = INTEGRAL_WINDUP_LIMIT;
  else if (pidIntegral < -INTEGRAL_WINDUP_LIMIT) pidIntegral = -INTEGRAL_WINDUP_LIMIT;

  // 미분항: 직전 오차 대비 변화량
  static float previousError = 0.0f;
  float derivative = pidPrimed ? (error - previousError) : 0.0f;
  previousError = error;

  float out = (Kp*error) + (Ki*pidIntegral) + (Kd*derivative);
  dbgP = Kp*error; dbgI = Ki*pidIntegral; dbgD = Kd*derivative;

  if (out < 0) out = 0;
  if (out > PWM_MAX) out = PWM_MAX;
  return out;
}
static void resetPID() { pidIntegral = 0; pidPrimed = false; dbgP = dbgI = dbgD = 0; }

// ===========================================================================
//  센서 폴링 — 매 루프 누적, 1분마다 판정
// ===========================================================================
static void pollMotionAndHR() {
  // ---- MPU6050: 가속도 변화량을 에폭 동안 누적 (움직임 지표) ----
  if (g_mpuOk) {
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);
    epochMotionAccum += fabsf(a.acceleration.x - prevAx)
                      + fabsf(a.acceleration.y - prevAy)
                      + fabsf(a.acceleration.z - prevAz);
    prevAx = a.acceleration.x; prevAy = a.acceleration.y; prevAz = a.acceleration.z;
  }

  // ---- MAX30102: 비트 검출 후 에폭 동안 BPM 누적 ----
  if (g_maxOk) {
    long irValue = particleSensor.getIR();
    if (checkForBeat(irValue)) {
      unsigned long nowMs = millis();
      long delta = nowMs - lastBeatMs;
      lastBeatMs = nowMs;
      if (delta > 0) {
        latestBpm = 60000.0f / (float)delta;
        if (latestBpm > 20 && latestBpm < 255) {
          epochHrSum += (long)latestBpm;
          epochHrCount++;
        }
      }
    }
  }
}

// 1분(EPOCH) 주기 — 입면 판정
static void evaluateEpochAndOnset(unsigned long now) {
  if (now - lastEpochStartMs < EPOCH_DURATION_MS) return;

  int epochAvgHR = (epochHrCount > 0) ? (int)(epochHrSum / epochHrCount) : 0;

  bool quietEpoch = (epochMotionAccum < MOTION_EPOCH_THRESHOLD)
                  && (epochAvgHR > 0) && (epochAvgHR <= HR_SLEEP_BASELINE_BPM);

  if (quietEpoch) continuousQuietEpochs++;
  else            continuousQuietEpochs = 0;

  if (!isAsleepConfirmed && continuousQuietEpochs >= REQUIRED_SLEEP_EPOCHS) {
    isAsleepConfirmed = true;
    // 조용한 구간이 실제로 "시작된" 시점으로 역산 (SOL 정확도 향상)
    unsigned long onsetMs = now - ((unsigned long)REQUIRED_SLEEP_EPOCHS * EPOCH_DURATION_MS);
    if (onsetMs < sessionStartMs) onsetMs = sessionStartMs;
    onSleepOnsetConfirmed(onsetMs);
  }

  // 에폭 변수 초기화
  epochMotionAccum = 0.0f;
  epochHrSum = 0; epochHrCount = 0;
  lastEpochStartMs = now;
}

// ===========================================================================
//  NVS 프로파일
// ===========================================================================
static void profileClear(Profile* p) { p->nBins = 0; p->lastTemp = SEARCH_START; }

static void loadProfile(const char* id) {
  prefs.begin("sleeptemp", true);
  size_t n = prefs.getBytesLength(id);
  if (n == sizeof(Profile)) prefs.getBytes(id, &g_profile, sizeof(Profile));
  else profileClear(&g_profile);
  prefs.end();
}
static void saveProfile(const char* id) {
  prefs.begin("sleeptemp", false);
  prefs.putBytes(id, &g_profile, sizeof(Profile));
  prefs.end();
}
static void eraseProfile(const char* id) {
  prefs.begin("sleeptemp", false);
  prefs.remove(id);
  prefs.end();
  profileClear(&g_profile);
}

// ===========================================================================
//  세션 제어
// ===========================================================================
static void startSession() {
  if (safetyState != STATE_NORMAL) {
    Serial.println("# START 거부: FAULT 상태. 먼저 'r' 로 해제하세요.");
    return;
  }
  if (!manualTempSet) {
    SearchResult sr = nextTemperature(&g_profile);
    if (sr.converged) {
      Serial.print("# 탐색 수렴됨. 최적 온도 약 ");
      Serial.print(sr.bestTemp,1);
      Serial.print("C (평균 SOL ");
      Serial.print(sr.bestSol,1); Serial.println(" min)");
    }
    sessionTemp = sr.nextTemp;
  }
  SETPOINT_C = sessionTemp;

  sessionStartMs = millis();
  lastEpochStartMs = sessionStartMs;
  epochMotionAccum = 0.0f;
  epochHrSum = 0; epochHrCount = 0;
  continuousQuietEpochs = 0;
  isAsleepConfirmed = false;

  sessionState = SESS_RUNNING;
  resetPID();
  Serial.print("# SESSION START  person="); Serial.print(g_personId);
  Serial.print("  temp="); Serial.print(sessionTemp,1); Serial.println("C");
}

// 입면 확정 시점 (에폭 로직에서 호출) — 측정 기록 후, 설정 시간만큼 가온 유지(Cooldown)
static void onSleepOnsetConfirmed(unsigned long onsetMs) {
  float solMin = (onsetMs - sessionStartMs) / 60000.0f;
  Serial.print("# SLEEP ONSET detected. SOL="); Serial.print(solMin,2);
  Serial.println(" min");

  recordResult(&g_profile, sessionTemp, solMin);
  saveProfile(g_personId);

  SearchResult sr = nextTemperature(&g_profile);
  Serial.print("@RESULT,"); Serial.print(g_personId); Serial.print(',');
  Serial.print(sessionTemp,1); Serial.print(',');
  Serial.print(solMin,2); Serial.print(',');
  Serial.print(sr.converged?1:0); Serial.print(',');
  Serial.print(sr.bestTemp,1); Serial.print(',');
  Serial.print(sr.bestSol,2); Serial.print(',');
  Serial.println(sr.nextTemp,1);

  // 입면 확정 후에도 목표 온도로 HEATING_DURATION_MS 동안 가온 유지
  cooldownEndMs = millis() + HEATING_DURATION_MS;
  sessionState  = SESS_COOLDOWN;
  Serial.print("# COOLDOWN 진입: 앞으로 ");
  Serial.print(HEATING_DURATION_MS / 60000UL);
  Serial.println("분간 가온을 유지합니다.");
}

// 세션 최대시간 내 미입면 — 타임아웃(패널티 SOL 기록 후 즉시 종료)
static void finalizeNoOnset() {
  float solMin = SESSION_MAX_MS / 60000.0f;
  Serial.print("# NO ONSET (timeout). SOL capped="); Serial.print(solMin,1);
  Serial.println(" min");

  recordResult(&g_profile, sessionTemp, solMin);
  saveProfile(g_personId);

  sessionState = SESS_DONE;
  manualTempSet = false;
  SETPOINT_C = 0;
}

static void updateSession(unsigned long now) {
  if (now < sessionStartMs) return;
  if (sessionState == SESS_RUNNING) {
    evaluateEpochAndOnset(now);
    if (sessionState == SESS_RUNNING && (now - sessionStartMs >= SESSION_MAX_MS)) {
      finalizeNoOnset();
    }
  } else if (sessionState == SESS_COOLDOWN) {
    if (now >= cooldownEndMs) {
      Serial.println("# COOLDOWN 종료: 히터 정지");
      sessionState  = SESS_DONE;
      manualTempSet = false;
      SETPOINT_C = 0;
    }
  }
}

// ===========================================================================
//  로깅
// ===========================================================================

static void printCsvHeader() {
  Serial.println("======================================================");
  Serial.println(" ESP32 수면 온도 제어기 부팅 완료 (실시간 모니터링 시작)");
  Serial.println("======================================================");
}

static void logCsv(unsigned long t, float skinC, float heaterC, int duty) {
  Serial.print("[진행상태] "); 
  Serial.print("시간:"); Serial.print(t / 1000); Serial.print("초 | ");
  Serial.print("피부온도:"); Serial.print(isnan(skinC) ? -99.0 : skinC, 1); Serial.print("℃ | ");
  Serial.print("히터온도:"); Serial.print(isnan(heaterC) ? -99.0 : heaterC, 1); Serial.print("℃ | ");
  Serial.print("목표:"); Serial.print(SETPOINT_C, 1); Serial.print("℃ | ");
  
  Serial.print("히터파워:"); Serial.print(100.0f * duty / PWM_MAX, 0); Serial.print("% | ");
  Serial.print("심박수:"); Serial.print(latestBpm, 0); Serial.print("BPM | ");
  
  Serial.print("안전:"); Serial.print(stateName(safetyState)); Serial.print(" | ");
  Serial.print("세션:"); Serial.print(sessName(sessionState)); Serial.print(" | ");
  
  Serial.print("연속수면(분):"); Serial.print(continuousQuietEpochs); Serial.print(" | ");
  Serial.println(isAsleepConfirmed ? "판정: 수면중" : "판정: 깨어있음");
}

static void printReport() {
  Serial.print("# ---- 리포트: "); Serial.print(g_personId); Serial.println(" ----");
  Serial.println("# 설정온도 , 평균 수면잠복기(분) , 시도횟수");
  for (int i = 0; i < g_profile.nBins; i++) {
    Serial.print("#  "); Serial.print(g_profile.bins[i].temp,1);
    Serial.print(" , "); Serial.print(binMean(&g_profile.bins[i]),2);
    Serial.print(" , "); Serial.println(g_profile.bins[i].count);
  }
  SearchResult sr = nextTemperature(&g_profile);
  Serial.print("# 최고성능온도="); Serial.print(sr.bestTemp,1);
  Serial.print("C  다음추천="); Serial.print(sr.nextTemp,1);
  Serial.println("C");
}

// ===========================================================================
//  시리얼 명령
// ===========================================================================
static void handleSerial(float skinC, float heaterC) {
  static char buf[48]; static int len = 0;
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (len == 0) continue;
      buf[len] = 0; len = 0;
      if (strncmp(buf,"id ",3) == 0) {
        strncpy(g_personId, buf+3, sizeof(g_personId)-1);
        g_personId[sizeof(g_personId)-1] = 0;
        loadProfile(g_personId);
        Serial.print("# person="); Serial.print(g_personId);
        Serial.print("  bins="); Serial.println(g_profile.nBins);
      } else if (strcmp(buf,"start") == 0) {
        startSession();
      } else if (strcmp(buf,"abort") == 0) {
        pwmWrite(0); SETPOINT_C = 0; sessionState = SESS_IDLE; manualTempSet = false;
        Serial.println("# SESSION aborted");
      } else if (strncmp(buf,"set ",4) == 0) {
        sessionTemp = clampSearch(atof(buf+4)); manualTempSet = true;
        Serial.print("# 세션 온도 수동 지정="); Serial.println(sessionTemp,1);
      } else if (strcmp(buf,"report") == 0) {
        printReport();
      } else if (strcmp(buf,"reset_profile") == 0) {
        eraseProfile(g_personId);
        Serial.println("# profile erased");
      } else if (strcmp(buf,"r") == 0) {
        bool skinOk   = !isnan(skinC)   && skinC   > T_SENSE_MIN_C && skinC   < T_SENSE_MAX_C;
        bool heaterOk = !isnan(heaterC) && heaterC > T_SENSE_MIN_C && heaterC < T_SENSE_MAX_C;
        bool tempsSafe = skinOk && heaterOk && (skinC < SKIN_REARM_C) && (heaterC < HEATER_REARM_C);
        if (safetyState != STATE_NORMAL && tempsSafe) {
          safetyState = STATE_NORMAL; resetPID();
          Serial.println("# RESET: FAULT 해제");
        } else if (safetyState != STATE_NORMAL) {
          Serial.println("# RESET 거부: 피부/히터 온도가 REARM 이하이고 센서가 정상이어야 함");
        }
      } else {
        Serial.print("# unknown cmd: "); Serial.println(buf);
      }
    } else if (len < (int)sizeof(buf)-1) {
      buf[len++] = c;
    }
  }
}

// ===========================================================================
//  setup / loop
// ===========================================================================
void setup() {
  Serial.begin(115200);
  delay(300);

  pwmSetup(); pwmWrite(0);
  SETPOINT_C = 0;
  analogReadResolution(12);
  analogSetPinAttenuation(NTC_PIN, ADC_11db);
  pinMode(START_BTN_PIN, INPUT_PULLUP);

  Wire.begin();  // SDA=21, SCL=22 (기본)

  g_mpuOk = mpu.begin();
  if (g_mpuOk) mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
  Serial.println(g_mpuOk ? "# MPU6050 OK" : "# MPU6050 NOT found");

  g_mlxOk = mlx.begin();
  Serial.println(g_mlxOk ? "# MLX90614 OK" : "# MLX90614 NOT found");

  // MAX30102 초기화 (이때 I2C 통신 속도가 400kHz로 빨라짐)
  g_maxOk = particleSensor.begin(Wire, I2C_SPEED_FAST);
  
  // ★ 추가된 코드: MLX90614 센서와의 호환성을 위해 I2C 통신 속도를 100kHz로 원상 복구합니다 ★
  Wire.setClock(100000); 

  if (g_maxOk) {
    particleSensor.setup();
    particleSensor.setPulseAmplitudeRed(0x0A);
    particleSensor.setPulseAmplitudeGreen(0);
  }
  Serial.println(g_maxOk ? "# MAX30102 OK" : "# MAX30102 NOT found");

  if (g_mpuOk) {
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);
    prevAx = a.acceleration.x; prevAy = a.acceleration.y; prevAz = a.acceleration.z;
  }

  profileClear(&g_profile);
  loadProfile(g_personId);

  Serial.println("# ESP32 Sleep-Onset Temperature Optimizer [실기 v3]");
  Serial.print("# SkinHardLimit="); Serial.print(SKIN_HARD_LIMIT_C,1);
  Serial.print("C  HeaterHardLimit="); Serial.print(HEATER_HARD_LIMIT_C,1);
  Serial.print("C  SearchRange="); Serial.print(SEARCH_MIN,1);
  Serial.print("-"); Serial.print(SEARCH_MAX,1); Serial.println("C");
  Serial.print("# Epoch="); Serial.print(EPOCH_DURATION_MS/60000UL);
  Serial.print("min  RequiredQuietEpochs="); Serial.print(REQUIRED_SLEEP_EPOCHS);
  Serial.print("  HeatingDurationAfterOnset="); Serial.print(HEATING_DURATION_MS/60000UL);
  Serial.println("min");
  Serial.println("# cmds: id <name> | start | abort | set <c> | report | reset_profile | r");

  printCsvHeader();
  lastControlMs = lastLogMs = millis();
}

void loop() {
  unsigned long now = millis();

  // --- 고속 센서 폴링 (매 루프, Non-blocking) ---
  pollMotionAndHR();

  // --- 시작 버튼 (엣지 검출) ---
  static bool btnPrev = HIGH;
  bool btn = digitalRead(START_BTN_PIN);
  if (btnPrev == HIGH && btn == LOW && sessionState == SESS_IDLE) startSession();
  btnPrev = btn;

  // --- 제어 주기 (1초) ---
  if (now - lastControlMs >= CONTROL_PERIOD_MS) {
    lastControlMs = now;

    float heaterC = readHeaterTempC();               // NTC: 히터 표면 온도(안전감시용)
    float skinC   = g_mlxOk ? mlx.readObjectTempC() : NAN; // MLX90614: 피부 온도(제어 목표)

    safetyState = evaluateSafety(skinC, heaterC, lastLoggedSkinC, lastLoggedHeaterC, safetyState);
    handleSerial(skinC, heaterC);

    // 세션/입면 갱신
    updateSession(now);

    // 제어 출력
    int duty = 0;
    bool heaterAllowed = (safetyState == STATE_NORMAL)
                       && (sessionState == SESS_RUNNING || sessionState == SESS_COOLDOWN)
                       && (SETPOINT_C > 0);
    if (heaterAllowed) {
      float out = computePID(SETPOINT_C, skinC, CONTROL_PERIOD_MS/1000.0f);
      duty = (int)(out + 0.5f);
      lastSkinTempC = skinC; pidPrimed = true;
    } else {
      resetPID();
    }
    if (safetyState != STATE_NORMAL) duty = 0;  // ★ 하드 컷오프 강제 ★
    pwmWrite(duty);

    lastLoggedSkinC = skinC;
    lastLoggedHeaterC = heaterC;

    if (now - lastLogMs >= LOG_PERIOD_MS) {
      lastLogMs = now;
      logCsv(now, skinC, heaterC, duty);
    }
  }
}