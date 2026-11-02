# RV565 RP2350 benchmark (Raspberry Pi Pico 2). Build with
#   cmake -B build -DPICO_BOARD=pico2 -DRV565_OVERLAP=1 && cmake --build build -j
# The clip is benchmarks/rp2350_video_dma/video.rv565 unless -DRV565_VIDEO=... is given.
cmake_minimum_required(VERSION 3.13)
include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)
project(rv565_rp2350_bench C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

set(RV565_VIDEO "${CMAKE_CURRENT_LIST_DIR}/video.rv565" CACHE FILEPATH "RV565 clip embedded in flash")
set(RV565_OVERLAP 1 CACHE STRING "1: inflate on core 1 (dual-core); 0: serial path")

if(NOT EXISTS "${RV565_VIDEO}")
    message(FATAL_ERROR "No clip at ${RV565_VIDEO}. Encode one, e.g.\n"
        "  python3 tools/encode_video_benchmark.py bbb.mp4 benchmarks/rp2350_video_dma/video.rv565 --start 90 --seconds 4")
endif()
file(SIZE "${RV565_VIDEO}" RV565_VIDEO_BYTES)
# The Pico 2 has 4 MiB of flash; leave room for the program.
if(RV565_VIDEO_BYTES GREATER 3800000)
    message(FATAL_ERROR "Clip is ${RV565_VIDEO_BYTES} bytes; the Pico 2 fits about 3.8 MB. Encode fewer --seconds.")
endif()

configure_file(video.S.in ${CMAKE_CURRENT_BINARY_DIR}/video.S @ONLY)
set_source_files_properties(${CMAKE_CURRENT_BINARY_DIR}/video.S PROPERTIES OBJECT_DEPENDS "${RV565_VIDEO}")

add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/../.. rv565)

add_executable(rv565_rp2350_bench main.c ${CMAKE_CURRENT_BINARY_DIR}/video.S)
target_compile_definitions(rv565_rp2350_bench PRIVATE RV565_OVERLAP=${RV565_OVERLAP})
target_link_libraries(rv565_rp2350_bench rv565 pico_stdlib hardware_clocks hardware_spi)
pico_enable_stdio_usb(rv565_rp2350_bench 1)
pico_enable_stdio_uart(rv565_rp2350_bench 0)
pico_add_extra_outputs(rv565_rp2350_bench)
