#pragma once
#include <Arduino.h>
class TwoWire { public: void begin(); void setClock(uint32_t); };
extern TwoWire Wire;
