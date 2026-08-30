/* ============================================================================
 * ESP32 개인 맞춤 입면 온도 탐색기 — 실제 하드웨어 통합 버전 (v7)
 * (Personalized Sleep-Onset Temperature Optimizer for real ESP32 kit)
 *
 * v3 -> v4 변경점
 *  1) 심박 기준선(안정심박수) 자동 캘리브레이션
 *     - 이후 30초 = 안정심박수 수집(평균) -> 이번 세션의 기준값
 *     - 실시간 심박이 (안정심박수 - 10) BPM 이하로 20분 이상 유지 + 움직임 없음
 *       -> 입면 판정 후 서버(호스트 PC)로 상태 플래그 전송
 *  2) 60분 동안 입면 판정이 없으면 결과 기록 후 기기 전원 차단(딥슬립)
 *  3) 이상 온도는 5초 이상 연속 유지될 때만 FAULT로 래치
 *     (판정 대기 중에도 히터 출력은 즉시 0으로 차단 — 안전 우선)
 *
 * v4 -> v5 변경점
 *  4) 모든 센서(MLX90614 / NTC / MPU6050 / MAX30102)는 start 전까지 정지 상태.
 *     start 누르면 측정을 시작하고, 처음 20초(SENSOR_WARMUP_MS)는 워밍업 구간으로
 *     모든 센서 데이터를 버린다. 이 구간에는 유효한 온도 기준이 없으므로 히터도 켜지
 *     않는다(가열은 워밍업 종료 후 시작).
 *  5) 60분 미입면(타임아웃) -> 히터 + 모든 센서 정지 후 기기 종료.
 *
 * v6 -> v7 변경점
 *  7) 기기 ID 를 칩에 구워진 MAC(efuse)에서 만들어 쓴다 — 사람이 정하지 않는다.
 *     부팅 시 "@ID,DORMX-XXXXXXXXXXXX" 로 알리고, 호스트는 이 값으로 업로드한다.
 *
 * v5 -> v6 변경점
 *  6) 입면 확정 시: 입면 판정용 생체 센서(MPU6050/MAX30102)는 즉시 정지하고,
 *     목표 온도로 HEATING_DURATION_MS(10분) 동안 가온을 유지한 뒤 히터와 온도 센서를
 *     정지시키고 기기를 종료한다. 가온 중에는 PID 입력(MLX90614)과 과열 감시(NTC)가
 *     반드시 필요하므로 온도 센서 2종은 히터가 꺼질 때 함께 끈다.
 * ========================================================================== */

#include <Wire.h>
#include <Preferences.h>
#include <math.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_MLX90614.h>
#include "MAX30105.h"
#include "heartRate.h"
#include "esp_sleep.h"
#include "esp_mac.h"
#include "driver/rtc_io.h"

// ===========================================================================
// 핀 / 하드웨어 설정
// ===========================================================================
static const int HEATER_PWM_PIN = 26;   // MOSFET(IRLML2502) 게이트
static const int NTC_PIN        = 34;   // NTC 서미스터(히터 표면) 아날로그 핀
static const int START_BTN_PIN  = 32;   // 세션 시작 버튼 (INPUT_PULLUP, RTC GPIO)

// ------- NTC 전압 분배기 / ADC (히터 표면 온도, 안전감시 전용) -------
static const float V_SUPPLY_MV = 3300.0f;
static const float SERIES_R    = 10000.0f;
static const int   ADC_SAMPLES = 16;
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
static const unsigned long CONTROL_PERIOD_MS = 1000;  // 1초
static const unsigned long LOG_PERIOD_MS     = 1000;

// ===========================================================================
// 안전(Watchdog) — 히터(NTC) / 피부(MLX) 이중 감시
// ===========================================================================
static const float SKIN_HARD_LIMIT_C   = 42.0f;  // 피부 표면 절대 상한
static const float HEATER_HARD_LIMIT_C = 45.0f;  // 히터 필름 절대 상한
static const float SPIKE_JUMP_C        = 2.0f;   // 1제어주기(1초) 내 급상승 한계
static const float SKIN_REARM_C        = 39.0f;  // 재가동 허용 온도(피부)
static const float HEATER_REARM_C      = 42.0f;  // 재가동 허용 온도(히터)

// [변경 3] 이상 온도가 이 시간 이상 "연속" 유지될 때만 FAULT 래치
static const unsigned long FAULT_PERSIST_MS = 5000UL;
// 스파이크 판정 후, 온도가 이 값 이상 떨어지면 "이상 상태 해소"로 간주
static const float SPIKE_RELEASE_MARGIN_C = 0.5f;

enum SafetyState {
  STATE_NORMAL = 0,
  STATE_FAULT_OVERTEMP_SKIN,
  STATE_FAULT_OVERTEMP_HEATER,
  STATE_FAULT_SPIKE_SKIN,
  STATE_FAULT_SPIKE_HEATER,
  STATE_FAULT_SENSOR
};

// ===========================================================================
// 세션 상태
// ===========================================================================
//  IDLE   : 대기(센서 정지)
//  WARMUP : start 직후 20초 — 센서만 켜서 안정화, 데이터는 버리고 히터도 끔
//  RUNNING: 가온 + 안정심박수 측정 + 입면 판정
//  COOLDOWN: (KEEP_HEATING_AFTER_ONSET=1 일 때만) 입면 후 가온 유지
//  OFF    : 종료(히터·센서 정지)
enum SessionState { SESS_IDLE = 0, SESS_WARMUP, SESS_RUNNING, SESS_COOLDOWN, SESS_OFF };

// ===========================================================================
// 입면(Sleep Onset) 추정 — 1분 에폭 누적
// ===========================================================================
static const unsigned long EPOCH_DURATION_MS   = 60000UL;   // 1분 에폭
static const int  REQUIRED_SLEEP_EPOCHS        = 20;        // 연속 20에폭(20분) 유지 시 입면
static const float MOTION_EPOCH_THRESHOLD      = 5.0f;      // 에폭 누적 움직임 임계값
static const unsigned long SESSION_MAX_MS      = 60UL * 60 * 1000;  // 세션 최대 60분

// [변경 6] 입면 확정 시 동작
//   1 = 생체 센서만 즉시 정지하고 아래 시간만큼 가온 유지 후 히터/온도 센서 정지(기본)
//   0 = 입면 확정 즉시 히터와 모든 센서 정지
#define KEEP_HEATING_AFTER_ONSET 1
static const unsigned long HEATING_DURATION_MS = 10UL * 60000UL;    // 10분

// ------- [변경 4] 센서 워밍업: start 직후 이 시간 동안의 모든 센서 데이터를 버린다 -------
static const unsigned long SENSOR_WARMUP_MS = 20000UL;  // 20초 (온도/움직임/심박 공통)

