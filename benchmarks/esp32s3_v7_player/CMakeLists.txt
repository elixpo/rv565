# RV565 version 7 playback benchmark for the Oreo Badge (ESP32-S3 N16R8,
# 320x240 ST7789). Builds the player around one clip, chosen at configure time:
#   idf.py -DRV565_CLIP=/abs/path/clip.rv565 -DRV565_OVERLAP=1 build
# RV565_OVERLAP=1 inflates on core 1 (dual-core, the default); 0 is serial.
cmake_minimum_required(VERSION 3.16)
# The library is this checkout, used directly (the component name is the
# checkout's folder name, rv565).
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../..")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(rv565_v7_player)
