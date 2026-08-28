#pragma once
#include <Adafruit_Sensor.h>
#define MPU6050_RANGE_2_G 0
class Adafruit_MPU6050 {
public:
  bool begin();
  void setAccelerometerRange(int);
  void enableSleep(bool);
  bool getEvent(sensors_event_t*, sensors_event_t*, sensors_event_t*);
};