// ------- [변경 1] 심박 기준선(안정심박수) 캘리브레이션 -------
static const unsigned long CALIB_COLLECT_MS = 30000UL;  // 워밍업 후 30초: 안정심박수 수집
static const int   CALIB_MIN_SAMPLES  = 10;             // 30초 동안 최소 확보해야 할 비트 수
static const int   CALIB_MAX_ATTEMPTS = 3;              // 수집 실패 시 재시도 횟수
static const float RESTING_BPM_MIN    = 40.0f;          // 안정심박수 허용 범위
static const float RESTING_BPM_MAX    = 120.0f;
static const float HR_DROP_BPM        = 10.0f;          // 입면 기준 = 안정심박수 - 10
static const float ONSET_HR_FLOOR_BPM = 35.0f;          // 입면 기준의 하한(생리학적 안전선)
static const float HR_FALLBACK_RESTING_BPM = 60.0f;     // 캘리브레이션 실패 시 대체 기준

static const int   MIN_HR_SAMPLES_PER_EPOCH = 10;       // 에폭이 유효하려면 필요한 비트 수
static const float HR_ABOVE_RATIO_MAX       = 0.25f;    // 기준 초과 샘플 비율 허용치

// 전원 차단 방식: 1 = 딥슬립(버튼으로 재기동), 0 = 히터/센서만 끄고 SESS_OFF 유지
#define POWER_OFF_USE_DEEP_SLEEP 1

// MLX90614 라이브러리에 enterSleepMode() 가 있는 버전이면 1 로 두면 절전까지 수행한다.
// (0 이어도 읽기를 멈추므로 측정은 정지된다)
#define MLX_HAS_SLEEP_API 0

// ===========================================================================
// 적응형 온도 탐색 파라미터
// ===========================================================================
static const int   MAX_BINS     = 16;
static const float SEARCH_START = 39.0f;   // 첫 세션 온도
static const float SEARCH_MIN   = 37.5f;
static const float SEARCH_MAX   = 40.5f;   // SKIN_HARD_LIMIT(42) 대비 여유 확보
static const float SEARCH_STEP0 = 1.0f;
static const float SEARCH_TOL   = 0.3f;
static const float BIN_WIDTH    = 0.5f;

struct Bin     { float temp; float solSumMin; uint16_t count; };
struct Profile { uint8_t nBins; Bin bins[MAX_BINS]; float lastTemp; };
struct SearchResult { float nextTemp; bool converged; float bestTemp; float bestSol; };

// ===========================================================================
// 함수 프로토타입
// ===========================================================================
static float heaterVoltageToResistance(float vNodeMv);
static float heaterResistanceToTempC(float rOhm);
static float readHeaterTempC();

static SafetyState classifyAbnormal(float skinC, float heaterC, float lastSkinC, float lastHeaterC);
static SafetyState evaluateSafety(float skinC, float heaterC, float lastSkinC, float lastHeaterC,
                                  SafetyState current, unsigned long now);
static void  clearFaultPending();
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

static void setBioSensorsActive(bool on);   // MPU6050 + MAX30102 (입면 판정용)
static void setTempSensorsActive(bool on);  // MLX90614 + NTC (PID/과열 감시용)
static void setSensorsActive(bool on);      // 위 둘을 한 번에
static bool sensorDataAccepted();        // 워밍업이 끝나 데이터를 신뢰할 수 있는가

static void  pwmSetup();
static void  pwmWrite(int duty);
static float computePID(float setpoint, float tempC, float dtSec);
static void  resetPID();

static void pollMotionAndHR();                        // 매 루프: 움직임/심박 누적 (Non-blocking)
static void updateCalibration(unsigned long now);     // 워밍업 후 30초 평균 = 안정심박수
static void evaluateEpochAndOnset(unsigned long now); // 1분마다: 입면 판정

static void profileClear(Profile* p);
static void loadProfile(const char* id);
static void saveProfile(const char* id);
static void eraseProfile(const char* id);

static void startSession();
static void onSleepOnsetConfirmed(unsigned long onsetMs);
static void finalizeNoOnset();
static void updateSession(unsigned long now);
static void shutdownDevice(const char* reason);

static void buildDeviceId();             // 칩 MAC(efuse) -> 기기 고유 ID
static void announceDeviceId();          // 호스트에 기기 ID 알림
static void sendServerFlag(const char* flag, float v1, float v2);
static void printCsvHeader();
static void logCsv(unsigned long t, float skinC, float heaterC, int duty);
static void printReport();
static void handleSerial(float skinC, float heaterC);

// ===========================================================================
// 전역 상태
// ===========================================================================
static SafetyState  safetyState  = STATE_NORMAL;
static SessionState sessionState = SESS_IDLE;

// 센서 객체
static Adafruit_MPU6050 mpu;
static Adafruit_MLX90614 mlx;
static MAX30105 particleSensor;
static bool g_mpuOk = false, g_mlxOk = false, g_maxOk = false;
// [변경 4] start 전/종료 후에는 모든 센서 정지
static bool g_bioSensorsActive  = false;  // MPU6050 + MAX30102 (입면 판정용)
static bool g_tempSensorsActive = false;  // MLX90614 + NTC     (PID 제어 + 과열 감시용)

// PID 내부
static float pidIntegral = 0.0f, pidPrevError = 0.0f;
static bool  pidPrimed = false;
static float dbgP = 0, dbgI = 0, dbgD = 0;

// 안전감시용 직전값 / FAULT 지연 판정 상태
static float lastLoggedSkinC = NAN, lastLoggedHeaterC = NAN;
static SafetyState   pendingFault    = STATE_NORMAL;
static unsigned long pendingFaultMs  = 0;
static bool  g_preFaultCutoff = false;   // FAULT 확정 전이라도 히터를 끄는 예방 차단
static float spikeRefSkinC   = NAN;      // 스파이크 감지 시점의 온도(해소 판단용)
static float spikeRefHeaterC = NAN;

// ---- 심박 기준선(캘리브레이션) 상태 ----
enum CalibState { CAL_NONE = 0, CAL_COLLECT, CAL_READY, CAL_FAILED };
static CalibState    calibState      = CAL_NONE;
static unsigned long calibPhaseMs    = 0;
static double        calibBpmSum     = 0;
static int           calibBpmCount   = 0;
static int           calibAttempts   = 0;
static float g_restingBpm       = NAN;   // 이번 세션의 안정심박수
static float g_onsetHrThreshold = NAN;   // 입면 기준 = 안정심박수 - HR_DROP_BPM

// ---- 입면 추정(에폭) 상태 ----
static unsigned long lastEpochStartMs = 0;
static float epochMotionAccum = 0.0f;
static float prevAx = 0, prevAy = 0, prevAz = 0;
static double epochHrSum = 0;
static int  epochHrCount = 0;
static int  epochHrAbove = 0;            // 기준 초과 샘플 수
static int  continuousQuietEpochs = 0;
static bool isAsleepConfirmed = false;

