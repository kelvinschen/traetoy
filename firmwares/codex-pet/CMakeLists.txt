cmake_minimum_required(VERSION 3.16)
get_filename_component(PASSPORT_ROOT "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
set(PASSPORT_BOARD "${PASSPORT_ROOT}/shared/boards/ai-passport")
set(EXTRA_COMPONENT_DIRS "${PASSPORT_BOARD}/components")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
idf_build_set_property(BOOTLOADER_EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../shared/boards/ai-passport/bootloader_components/" APPEND)
project(FoloToy-AI-Passport)

# Keep symbols for on-device diagnostics and reject the ROM miniz ABI collision.
add_custom_command(TARGET ${CMAKE_PROJECT_NAME}.elf POST_BUILD
    COMMAND ${PYTHON} "${CMAKE_CURRENT_LIST_DIR}/tools/check_link.py" "${CMAKE_NM}" "$<TARGET_FILE:${CMAKE_PROJECT_NAME}.elf>"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_CURRENT_LIST_DIR}/build"
    COMMAND ${CMAKE_COMMAND} -E copy "$<TARGET_FILE:${CMAKE_PROJECT_NAME}.elf>" "${CMAKE_CURRENT_LIST_DIR}/build/pet.elf"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_BINARY_DIR}/${CMAKE_PROJECT_NAME}.map" "${CMAKE_CURRENT_LIST_DIR}/build/pet.map")
