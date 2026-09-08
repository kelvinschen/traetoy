idf_component_register(SRCS "companion_ble.c" "companion_ble_wire.c"
    INCLUDE_DIRS "." REQUIRES bt nvs_flash mbedtls esp_timer)