// MAX30102 비트 검출용
static long  lastBeatMs = 0;
static float latestBpm  = 0;

// ---- 세션 ----
static unsigned long sessionStartMs = 0;
static unsigned long cooldownEndMs  = 0;
static float sessionTemp   = SEARCH_START;
static float SETPOINT_C    = 0;
static bool  manualTempSet = false;

// 타이밍
static unsigned long lastControlMs = 0, lastLogMs = 0;

// 프로파일 / NVS
static Profile g_profile;
static char g_personId[16] = "default";
// [변경 7] 칩에 구워진 MAC 에서 만든 기기 고유 ID. 사람이 바꿀 수 없다.
static char g_deviceId[20] = "DORMX-UNKNOWN";
static Preferences prefs;

// ===========================================================================
// ---- [변경 4] 센서 측정 시작/정지 ----
//   start 전, 그리고 세션 종료 후에는 모든 센서를 정지시킨다.
//   NTC 분압 회로는 상시 전원이라 물리적으로 끌 수 없으므로 ADC 샘플링을 멈춘다.
//
//   센서는 두 계통으로 나눠 제어한다.
//    - 생체 센서(MPU6050 / MAX30102): 입면 판정 전용. 입면이 확정되면 바로 정지.
//    - 온도 센서(MLX90614 / NTC)    : PID 제어 + 과열 감시용. 히터가 켜져 있는 동안은
//                                     반드시 살아 있어야 하므로 히터를 끌 때 함께 끈다.
// ===========================================================================
static void setBioSensorsActive(bool on) {
  if (on) {
    if (g_mpuOk) mpu.enableSleep(false);
    if (g_maxOk) particleSensor.wakeUp();
    g_bioSensorsActive = true;
    latestBpm = 0; lastBeatMs = millis();
    prevAx = prevAy = prevAz = 0;
    epochMotionAccum = 0.0f;
    epochHrSum = 0; epochHrCount = 0; epochHrAbove = 0;
    Serial.println("# 생체 센서 측정 시작 (MPU6050 / MAX30102)");
  } else {
    if (g_mpuOk) mpu.enableSleep(true);
    if (g_maxOk) particleSensor.shutDown();
    g_bioSensorsActive = false;
    latestBpm = 0;
    Serial.println("# 생체 센서 측정 정지 (MPU6050 / MAX30102)");
  }
}

static void setTempSensorsActive(bool on) {
  if (on) {
#if MLX_HAS_SLEEP_API
    if (g_mlxOk) mlx.enterSleepMode(false);
#endif
    g_tempSensorsActive = true;
    lastLoggedSkinC = NAN; lastLoggedHeaterC = NAN;
    Serial.println("# 온도 센서 측정 시작 (MLX90614 / NTC)");
  } else {
#if MLX_HAS_SLEEP_API
    if (g_mlxOk) mlx.enterSleepMode(true);
#endif
    g_tempSensorsActive = false;
    lastLoggedSkinC = NAN; lastLoggedHeaterC = NAN;
    Serial.println("# 온도 센서 측정 정지 (MLX90614 / NTC)");
  }
}

static void setSensorsActive(bool on) {
  setBioSensorsActive(on);
  setTempSensorsActive(on);
}

// 워밍업(SESS_WARMUP) 동안의 온도 데이터는 제어/안전 판정에 쓰지 않는다.
static bool sensorDataAccepted() {
  return g_tempSensorsActive && sessionState != SESS_WARMUP;
}

// ===========================================================================
// ---- NTC(히터) 온도 변환 : 안전감시 전용 ----
// ===========================================================================
static float heaterVoltageToResistance(float vNodeMv) {
  if (vNodeMv <= 1.0f) return NAN;
  if (vNodeMv >= V_SUPPLY_MV - 1.0f) return NAN;
#if THERMISTOR_INVERTED
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
  double lnR  = log((double)rOhm);
  double invT = SH_A + SH_B * lnR + SH_C * lnR * lnR * lnR;
  return (float)(1.0/invT - 273.15);
#endif
}

static float readHeaterTempC() {
  if (!g_tempSensorsActive) return NAN;      // 센서 정지 중에는 측정하지 않는다
  uint32_t acc = 0;
  for (int i = 0; i < ADC_SAMPLES; i++) acc += analogReadMilliVolts(NTC_PIN);
  float mv = (float)acc / ADC_SAMPLES;
  return heaterResistanceToTempC(heaterVoltageToResistance(mv));
}

// ===========================================================================
// ---- 안전 평가 (히터 NTC + 피부 MLX 이중 감시, 5초 지속 시 래치) ----
// ===========================================================================

// 순간값 기준으로 "지금 이상 상태인가"만 판정 (래치/지속시간 판단은 상위에서)
static SafetyState classifyAbnormal(float skinC, float heaterC, float lastSkinC, float lastHeaterC) {
  // 센서 이상(범위 초과/NaN)
  if (isnan(skinC)   || skinC   < T_SENSE_MIN_C || skinC   > T_SENSE_MAX_C) return STATE_FAULT_SENSOR;
  if (isnan(heaterC) || heaterC < T_SENSE_MIN_C || heaterC > T_SENSE_MAX_C) return STATE_FAULT_SENSOR;

  // 절대 상한
  if (skinC   >= SKIN_HARD_LIMIT_C)   return STATE_FAULT_OVERTEMP_SKIN;
  if (heaterC >= HEATER_HARD_LIMIT_C) return STATE_FAULT_OVERTEMP_HEATER;

  // 급상승(열폭주/센서오작동) — 한 번 감지되면 온도가 다시 내려올 때까지 이상 상태로 본다
  if (!isnan(spikeRefSkinC)) {
    if (skinC >= spikeRefSkinC - SPIKE_RELEASE_MARGIN_C) return STATE_FAULT_SPIKE_SKIN;
    spikeRefSkinC = NAN;                       // 온도가 원복 -> 일시적 노이즈로 판단
  } else if (!isnan(lastSkinC) && (skinC - lastSkinC) >= SPIKE_JUMP_C) {
    spikeRefSkinC = skinC;
    return STATE_FAULT_SPIKE_SKIN;
  }

  if (!isnan(spikeRefHeaterC)) {
    if (heaterC >= spikeRefHeaterC - SPIKE_RELEASE_MARGIN_C) return STATE_FAULT_SPIKE_HEATER;
    spikeRefHeaterC = NAN;
  } else if (!isnan(lastHeaterC) && (heaterC - lastHeaterC) >= SPIKE_JUMP_C) {
    spikeRefHeaterC = heaterC;
    return STATE_FAULT_SPIKE_HEATER;
  }

  return STATE_NORMAL;
}

