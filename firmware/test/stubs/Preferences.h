#pragma once
#include <Arduino.h>
class Preferences {
public:
  bool begin(const char*, bool=false);
  void end();
  size_t getBytesLength(const char*);
  size_t getBytes(const char*, void*, size_t);
  size_t putBytes(const char*, const void*, size_t);
  bool remove(const char*);
};
