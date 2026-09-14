set(CODEX "${CMAKE_CURRENT_LIST_DIR}/../../codex/main")
set(MINIZ "${CMAKE_CURRENT_LIST_DIR}/../vendor/miniz")
idf_component_register(SRCS "main.c" "pet_codec.c" "pet_behavior.c" "pet_ui.c" "pet_pages.c" "pet_sound_pcm.c" "pet_assets.c" "pet_font.c"
    "${CODEX}/companion_protocol.c" "${CODEX}/companion_tiles.c" "${CODEX}/companion_alerts.c" "${CODEX}/companion_info.c"
    "${MINIZ}/miniz_tinfl.c" "${MINIZ}/miniz.c"
    INCLUDE_DIRS "." "${CODEX}" "${MINIZ}"
    REQUIRES bsp passport_ble esp_driver_usb_serial_jtag esp_timer esp_lcd
    EMBED_FILES "../assets/bloub.bin")
target_compile_definitions(${COMPONENT_LIB} PRIVATE COMPANION_ALERT_KIND_MAX=3 MINIZ_NO_ARCHIVE_APIS MINIZ_NO_DEFLATE_APIS MINIZ_NO_ZLIB_APIS MINIZ_NO_STDIO
    tinfl_decompress=pet_tinfl_decompress)