static void clearFaultPending() {
  pendingFault    = STATE_NORMAL;
  pendingFaultMs  = 0;
  g_preFaultCutoff = false;
  spikeRefSkinC   = NAN;
  spikeRefHeaterC = NAN;
}

// [변경 3] 이상 상태가 FAULT_PERSIST_MS(5초) 이상 연속될 때만 FAULT 확정(래치)
static SafetyState evaluateSafety(float skinC, float heaterC, float lastSkinC, float lastHeaterC,
                                  SafetyState current, unsigned long now) {
  // 이미 래치된 FAULT는 재가동(REARM) 조건 전까지 유지
  if (current != STATE_NORMAL) {
    g_preFaultCutoff = false;   // 이미 FAULT — 예방 차단 플래그는 의미 없음
    return current;
  }

  SafetyState cand = classifyAbnormal(skinC, heaterC, lastSkinC, lastHeaterC);

  if (cand == STATE_NORMAL) {
    if (pendingFault != STATE_NORMAL) {
      Serial.print("# 이상 온도 해소(FAULT 미확정): ");
      Serial.println(stateName(pendingFault));
    }
    clearFaultPending();
    return STATE_NORMAL;
  }

  // 이상 상태 지속 시간 측정 시작 / 갱신
  if (cand != pendingFault) {
    pendingFault   = cand;
    pendingFaultMs = now;
    Serial.print("# 이상 온도 감지(");
    Serial.print(stateName(cand));
    Serial.print(") — ");
    Serial.print(FAULT_PERSIST_MS / 1000UL);
    Serial.println("초 이상 지속되면 FAULT 확정. 히터는 즉시 차단합니다.");
  }

  g_preFaultCutoff = true;      // 확정 전이라도 가열은 멈춘다(안전 우선)

  if (now - pendingFaultMs >= FAULT_PERSIST_MS) {
    SafetyState latched = pendingFault;
    clearFaultPending();
    Serial.print("# FAULT 확정: ");
    Serial.println(stateName(latched));
    sendServerFlag("FAULT", (float)latched, isnan(skinC) ? -99.0f : skinC);
    return latched;
  }

  return STATE_NORMAL;          // 아직 지속시간 미달 — FAULT 아님
}

static const char* stateName(SafetyState s) {
  switch (s) {
    case STATE_NORMAL:                 return "NORMAL";
    case STATE_FAULT_OVERTEMP_SKIN:    return "FAULT_OVERTEMP_SKIN";
    case STATE_FAULT_OVERTEMP_HEATER:  return "FAULT_OVERTEMP_HEATER";
    case STATE_FAULT_SPIKE_SKIN:       return "FAULT_SPIKE_SKIN";
    case STATE_FAULT_SPIKE_HEATER:     return "FAULT_SPIKE_HEATER";
    case STATE_FAULT_SENSOR:           return "FAULT_SENSOR";
    default:                           return "?";
  }
}
static const char* sessName(SessionState s) {
  switch (s) {
    case SESS_IDLE:     return "IDLE";
    case SESS_WARMUP:   return "WARMUP";
    case SESS_RUNNING:  return "RUNNING";
    case SESS_COOLDOWN: return "COOLDOWN";
    case SESS_OFF:      return "OFF";
    default:            return "?";
  }
}

// ===========================================================================
// ---- 개인화 탐색 알고리즘 ----
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
  p->bins[idx].count += 1;
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
  SearchResult r;
  r.converged = false;
  r.nextTemp  = SEARCH_START;
  r.bestTemp  = NAN;
  r.bestSol   = NAN;

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
    float dir  = (r.bestTemp - p->bins[worse].temp);
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
  int bpos = 0;
  for (int i = 0; i < n; i++) if (order[i] == best) { bpos = i; break; }
  int lo = (bpos > 0)   ? bpos-1 : bpos;
  int hi = (bpos < n-1) ? bpos+1 : bpos;
  if (lo == bpos) hi = (bpos+2 < n)  ? bpos+2 : n-1;
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
// PWM (ESP32 Core v3.x)
// ===========================================================================
static void pwmSetup() { ledcAttach(HEATER_PWM_PIN, PWM_FREQ_HZ, PWM_RES_BITS); }
static void pwmWrite(int duty) {
  if (duty < 0) duty = 0;
  if (duty > PWM_MAX) duty = PWM_MAX;
  ledcWrite(HEATER_PWM_PIN, duty);
}

// ===========================================================================
// PID (제어 목표 = 피부 온도 / MLX90614)
// ===========================================================================
static float computePID(float setpoint, float tempC, float dtSec) {
  float error = setpoint - tempC;

  pidIntegral += error * dtSec;
  if (pidIntegral >  INTEGRAL_WINDUP_LIMIT) pidIntegral =  INTEGRAL_WINDUP_LIMIT;
  else if (pidIntegral < -INTEGRAL_WINDUP_LIMIT) pidIntegral = -INTEGRAL_WINDUP_LIMIT;

  // 미분항: 직전 오차 대비 변화량
  float derivative = pidPrimed ? (error - pidPrevError) : 0.0f;
  pidPrevError = error;

  float out = (Kp*error) + (Ki*pidIntegral) + (Kd*derivative);
  dbgP = Kp*error; dbgI = Ki*pidIntegral; dbgD = Kd*derivative;

  if (out < 0) out = 0;
  if (out > PWM_MAX) out = PWM_MAX;
  return out;
}
static void resetPID() {
  pidIntegral = 0; pidPrevError = 0; pidPrimed = false;
  dbgP = dbgI = dbgD = 0;
}

// ===========================================================================
// 센서 폴링 — 매 루프 누적, 1분마다 판정
// ===========================================================================
static void pollMotionAndHR() {
  if (!g_bioSensorsActive) return;          // [변경 4] start 전 / 입면 확정 후에는 측정하지 않는다
  bool accept = (sessionState != SESS_WARMUP);  // 워밍업 20초 동안은 읽되 버린다

  // ---- MPU6050: 가속도 변화량을 에폭 동안 누적 (움직임 지표) ----
  if (g_mpuOk) {
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);
    if (accept) {
      epochMotionAccum += fabsf(a.acceleration.x - prevAx)
                        + fabsf(a.acceleration.y - prevAy)
                        + fabsf(a.acceleration.z - prevAz);
    }
    prevAx = a.acceleration.x; prevAy = a.acceleration.y; prevAz = a.acceleration.z;
  }

  // ---- MAX30102: 비트 검출 후 BPM 갱신 ----
  if (!g_maxOk) return;

  long irValue = particleSensor.getIR();
  if (!checkForBeat(irValue)) return;

  unsigned long nowMs = millis();
  long delta = nowMs - lastBeatMs;
  lastBeatMs = nowMs;
  if (delta <= 0) return;

  float instantBpm = 60000.0f / (float)delta;      // 순간 심박수 계산
  if (instantBpm <= 20 || instantBpm >= 255) return;

  if (latestBpm == 0) latestBpm = instantBpm;      // 제일 처음엔 현재 값으로 초기화
  else                latestBpm = (latestBpm * 0.85f) + (instantBpm * 0.15f);

  // [변경 4] 워밍업 20초 동안의 심박은 노이즈로 간주하여 버린다
  if (!accept) return;

  if (calibState == CAL_COLLECT) {                 // 30초간 안정심박수 수집
    calibBpmSum += latestBpm;
    calibBpmCount++;
    return;
  }

  if (calibState == CAL_READY || calibState == CAL_FAILED) {
    epochHrSum += latestBpm;
    epochHrCount++;
    if (!isnan(g_onsetHrThreshold) && latestBpm > g_onsetHrThreshold) epochHrAbove++;
  }
}

