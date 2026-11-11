# Changelog

All notable changes to RV565 are listed here. The project follows
[semantic versioning](https://semver.org).

## Unreleased

- Experimental CircuitPython library, `ports/circuitpython/`
  (`circuitpython_rv565`): reads version 6 files from a path, file object or
  bytes with a lazily built frame index, inflates with the built-in `zlib`,
  and plays through `displayio` (`Player`) or straight to an ST7789 over its
  bus (`DirectPlayer`), paced to the clip's rate with frame skipping. Host
  tests with CPython and fake `displayio`; not yet run on a board. Expect a
  few FPS ([#30](https://github.com/elixpo/rv565/issues/30)).
- `contrib/`: the FFmpeg patches (now two, `avcodec` and `avformat`) read
  and write format version 7, with every pixel format, stored or zlib frames,
  keyframe/delta/repeat frames and keyframe seeking, and still read and write
  version 6; they pass the `tests/data/v7` conformance vectors and FATE. The
  `file(1)`, shared-mime-info, PRONOM and Kaitai Struct signatures recognise
  version 7 as well as version 6.

## 1.2.0 — 2026-11-04

- RP2350 cost model `RV565_COST_RP2350_180x135` (8.108 ms + 0.2446 µs/byte,
  r² 0.9984), measured on a Pico 2 with the paper's method; results in
  `docs/RESULTS_RP2350.md`. Dual-core playback runs at 24 FPS with zero
  misses on both film windows; the serial path cannot (every frame late).
- The RP2 port is no longer experimental on the RP2350 and joins the 1.x
  compatibility promise; on the RP2040 it compiles but is not yet run.
- Python: `COST_RP2350_180x135`, and `rv565 info --chip esp32s3|rp2350` picks
  the cost model and that chip's measured display transfer.
- Bundled inflate (RP2 and other non-ESP32 targets) keeps its ~11 KB
  decompressor in static memory instead of on the stack. On the RP2040/RP2350
  core 0 has a 2 KB stack, so inflating there (serial mode, or the Pico
  example's single-core path) overflowed it. The ESP32 ROM path is unchanged.
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
