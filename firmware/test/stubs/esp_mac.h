#pragma once
#include <cstdint>
#define ESP_OK 0
typedef int esp_err_t;
typedef enum { ESP_MAC_WIFI_STA = 0 } esp_mac_type_t;
esp_err_t esp_read_mac(uint8_t* mac, esp_mac_type_t type);