// ---- [변경 1] 안정심박수 캘리브레이션 (워밍업 종료 후 30초 평균) ----
static void updateCalibration(unsigned long now) {
  if (calibState != CAL_COLLECT) return;
  if (now - calibPhaseMs < CALIB_COLLECT_MS) return;

  if (calibBpmCount >= CALIB_MIN_SAMPLES) {
    float rest = (float)(calibBpmSum / calibBpmCount);
    if (rest < RESTING_BPM_MIN) rest = RESTING_BPM_MIN;
    if (rest > RESTING_BPM_MAX) rest = RESTING_BPM_MAX;
    g_restingBpm = rest;
    g_onsetHrThreshold = rest - HR_DROP_BPM;
    if (g_onsetHrThreshold < ONSET_HR_FLOOR_BPM) g_onsetHrThreshold = ONSET_HR_FLOOR_BPM;
    calibState = CAL_READY;

    Serial.print("# 안정심박수 확정 = ");
    Serial.print(g_restingBpm, 1);
    Serial.print(" BPM (샘플 ");
    Serial.print(calibBpmCount);
    Serial.print("개) / 입면 기준 = ");
    Serial.print(g_onsetHrThreshold, 1);
    Serial.print(" BPM 이하 ");
    Serial.print((unsigned long)REQUIRED_SLEEP_EPOCHS * (EPOCH_DURATION_MS / 60000UL));
    Serial.println("분 유지");
    sendServerFlag("HR_BASELINE", g_restingBpm, g_onsetHrThreshold);
  } else {
    calibAttempts++;
    if (calibAttempts < CALIB_MAX_ATTEMPTS) {
      Serial.print("# 안정심박수 측정 실패(샘플 ");
      Serial.print(calibBpmCount);
      Serial.print("개) — 재측정 ");
      Serial.print(calibAttempts + 1);
      Serial.print("/");
      Serial.println(CALIB_MAX_ATTEMPTS);
      calibPhaseMs  = now;     // 30초 수집 구간 재시작
      calibBpmSum   = 0;
      calibBpmCount = 0;
      return;
    }
    // 심박 신호를 못 얻는 경우: 기본 기준값으로 대체하고 계속 진행
    g_restingBpm = HR_FALLBACK_RESTING_BPM;
    g_onsetHrThreshold = g_restingBpm - HR_DROP_BPM;
    calibState = CAL_FAILED;
    Serial.print("# 안정심박수 측정 실패 — 기본값 ");
    Serial.print(g_restingBpm, 1);
    Serial.println(" BPM 사용 (심박 조건은 참고용, 움직임 위주 판정)");
    sendServerFlag("HR_BASELINE_FALLBACK", g_restingBpm, g_onsetHrThreshold);
  }

  // 캘리브레이션이 끝난 시점부터 입면 판정용 에폭 시계를 시작
  lastEpochStartMs = now;
  epochMotionAccum = 0.0f;
  epochHrSum = 0; epochHrCount = 0; epochHrAbove = 0;
  continuousQuietEpochs = 0;
}

// 1분(EPOCH) 주기 — 입면 판정
static void evaluateEpochAndOnset(unsigned long now) {
  if (calibState != CAL_READY && calibState != CAL_FAILED) return;  // 기준선 확보 전에는 판정하지 않음
  if (now - lastEpochStartMs < EPOCH_DURATION_MS) return;

  float epochAvgHR = (epochHrCount > 0) ? (float)(epochHrSum / epochHrCount) : 0.0f;

  // 움직임 조건: 에폭 누적 움직임이 임계값 미만
  bool motionQuiet = (!g_mpuOk) ? true : (epochMotionAccum < MOTION_EPOCH_THRESHOLD);

  // 심박 조건: 에폭 평균이 (안정심박수 - 10) 이하이고, 기준 초과 샘플이 드물 것
  bool hrQuiet;
  if (calibState == CAL_READY) {
    hrQuiet = (epochHrCount >= MIN_HR_SAMPLES_PER_EPOCH)
           && (epochAvgHR <= g_onsetHrThreshold)
           && ((float)epochHrAbove / (float)epochHrCount <= HR_ABOVE_RATIO_MAX);
  } else {
    hrQuiet = true;   // 심박 기준선을 못 잡은 경우 움직임만으로 판정
  }

  bool quietEpoch = motionQuiet && hrQuiet;

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
  epochHrSum = 0; epochHrCount = 0; epochHrAbove = 0;
  lastEpochStartMs = now;
}

// ===========================================================================
// NVS 프로파일
// ===========================================================================
static void profileClear(Profile* p) { p->nBins = 0; p->lastTemp = SEARCH_START; }

