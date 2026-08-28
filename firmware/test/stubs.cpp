#include <Arduino.h>
#include <Wire.h>
#include <Preferences.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_MLX90614.h>
#include <MAX30105.h>
#include <heartRate.h>
#include <esp_sleep.h>
#include <driver/rtc_io.h>
#include <cstdio>

unsigned long g_fakeMillis = 0;
bool g_deepSleepCalled = false;
bool g_verbose = false;

unsigned long millis() { return g_fakeMillis; }
void delay(unsigned long) {}
void pinMode(int,int) {}
int digitalRead(int) { return HIGH; }
void analogReadResolution(int) {}
void analogSetPinAttenuation(int,int) {}
uint32_t analogReadMilliVolts(int) { return 1650; }
void ledcAttach(int,int,int) {}
int g_lastDuty = 0;
void ledcWrite(int, int d) { g_lastDuty = d; }

SerialClass Serial;
void SerialClass::begin(unsigned long) {}
int SerialClass::available() { return 0; }
int SerialClass::read() { return -1; }
void SerialClass::flush() {}
void SerialClass::print(const char* s) { if (g_verbose) printf("%s", s); }
void SerialClass::print(char c) { if (g_verbose) printf("%c", c); }
void SerialClass::print(int v) { if (g_verbose) printf("%d", v); }
void SerialClass::print(long v) { if (g_verbose) printf("%ld", v); }
void SerialClass::print(unsigned long v) { if (g_verbose) printf("%lu", v); }
void SerialClass::print(double v, int d) { if (g_verbose) printf("%.*f", d, v); }
void SerialClass::print(float v, int d) { if (g_verbose) printf("%.*f", d, (double)v); }
void SerialClass::println(const char* s) { if (g_verbose) printf("%s\n", s); }
void SerialClass::println(int v) { if (g_verbose) printf("%d\n", v); }
void SerialClass::println(long v) { if (g_verbose) printf("%ld\n", v); }
void SerialClass::println(unsigned long v) { if (g_verbose) printf("%lu\n", v); }
void SerialClass::println(double v, int d) { if (g_verbose) printf("%.*f\n", d, v); }
void SerialClass::println(float v, int d) { if (g_verbose) printf("%.*f\n", d, (double)v); }
void SerialClass::println() { if (g_verbose) printf("\n"); }

TwoWire Wire;
void TwoWire::begin() {}
void TwoWire::setClock(uint32_t) {}

bool Preferences::begin(const char*, bool) { return true; }
void Preferences::end() {}
size_t Preferences::getBytesLength(const char*) { return 0; }
size_t Preferences::getBytes(const char*, void*, size_t) { return 0; }
size_t Preferences::putBytes(const char*, const void*, size_t n) { return n; }
bool Preferences::remove(const char*) { return true; }

bool Adafruit_MPU6050::begin() { return false; }
void Adafruit_MPU6050::setAccelerometerRange(int) {}
bool g_mpuAsleep = true;
void Adafruit_MPU6050::enableSleep(bool e) { g_mpuAsleep = e; }
bool Adafruit_MPU6050::getEvent(sensors_event_t*, sensors_event_t*, sensors_event_t*) { return true; }
bool Adafruit_MLX90614::begin() { return false; }
double Adafruit_MLX90614::readObjectTempC() { return 30.0; }
bool g_mlxAsleep = true;
void Adafruit_MLX90614::enterSleepMode(bool sl) { g_mlxAsleep = sl; }
bool MAX30105::begin(TwoWire&, uint32_t) { return false; }
void MAX30105::setup() {}
void MAX30105::setPulseAmplitudeRed(uint8_t) {}
void MAX30105::setPulseAmplitudeGreen(uint8_t) {}
long MAX30105::getIR() { return 50000; }
bool g_maxShutdown = true;
void MAX30105::shutDown() { g_maxShutdown = true; }
void MAX30105::wakeUp() { g_maxShutdown = false; }
bool g_forceBeat = false;
bool checkForBeat(long) { return g_forceBeat; }

esp_sleep_wakeup_cause_t esp_sleep_get_wakeup_cause() { return ESP_SLEEP_WAKEUP_UNDEFINED; }
int esp_sleep_enable_ext0_wakeup(gpio_num_t, int) { return 0; }
void esp_deep_sleep_start() { g_deepSleepCalled = true; }
int rtc_gpio_pullup_en(gpio_num_t) { return 0; }
int rtc_gpio_pulldown_dis(gpio_num_t) { return 0; }
int rtc_gpio_deinit(gpio_num_t) { return 0; }
