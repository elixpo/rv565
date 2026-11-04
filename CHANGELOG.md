# Changelog

All notable changes to RV565 are listed here. The project follows
[semantic versioning](https://semver.org).

## Unreleased

- RP2 port runs on hardware: first bring-up on a Raspberry Pi Pico 2 with a
  2.0" 320x240 ST7789, 24 FPS with zero misses on the test pattern.
  - Command bytes (the init sequence and each frame's RAMWR) now go out at
    10 MHz; at 37.5 MHz the panel misread them and stayed blank. Pixel data
    still runs at the configured rate.
  - SPI mode 3 instead of mode 0: the RP2350's PL022 leaves a gap after every
    byte in mode 0. Measured frame time 39.71 ms → 33.57 ms; the transfer
    now runs at 99.4% of the 37.5 MHz wire time (83.8% before).
- RP2350 benchmark: wiring notes (short wires, a series resistor on SCL) and
  `st7789_test.py`, a MicroPython wiring check.

## 1.1.0 — 2026-11-01

- Any ST7789 module: the ESP32 and RP2 display configs take an
  `rv565_panel_t` (size, controller offset, MADCTL rotation, inversion), with
  presets for 320x240, 240x320, 240x240, 135x240 and 240x135 in
  `rv565_panel.h`. A zeroed panel keeps the 1.0 behaviour (320x240
  landscape), so existing code is unchanged. Only 320x240 is verified on
  hardware so far.
- Examples show where to pick the panel.
- `examples/TFT_eSPI_Player` and `examples/LovyanGFX_Player`: keep your
  display library for the panel and use RV565 for decoding (compiled in CI,
  not yet run on hardware).
- Python package `rv565` (`python/`): read, write, verify and schedule-check
  files, the `rv565` command (which `tools/rv565.py` now wraps), and a Pillow
  plugin (`import rv565.pillow`). Published to PyPI with the same version.
- `contrib/`: file type registration for `.rv565` (`file(1)` magic,
  shared-mime-info `video/x-rv565`, PRONOM fields) and an FFmpeg patch
  (decoder, encoder, demuxer, muxer), prepared for upstream submission.
- `docs/FORMAT.md` gains an identification section (extension, MIME type,
  signature).

## 1.0.0 — 2026-10-31

First stable release. The container format (version 6) and the public API are
now covered by the 1.x compatibility promise; see *Versioning* in the README.

- Core: header parsing and validation, O(1) frame index, exact-length
  inflate, nearest-neighbour stripe scaler, decode-cost model,
  schedulability check, absolute-deadline pacer.
- Player: two-stripe DMA pipeline with optional second-core decoding.
- ESP32 port (ESP-IDF and Arduino-ESP32), verified on the ESP32-S3 badge.
- RP2040/RP2350 port (Pico SDK and Arduino-Pico), experimental: compiled in
  CI, not yet run on hardware.
- `tools/rv565.py`: encode, info, verify, c-array, testpattern.
- Published in the Arduino Library Manager.

## 0.1.0 — 2026-10-31

Initial listing in the Arduino Library Manager.