static void loadProfile(const char* id) {
  prefs.begin("sleeptemp", true);
  size_t n = prefs.getBytesLength(id);
  if (n == sizeof(Profile)) prefs.getBytes(id, &g_profile, sizeof(Profile));
  else                      profileClear(&g_profile);
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
// 서버(호스트 PC) 상태 플래그 전송
//   포맷: @FLAG,<person>,<flag>,<millis>,<v1>,<v2>
// ===========================================================================
// [변경 7] ESP32 efuse 에 구워진 기본 MAC(6바이트)으로 기기 ID 를 만든다.
//          같은 칩이면 항상 같은 값이고, 사용자가 입력할 필요가 없다.
static void buildDeviceId() {
  uint8_t mac[6] = {0};
  if (esp_read_mac(mac, ESP_MAC_WIFI_STA) != ESP_OK) {
    strncpy(g_deviceId, "DORMX-UNKNOWN", sizeof(g_deviceId) - 1);
    g_deviceId[sizeof(g_deviceId) - 1] = 0;
    return;
  }
  snprintf(g_deviceId, sizeof(g_deviceId), "DORMX-%02X%02X%02X%02X%02X%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

// 호스트(브리지)가 이 줄을 보고 업로드에 쓸 기기 ID 를 자동으로 잡는다.
static void announceDeviceId() {
  Serial.print("@ID,");
  Serial.println(g_deviceId);
}

static void sendServerFlag(const char* flag, float v1, float v2) {
  Serial.print("@FLAG,");
  Serial.print(g_personId);   Serial.print(',');
  Serial.print(flag);         Serial.print(',');
  Serial.print(millis());     Serial.print(',');
  Serial.print(v1, 2);        Serial.print(',');
  Serial.println(v2, 2);
}

// ===========================================================================
// 세션 제어
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
      Serial.print(sr.bestSol,1);
      Serial.println(" min)");
    }
    sessionTemp = sr.nextTemp;
  }
  SETPOINT_C = sessionTemp;

  sessionStartMs   = millis();
  lastEpochStartMs = sessionStartMs;
  epochMotionAccum = 0.0f;
  epochHrSum = 0; epochHrCount = 0; epochHrAbove = 0;
  continuousQuietEpochs = 0;
  isAsleepConfirmed = false;

  calibState    = CAL_NONE;      // 워밍업이 끝나면 CAL_COLLECT 로 전환
  calibPhaseMs  = sessionStartMs;
  calibBpmSum   = 0;
  calibBpmCount = 0;
  calibAttempts = 0;
  g_restingBpm       = NAN;
  g_onsetHrThreshold = NAN;

  // [변경 4] start 신호를 받은 지금부터 모든 센서 측정 시작
  //          — 처음 SENSOR_WARMUP_MS 동안의 데이터는 전부 버리고 히터도 켜지 않는다
  sessionState = SESS_WARMUP;
  setSensorsActive(true);
  clearFaultPending();
  resetPID();
  Serial.print("# SESSION START  person=");
  Serial.print(g_personId);
  Serial.print("  temp=");
  Serial.print(sessionTemp,1);
  Serial.println("C");
  Serial.print("# 센서 워밍업 ");
  Serial.print(SENSOR_WARMUP_MS / 1000UL);
  Serial.println("초: 모든 센서 데이터를 버리며, 이 구간에는 히터를 켜지 않습니다.");
  Serial.print("# 워밍업 후 ");
  Serial.print(CALIB_COLLECT_MS / 1000UL);
  Serial.println("초 평균을 이번 세션의 안정심박수로 사용합니다.");
  sendServerFlag("SESSION_START", sessionTemp, 0);
}

// 입면 확정 시점 (에폭 로직에서 호출) — 측정 기록 후, 설정 시간만큼 가온 유지(Cooldown)
static void onSleepOnsetConfirmed(unsigned long onsetMs) {
  float solMin = (onsetMs - sessionStartMs) / 60000.0f;
  Serial.print("# SLEEP ONSET detected. SOL=");
  Serial.print(solMin,2);
  Serial.println(" min");

  // [변경 1] 서버로 입면 상태 플래그 전송
  sendServerFlag("SLEEP_ONSET", solMin, isnan(g_restingBpm) ? 0.0f : g_restingBpm);

  recordResult(&g_profile, sessionTemp, solMin);
  saveProfile(g_personId);

  SearchResult sr = nextTemperature(&g_profile);
  Serial.print("@RESULT,");
  Serial.print(g_personId);   Serial.print(',');
  Serial.print(sessionTemp,1);Serial.print(',');
  Serial.print(solMin,2);     Serial.print(',');
  Serial.print(sr.converged?1:0); Serial.print(',');
  Serial.print(sr.bestTemp,1);Serial.print(',');
  Serial.print(sr.bestSol,2); Serial.print(',');
  Serial.println(sr.nextTemp,1);

#if KEEP_HEATING_AFTER_ONSET
  // [변경 6] 입면 판정이 끝났으므로 생체 센서(MPU6050/MAX30102)는 즉시 정지한다.
  //          온도 센서는 가온 유지 구간의 PID 제어와 과열 감시에 필요하므로 남겨두고,
  //          HEATING_DURATION_MS 가 끝나면 히터와 함께 정지시킨다.
  setBioSensorsActive(false);
  cooldownEndMs = millis() + HEATING_DURATION_MS;
  sessionState  = SESS_COOLDOWN;
  Serial.print("# COOLDOWN 진입: 생체 센서 정지, 앞으로 ");
  Serial.print(HEATING_DURATION_MS / 60000UL);
  Serial.println("분간 가온을 유지합니다(온도 센서는 안전 감시를 위해 유지).");
  sendServerFlag("COOLDOWN_START", SETPOINT_C, HEATING_DURATION_MS / 60000.0f);
#else
  // 입면이 확정되면 히터와 모든 센서를 끄고 기기를 종료한다
  manualTempSet = false;
  shutdownDevice("SLEEP_ONSET");
#endif
}

// [변경 2] 세션 최대시간(60분) 내 미입면 — 결과 기록 후 기기 전원 차단
static void finalizeNoOnset() {
  float solMin = SESSION_MAX_MS / 60000.0f;
  Serial.print("# NO ONSET (timeout). SOL capped=");
  Serial.print(solMin,1);
  Serial.println(" min");

  recordResult(&g_profile, sessionTemp, solMin);
  saveProfile(g_personId);
  sendServerFlag("NO_ONSET", solMin, 0);

  manualTempSet = false;
  shutdownDevice("NO_ONSET_TIMEOUT");
}

// 히터 차단 후 기기 전원 종료(딥슬립). 버튼(START_BTN_PIN)을 누르면 재기동.
static void shutdownDevice(const char* reason) {
  pwmWrite(0);
  SETPOINT_C   = 0;
  sessionState = SESS_OFF;
  resetPID();
  setSensorsActive(false);       // [변경 5] 히터와 함께 모든 센서 정지

  Serial.print("# 기기를 종료합니다 (사유: ");
  Serial.print(reason);
  Serial.println(")");
  sendServerFlag("POWER_OFF", 0, 0);
  Serial.flush();
  delay(200);

#if POWER_OFF_USE_DEEP_SLEEP
  rtc_gpio_pullup_en((gpio_num_t)START_BTN_PIN);
  rtc_gpio_pulldown_dis((gpio_num_t)START_BTN_PIN);
  esp_sleep_enable_ext0_wakeup((gpio_num_t)START_BTN_PIN, 0);  // 버튼 누름(LOW) 시 기상
  esp_deep_sleep_start();
#else
  Serial.println("# (딥슬립 비활성화 설정) 히터를 끈 상태로 대기합니다. 리셋하면 재시작됩니다.");
#endif
}

