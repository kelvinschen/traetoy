#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
typedef bool (*companion_ble_receive_fn)(const char *line,uint32_t session,uint32_t counter);
esp_err_t companion_ble_start(companion_ble_receive_fn receive);
/* USB-only provisioning; key never leaves the device through BLE/readback. */
bool companion_ble_provision(const char *hex,char identity[13]);
void companion_ble_reply(uint32_t session,uint32_t counter,const char *line);
void companion_ble_tick(void);

/* True only after application authentication on the current GATT connection. */
bool companion_ble_connected(void);
