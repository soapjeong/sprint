#pragma once
#include <Arduino.h>
class TwoWire {
 public:
  void begin();
  void begin(int sda, int scl);
  void setClock(uint32_t);
};
extern TwoWire Wire;