static void updateSession(unsigned long now) {
  if (now < sessionStartMs) return;

  // [변경 4] 워밍업: 센서만 돌리고 데이터는 버린다. 히터는 아직 켜지 않는다.
  if (sessionState == SESS_WARMUP) {
    if (now - sessionStartMs < SENSOR_WARMUP_MS) return;

    sessionState = SESS_RUNNING;
    lastLoggedSkinC = NAN; lastLoggedHeaterC = NAN;   // 첫 유효 샘플이 급상승으로 오판되지 않도록
    clearFaultPending();
    resetPID();
    calibState    = CAL_COLLECT;                     // 이제부터 30초간 안정심박수 수집
    calibPhaseMs  = now;
    calibBpmSum   = 0;
    calibBpmCount = 0;
    epochMotionAccum = 0.0f;
    epochHrSum = 0; epochHrCount = 0; epochHrAbove = 0;
    lastEpochStartMs = now;

    Serial.print("# 센서 워밍업 종료 — 가온 시작(목표 ");
    Serial.print(SETPOINT_C, 1);
    Serial.print("C), 안정심박수 ");
    Serial.print(CALIB_COLLECT_MS / 1000UL);
    Serial.println("초 측정 시작");
    sendServerFlag("WARMUP_DONE", SETPOINT_C, 0);
    return;
  }

  if (sessionState == SESS_RUNNING) {
    updateCalibration(now);
    evaluateEpochAndOnset(now);
    if (sessionState == SESS_RUNNING && (now - sessionStartMs >= SESSION_MAX_MS)) {
      finalizeNoOnset();
    }
  } else if (sessionState == SESS_COOLDOWN) {
    if (now >= cooldownEndMs) {
      Serial.println("# COOLDOWN 종료: 히터/센서 정지");
      manualTempSet = false;
      sendServerFlag("SESSION_DONE", 0, 0);
      shutdownDevice("COOLDOWN_END");
    }
  }
}

// ===========================================================================
// 로깅
// ===========================================================================
static void printCsvHeader() {
  Serial.println("======================================================");
  Serial.println("  ESP32 수면 온도 제어기 부팅 완료 (실시간 모니터링 시작)");
  Serial.println("======================================================");
}

static void logCsv(unsigned long t, float skinC, float heaterC, int duty) {
  Serial.print("[진행상태] ");
  Serial.print("시간:");     Serial.print(t / 1000);  Serial.print("초 | ");
  Serial.print("피부온도:"); Serial.print(isnan(skinC)   ? -99.0 : skinC, 1);   Serial.print("℃ | ");
  Serial.print("히터온도:"); Serial.print(isnan(heaterC) ? -99.0 : heaterC, 1); Serial.print("℃ | ");
  Serial.print("목표:");     Serial.print(SETPOINT_C, 1); Serial.print("℃ | ");

  Serial.print("히터파워:"); Serial.print(100.0f * duty / PWM_MAX, 0); Serial.print("% | ");
  Serial.print("심박수:");   Serial.print(latestBpm, 0); Serial.print("BPM | ");
  Serial.print("안정심박:"); Serial.print(isnan(g_restingBpm) ? 0.0f : g_restingBpm, 0); Serial.print("BPM | ");
  Serial.print("입면기준:"); Serial.print(isnan(g_onsetHrThreshold) ? 0.0f : g_onsetHrThreshold, 0); Serial.print("BPM | ");

  const char* sensorTag = "OFF";
  if (g_bioSensorsActive && g_tempSensorsActive) sensorTag = (sessionState == SESS_WARMUP) ? "WARMUP" : "ON";
  else if (g_tempSensorsActive)                  sensorTag = "TEMP";   // 가온 유지 구간(생체 센서 정지)
  else if (g_bioSensorsActive)                   sensorTag = "BIO";
  Serial.print("센서:");     Serial.print(sensorTag);
  Serial.print(" | ");
  Serial.print("안전:");     Serial.print(stateName(safetyState)); Serial.print(" | ");
  Serial.print("세션:");     Serial.print(sessName(sessionState)); Serial.print(" | ");

  Serial.print("연속수면(분):"); Serial.print(continuousQuietEpochs); Serial.print(" | ");
  Serial.println(isAsleepConfirmed ? "판정: 수면중" : "판정: 깨어있음");
}

static void printReport() {
  Serial.print("# ---- 리포트: "); Serial.print(g_personId);
  Serial.print(" / 기기 "); Serial.print(g_deviceId); Serial.println(" ----");
  Serial.println("# 설정온도 , 평균 수면잠복기(분) , 시도횟수");
  for (int i = 0; i < g_profile.nBins; i++) {
    Serial.print("#   ");
    Serial.print(g_profile.bins[i].temp,1);        Serial.print(" , ");
    Serial.print(binMean(&g_profile.bins[i]),2);   Serial.print(" , ");
    Serial.println(g_profile.bins[i].count);
  }
  SearchResult sr = nextTemperature(&g_profile);
  Serial.print("# 최고성능온도="); Serial.print(sr.bestTemp,1);
  Serial.print("C  다음추천=");    Serial.print(sr.nextTemp,1);
  Serial.println("C");
}

