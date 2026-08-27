#pragma once
struct vec3 { float x, y, z; };
struct sensors_event_t { vec3 acceleration; vec3 gyro; float temperature; };
