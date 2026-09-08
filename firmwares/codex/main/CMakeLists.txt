idf_component_register(
    SRCS "main.c" "companion_info.c" "companion_info_ui.c" "companion_protocol.c" "companion_alerts.c" "companion_tiles.c" "companion_refresh.c" "companion_ble.c" "companion_ble_wire.c" "codex_logo.c"
         "../assets/fonts/montserrat_medium_13_digits.c"
         "../assets/fonts/montserrat_medium_13_ascii.c"
         "../assets/fonts/montserrat_bold_16_ascii.c"
         "../assets/fonts/noto_info_16.c"
         "ui_pixel.c"
         "ui_pixel_math.c"
         "demo_display.c"
         "demo_button.c"
         "demo_audio.c"
         "demo_battery.c"
         "demo_radio.c"
         "demo_wifi.c"
         "demo_ble.c"
         "demo_low_power.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_usb_serial_jtag bsp bt esp_event esp_hw_support esp_netif esp_timer esp_wifi nvs_flash mbedtls
)
