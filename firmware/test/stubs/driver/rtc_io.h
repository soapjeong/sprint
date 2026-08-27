#pragma once
#include <esp_sleep.h>
int rtc_gpio_pullup_en(gpio_num_t);
int rtc_gpio_pulldown_dis(gpio_num_t);
int rtc_gpio_deinit(gpio_num_t);