// ===========================================================================
// 시리얼 명령
// ===========================================================================
static void handleSerial(float skinC, float heaterC) {
  static char buf[48];
  static int len = 0;
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
        Serial.print(" bins=");    Serial.println(g_profile.nBins);
      } else if (strcmp(buf,"start") == 0) {
        startSession();
      } else if (strcmp(buf,"abort") == 0) {
        pwmWrite(0);
        SETPOINT_C = 0;
        sessionState = SESS_IDLE;
        manualTempSet = false;
        calibState = CAL_NONE;
        g_restingBpm = NAN; g_onsetHrThreshold = NAN;
        continuousQuietEpochs = 0;
        // FAULT 상태에서는 온도를 계속 감시해야 하므로 센서를 끄지 않는다
        if (safetyState == STATE_NORMAL) setSensorsActive(false);
        Serial.println("# SESSION aborted");
      } else if (strncmp(buf,"set ",4) == 0) {
        sessionTemp = clampSearch(atof(buf+4));
        manualTempSet = true;
        Serial.print("# 세션 온도 수동 지정=");
        Serial.println(sessionTemp,1);
      } else if (strcmp(buf,"whoami") == 0) {
        announceDeviceId();
      } else if (strcmp(buf,"report") == 0) {
        printReport();
      } else if (strcmp(buf,"reset_profile") == 0) {
        eraseProfile(g_personId);
        Serial.println("# profile erased");
      } else if (strcmp(buf,"off") == 0) {
        shutdownDevice("USER_CMD");
      } else if (strcmp(buf,"r") == 0) {
        bool skinOk   = !isnan(skinC)   && skinC   > T_SENSE_MIN_C && skinC   < T_SENSE_MAX_C;
        bool heaterOk = !isnan(heaterC) && heaterC > T_SENSE_MIN_C && heaterC < T_SENSE_MAX_C;
        bool tempsSafe = skinOk && heaterOk && (skinC < SKIN_REARM_C) && (heaterC < HEATER_REARM_C);
        if (safetyState != STATE_NORMAL && tempsSafe) {
          safetyState = STATE_NORMAL;
          clearFaultPending();
          resetPID();
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
// setup / loop
// ===========================================================================
void setup() {
  Serial.begin(115200);
  delay(300);

  pwmSetup();
  pwmWrite(0);
  SETPOINT_C = 0;
  analogReadResolution(12);
  analogSetPinAttenuation(NTC_PIN, ADC_11db);
  rtc_gpio_deinit((gpio_num_t)START_BTN_PIN);   // 딥슬립에서 깬 뒤 일반 GPIO로 복귀
  pinMode(START_BTN_PIN, INPUT_PULLUP);

  Wire.begin();   // SDA=21, SCL=22 (기본)

  g_mpuOk = mpu.begin();
  if (g_mpuOk) mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
  Serial.println(g_mpuOk ? "# MPU6050 OK" : "# MPU6050 NOT found");

  g_mlxOk = mlx.begin();
  Serial.println(g_mlxOk ? "# MLX90614 OK" : "# MLX90614 NOT found");

  // MAX30102 초기화 (이때 I2C 통신 속도가 400kHz로 빨라짐)
  g_maxOk = particleSensor.begin(Wire, I2C_SPEED_FAST);

  // MLX90614 센서와의 호환성을 위해 I2C 통신 속도를 100kHz로 원상 복구
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

  // [변경 4] 검출만 해두고 start 전까지는 모든 센서를 정지시켜 둔다
  setSensorsActive(false);

  profileClear(&g_profile);
  loadProfile(g_personId);

  if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0)
    Serial.println("# 버튼 입력으로 딥슬립에서 재기동했습니다.");

  buildDeviceId();
  Serial.println("# ESP32 Sleep-Onset Temperature Optimizer [실기 v7]");
  Serial.print("# 기기 ID(칩 MAC 기반) = "); Serial.println(g_deviceId);
  announceDeviceId();
  Serial.print("# SkinHardLimit="); Serial.print(SKIN_HARD_LIMIT_C,1);
  Serial.print("C HeaterHardLimit="); Serial.print(HEATER_HARD_LIMIT_C,1);
  Serial.print("C SearchRange="); Serial.print(SEARCH_MIN,1);
  Serial.print("-"); Serial.print(SEARCH_MAX,1); Serial.println("C");
  Serial.print("# FaultPersist="); Serial.print(FAULT_PERSIST_MS/1000UL);
  Serial.println("s (이상 온도가 이 시간 이상 지속될 때만 FAULT 확정)");
  Serial.print("# Epoch="); Serial.print(EPOCH_DURATION_MS/60000UL);
  Serial.print("min RequiredQuietEpochs="); Serial.print(REQUIRED_SLEEP_EPOCHS);
  Serial.print(" HeatingDurationAfterOnset="); Serial.print(HEATING_DURATION_MS/60000UL);
  Serial.println("min");
  Serial.print("# 센서: start 전까지 정지, start 후 "); Serial.print(SENSOR_WARMUP_MS/1000UL);
  Serial.println("s 워밍업(데이터 폐기, 히터 OFF)");
  Serial.print("# HR 캘리브레이션: 워밍업 후 수집 "); Serial.print(CALIB_COLLECT_MS/1000UL);
  Serial.print("s, 입면기준 = 안정심박수 - "); Serial.print(HR_DROP_BPM,0);
  Serial.println(" BPM");
  Serial.print("# SessionTimeout="); Serial.print(SESSION_MAX_MS/60000UL);
  Serial.println("min (미입면 시 히터/센서 정지 후 기기 전원 종료)");
#if KEEP_HEATING_AFTER_ONSET
  Serial.print("# 입면 확정 시: 생체 센서 즉시 정지 + ");
  Serial.print(HEATING_DURATION_MS/60000UL);
  Serial.println("분 가온 유지 후 히터/온도 센서 정지 및 기기 전원 종료");
#else
  Serial.println("# 입면 확정 시: 즉시 히터/센서 정지 후 기기 전원 종료");
#endif
  Serial.println("# cmds: id <name> | whoami | start | abort | set <c> | report | reset_profile | off | r");

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
  if (btnPrev == HIGH && btn == LOW
      && (sessionState == SESS_IDLE || sessionState == SESS_OFF)) startSession();
  btnPrev = btn;

  // --- 제어 주기 (1초) ---
  if (now - lastControlMs >= CONTROL_PERIOD_MS) {
    lastControlMs = now;

    // [변경 4] 센서 정지 중에는 온도도 측정하지 않는다.
    //          워밍업(SESS_WARMUP) 중에는 읽기만 하고 안전 판정/PID 에는 쓰지 않는다.
    bool accepted = sensorDataAccepted();
    float heaterC = readHeaterTempC();                                        // NTC: 히터 표면(안전감시용)
    float skinC   = (g_tempSensorsActive && g_mlxOk) ? mlx.readObjectTempC() : NAN; // MLX90614: 피부(제어 목표)

    if (accepted) {
      safetyState = evaluateSafety(skinC, heaterC, lastLoggedSkinC, lastLoggedHeaterC, safetyState, now);
    }
    handleSerial(skinC, heaterC);

    // 세션/입면 갱신
    updateSession(now);

    // 제어 출력 (워밍업이 끝나 유효한 온도가 확보된 뒤에만 가열)
    int duty = 0;
    bool heaterAllowed = accepted
                       && (safetyState == STATE_NORMAL)
                       && !g_preFaultCutoff                // 이상 온도 감시 중에는 가열 정지
                       && (sessionState == SESS_RUNNING || sessionState == SESS_COOLDOWN)
                       && (SETPOINT_C > 0);
    if (heaterAllowed) {
      float out = computePID(SETPOINT_C, skinC, CONTROL_PERIOD_MS/1000.0f);
      duty = (int)(out + 0.5f);
      pidPrimed = true;
    } else {
      resetPID();
    }
    if (safetyState != STATE_NORMAL || g_preFaultCutoff) duty = 0;  // ★ 하드 컷오프 강제 ★
    pwmWrite(duty);

    if (accepted) {                 // 워밍업/정지 구간의 값은 다음 주기 비교에 쓰지 않는다
      lastLoggedSkinC   = skinC;
      lastLoggedHeaterC = heaterC;
    }

    // 세션이 없고 FAULT 도 해소된 상태면 센서를 정지시킨다
    if ((g_bioSensorsActive || g_tempSensorsActive) && safetyState == STATE_NORMAL
        && (sessionState == SESS_IDLE || sessionState == SESS_OFF)) {
      setSensorsActive(false);
    }

    if (now - lastLogMs >= LOG_PERIOD_MS) {
      lastLogMs = now;
      logCsv(now, skinC, heaterC, duty);
    }
  }
}
