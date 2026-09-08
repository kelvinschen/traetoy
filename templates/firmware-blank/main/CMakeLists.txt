idf_component_register(SRCS "main.c" INCLUDE_DIRS "."
    REQUIRES bsp passport_ble esp_driver_usb_serial_jtag esp_timer)
