# Changelog

All notable changes to RV565 are listed here. The project follows
[semantic versioning](https://semver.org).

## Unreleased

Version 2.0.0 introduces RV565 format version 7 (`docs/FORMAT.md`): the
header declares one of nine pixel formats (`rgb565be`, `rgb565le`, `rgb444`,
`rgb666`, `rgb888`, `gray8`, `gray4`, `mono`, `mono_vpage`) and a codec
(stored or zlib), frames are keyframes, exact XOR deltas or repeats, and a
keyframe interval keeps seeking bounded. Version 6 files stay readable
everywhere.

- Conformance vectors in `tests/data/v7` (27 valid files with each decoded
  frame's SHA-256, 20 invalid files with the stage that must reject them),
  written and checked by `tools/make_conformance.py`. Every implementation
  is tested against them in CI.
- Python package 2.0.0, the reference implementation: `rv565.write()` takes
  `pixel_format`, `codec`, `keyframe_interval` and `version=6`;
  `rv565.convert()` and `rv565.to_rgb888()` handle every pixel format;
  `Clip.frame_type()`, and `Header` gains `version`, `header_size`,
  `pixel_format`, `codec` and `keyframe_interval`. `rv565 encode` and
  `testpattern` take `--format`, `--codec`, `--keyframe-interval` and `--v6`;
  `encode` now writes version 7 with one keyframe per second by default.
  `rv565 info` reports the format, codec and frame types. The Pillow plugin
  opens every pixel format and saves with the same options.
- `docs/RESULTS_V7.md`: on the paper's film windows, version 7 with one
  keyframe per second is 4.8–5.5× (W90) and 1.8–2.0× (W360) smaller than
  version 6. File sizes only; playback on hardware is not measured yet.

Version 2.0.0 of the C library reads RV565 format version 7
(`docs/FORMAT.md`) and keeps reading version 6.

- Format version 7 in the core (`rv565.h`): nine pixel formats
  (`rv565_pixel_format_t`, `RV565_PIXEL_RGB565BE` … `RV565_PIXEL_MONO_VPAGE`),
  codecs stored and zlib (`rv565_codec_t`), keyframe, delta and repeat
  frames (`rv565_frame_type_t`) and the keyframe interval. Still
  allocation-free; the zlib path still uses the ESP32 ROM tinfl or the
  bundled one.
- `rv565_open()` validates everything the spec checks at open time in its one
  linear scan: reserved pixel format, codec or frame type, `K` = 0, a missing
  keyframe at a multiple of `K`, a repeat with a body, a stored body that is
  not `S` bytes, truncation and trailing bytes. Rates up to 60 FPS in
  version 7 (30 in version 6).
- New: `rv565_decode(clip, i, prev, dst, dst_len, scratch, scratch_len)`
  (keyframe, delta against `prev`, repeat; in place with a scratch buffer
  for zlib deltas, or between two buffers without one), `rv565_seek()`
  (from the keyframe at or before a frame), `rv565_frame_type()`,
  `rv565_keyframe_at_or_before()`, `rv565_row_bytes()`,
  `rv565_bytes_per_pixel()`, and `rv565_scale_stripe_bpp()` for 1-, 2- and
  3-byte pixels (packed formats are not scaled).
- Player: deltas decode into the frame buffer that is not on screen, using
  the presented frame as their base; repeats decode nothing and are not sent
  to the display again; after a pacer skip the player applies the skipped
  records the delta chain needs (at most `K` − 1) without showing them.
  `rv565_frame_stats_t` gains `decoded` and `sent`. Only RGB565 big-endian
  clips play (the bundled ST7789 drivers run the panel in RGB565); other
  formats return `RV565_ERR_UNSUPPORTED` from `rv565_player_init()`.
- `rv565_check_schedule()` models repeats as costing no decode, and applies
  the cost model to the body length (type byte excluded).
- MicroPython module (`ports/micropython`): `inflate_delta(body, prev, frame[,
  scratch])`, `xor_frame(frame, other)` and `FORMAT_VERSION`;
  `inflate_frame()` is unchanged.
- Tests: `tests/test_conformance.c` and `tests/check_conformance.py` decode
  every vector in `tests/data/v7` in order (in place and between two
  buffers) and by seeking, compare each frame's SHA-256 with the manifest,
  and check that every invalid file is rejected at the right stage with the
  matching status. `make -C tests` runs them, and the player test now plays
  the rgb565be vectors. CI also runs the tests under ASan/UBSan and checks
  the vectors with `tools/make_conformance.py --check`.

API changes from 1.x (source-incompatible where noted):

- `rv565_header_t` gains `version`, `header_size`, `pixel_format`, `codec`
  and `keyframe_interval`. Code that fills a header by hand must set them.
- `rv565_frame_bytes()` is a function instead of a static inline and follows
  the pixel format.
- `RV565_MAX_FPS` is 60 (version 7); `RV565_MAX_FPS_V6` is 30.
  `RV565_HEADER_SIZE` is replaced by `RV565_HEADER_SIZE_V6` (12) and
  `RV565_HEADER_SIZE_V7` (16, the minimum).
- `rv565_clip_t.index[i]` points just past each record's length: at the type
  byte in version 7. `rv565_payload()` returns the body without the type
  byte (length 0 for a repeat).
- `rv565_decode_frame(clip, i, dst, len)` decodes in place: a keyframe on its
  own, otherwise `dst` must hold frame i−1, and a zlib delta returns
  `RV565_ERR_ARG` (use `rv565_decode()` with scratch or two buffers).
- `rv565_parse_header()` returns `RV565_ERR_TRUNCATED` (not
  `RV565_ERR_ARG`) for fewer than 12 bytes.
- New status codes: `RV565_ERR_FORMAT`, `RV565_ERR_KEYFRAME`,
  `RV565_ERR_RECORD`, `RV565_ERR_UNSUPPORTED`.
- `rv565_decoder_ops_t.start` takes the previous frame:
  `start(ctx, index, prev, dst, dst_len)`, and the struct gains an optional
  `decode` hook for the serial path. Backends call `rv565_decode(clip,
  index, prev, dst, dst_len, NULL, 0)`.
- `rv565_player_t`: `frames[1]` is required for clips with zlib deltas,
  even on the serial path; the state fields `ready_frame` and the meaning of
  `current` changed (`held[]`, `gen[]`, `sent`, `sent_gen`).

- CircuitPython library 2.0.0 (`ports/circuitpython/`): reads format
  version 7 as well as version 6, with every pixel format, the stored and
  zlib codecs, and keyframe, XOR delta and repeat frames, validated on open
  and indexing as the reference does, and checked in host tests against every
  conformance vector in `tests/data/v7` (in order and by random seeks). It
  decodes into one reused frame buffer, so `Clip.frame()` returns a buffer
  that the next call overwrites, and XORs deltas in 2 KiB chunks through long
  integers. `Player` shows `rgb565be`, `rgb565le`, `gray8`, `gray4` and
  `mono`, and `DirectPlayer` sends `rgb565be` and `rgb666` (COLMOD 0x66);
  both skip repeat frames and name the supported formats for any other clip.
  The version 7 paths have not yet run on a board.
- Experimental CircuitPython library, `ports/circuitpython/`
  (`circuitpython_rv565`): reads version 6 files from a path, file object or
  bytes with a lazily built frame index, inflates with the built-in `zlib`,
  and plays through `displayio` (`Player`) or straight to an ST7789 over its
  bus (`DirectPlayer`), paced to the clip's rate with frame skipping. Host
  tests with CPython and fake `displayio`; not yet run on a board. Expect a
  few FPS ([#30](https://github.com/elixpo/rv565/issues/30)).

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
