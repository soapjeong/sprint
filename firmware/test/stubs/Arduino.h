#pragma once
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <string>
#define HIGH 1
#define LOW 0
#define INPUT_PULLUP 2
#define ADC_11db 3
typedef uint8_t byte;
unsigned long millis();
void delay(unsigned long);
void pinMode(int,int);
int digitalRead(int);
void analogReadResolution(int);
void analogSetPinAttenuation(int,int);
uint32_t analogReadMilliVolts(int);
void ledcAttach(int,int,int);
void ledcWrite(int,int);
class SerialClass {
public:
  void begin(unsigned long);
  int available();
  int read();
  void flush();
  void print(const char*);
  void print(char);
  void print(int);
  void print(long);
  void print(unsigned long);
  void print(double, int=2);
  void print(float, int=2);
  void println(const char*);
  void println(int);
  void println(long);
  void println(unsigned long);
  void println(double, int=2);
  void println(float, int=2);
  void println();
};
extern SerialClass Serial;
