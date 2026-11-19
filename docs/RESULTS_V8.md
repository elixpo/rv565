# Format version 8: region deltas against version 7 and ZMBV

Measured 2026-11-20 with `tools/compare_zmbv.py` (reproduce below). Each clip
is 10 seconds at 24 FPS (240 frames), lossless, from the same RGB565
little-endian frames, with a keyframe every second and zlib level 9:

- **UI**: `tools/make_ui_clip.py`, a status screen with a clock, a progress
  bar, a spinner and a scrolling ticker.
- **W90** and **W360**: the paper's film windows of *Big Buck Bunny* (480p),
  from 90 s and 360 s: little and a lot of motion.

**Pixels sent** is the share of the frame a player transfers to the display
per frame, and **windows** the number of display windows (an SPI panel's
column and row address commands and a new transfer) that takes. For RV565 it
is what the file says changed: a keyframe or delta is the whole frame, a
partial delta a window per run of changed bands, a region delta a window per
changed band covering only its changed range. For ZMBV (FFmpeg's encoder,
`-g 24 -compression_level 9`, 16x16 blocks) the player is given the best
case: it skips every block identical to the previous frame and sends each
other block as its own window. Real ZMBV players send whole frames.

## 320x240 (the panel's native size)

| Clip | Format | Size | Pixels sent | Windows per frame |
| --- | --- | ---: | ---: | ---: |
| UI | RV565 version 7 | 981,793 B | 35.7% | 3.2 |
| UI | **RV565 version 8** | 940,714 B | **14.7%** | 9.6 |
| UI | ZMBV, best-case player | **886,544 B** | 16.7% | 50.2 |
| W90 | RV565 version 7 | 3,404,411 B | 87.1% | 2.1 |
| W90 | **RV565 version 8** | **3,237,228 B** | 37.7% | 24.8 |
| W90 | ZMBV, best-case player | 3,437,328 B | **36.0%** | 108.0 |
| W360 | RV565 version 7 | 14,629,037 B | 99.6% | 1.0 |
| W360 | **RV565 version 8** | 14,609,075 B | 87.7% | 24.3 |
| W360 | ZMBV, best-case player | **14,507,506 B** | **86.0%** | 258.0 |

## 180x135 (the paper's size)

| Clip | Format | Size | Pixels sent | Windows per frame |
| --- | --- | ---: | ---: | ---: |
| UI | RV565 version 7 | 125,802 B | 44.2% | 2.9 |
| UI | **RV565 version 8** | 114,890 B | **17.1%** | 7.0 |
| UI | ZMBV, best-case player | **83,482 B** | 25.1% | 31.9 |
| W90 | RV565 version 7 | 1,177,140 B | 90.7% | 1.5 |
| W90 | **RV565 version 8** | **1,138,690 B** | **42.1%** | 14.6 |
| W90 | ZMBV, best-case player | 1,217,570 B | 46.2% | 46.5 |
| W360 | RV565 version 7 | 4,442,863 B | 99.8% | 1.0 |
| W360 | **RV565 version 8** | 4,442,068 B | **89.9%** | 10.9 |
| W360 | ZMBV, best-case player | **4,430,312 B** | 91.4% | 97.1 |

At 180x135 the frame isn't a whole number of 16x16 blocks; ZMBV's edge blocks
are counted at their clipped size.

## What this shows

- **Region deltas send 2.2–2.6× fewer pixels than version 7** on the UI clip
  and the low-motion film, and 10–12% fewer on high-motion film, where most
  of every band changes. Version 7 sent whole rows; version 8 sends each band's
  changed range.
- **The same pixels as a perfect ZMBV player, in far fewer windows.** At
  320x240 version 8 sends within 2 points of ZMBV's best case on every clip
  (fewer on UI, slightly more on film), in 5×, 4× and 11× fewer windows. Each
  window costs an SPI panel a column and a row command and a new transfer,
  so on a microcontroller hundreds of 16x16 windows a frame are not free;
  version 8 keeps it to one per band of 8 rows.
- **File sizes within 6% of ZMBV:** version 8 is 6% smaller than ZMBV on the
  low-motion film, and 6% (UI) and 0.7% (high-motion film) larger at
  320x240. At 180x135 ZMBV stays 1.4× smaller on the UI clip. ZMBV keeps one
  zlib stream running across frames, so each frame reuses the previous
  frames' dictionary; that needs a 32 KiB inflate window and inflate state
  kept between frames. RV565 decodes every frame on its own, straight into
  the output, with no window, which is what lets it run on microcontrollers
  with little RAM.
- **Version 8 is also up to 9% smaller than version 7** (UI at 180x135; 4–5%
  on UI and low-motion film at 320x240, 0.1% on high-motion film), because a
  band's residual covers only its changed range.

Not measured here: frame time on a device. That needs a player for each
format on the same board and display; `benchmarks/esp32s3_v7_player` is the
starting point for RV565.

## Reproduce

Needs FFmpeg (with its ZMBV encoder), Pillow, and the film source:

```bash
python3 tools/compare_zmbv.py --ui
python3 tools/compare_zmbv.py big_buck_bunny_480p_h264.mov --start 90
python3 tools/compare_zmbv.py big_buck_bunny_480p_h264.mov --start 360
```

Each prints the table rows for 180x135 and 320x240 (`--size` picks others)
and checks that every encoding decodes to the source frames exactly.
