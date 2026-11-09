# RV565 against MJPEG on the ESP32-S3

Measured 2026-11-09 on the paper's ESP32-S3 board (arXiv:2610.35935), with
the paper's method. The firmware is the paper's player built twice: once
inflating RV565 frames with the ROM `tinfl`, and once decoding JPEG frames
with Espressif's SIMD-optimised `esp_new_jpeg`. Everything else (decode
buffers, scaling, stripes, DMA, pacing, measurement) is shared, so the
comparison isolates the format and its decoder.

## Setup

| | |
| --- | --- |
| Board | ESP32-S3 N16R8, 240 MHz, as in the paper |
| Display | 2.0" 320×240 ST7789, SPI at 40 MHz |
| RV565 decoder | ROM `tinfl` (RV565 v6) |
| MJPEG decoder | [`esp_new_jpeg`](https://components.espressif.com/components/espressif/esp_new_jpeg) 1.0.2, output big-endian RGB565, header parsed per frame |
| Firmware | `benchmarks/esp32s3_video_dma`, ESP-IDF 5.5.1; revisions `8205350` (W90 dual-core) and `309b3c2` (the rest), which differ only in `tools/run_codec_comparison.sh`; no tracked changes in either |
| Source | *Big Buck Bunny* 480p (SHA-256 `b2acb9bd…55b9a27`, as in the paper), FFmpeg 8.0.1 |
| Windows | W90: 90–100 s; W360: 360–370 s; 240 frames each, 180×135 at 24 FPS |
| Method | 48 warm-up frames, then 720 timed frames per run; 10 runs per configuration after independent resets (7,200 frames) |

The MJPEG clips start from exactly the RGB565 frames RV565 stores, and each
frame is a baseline JPEG at one FFmpeg quality (`-q:v`, 2 best to 31 worst).
PSNR is against those lossless frames, decoded on the host.

**4:4:4 is not in the table because it does not play.** `esp_new_jpeg` 1.0.2
rejects 4:4:4 JPEGs (`Not supported JPEG format`), so on the S3 MJPEG is
limited to chroma subsampling.

## Results

Times in milliseconds; the deadline at 24 FPS is 41.667 ms. Decode is
`tinfl` for RV565 and `esp_new_jpeg` for MJPEG. RAM is the heap the media
state takes (clip index, decoder and decode buffers).

### Dual-core

| Clip | Format | Size | Bytes/frame | PSNR mean (worst) | FPS | Misses | Drops | Decode mean | Decode p99 | Frame p99 | RAM |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| W90 | **RV565** | 6.12 MiB | 26,751 | exact | 24.009 | 0 | 0 | 8.90 | 10.02 | 31.33 | 99,136 |
| W90 | MJPEG q2 | 1.84 MiB | 8,026 | 34.8 dB (33.6) | 24.009 | 0 | 0 | 6.26 | 7.44 | 31.33 | 107,864 |
| W90 | MJPEG q5 | 0.97 MiB | 4,217 | 32.1 dB (30.5) | 24.009 | 0 | 0 | 4.44 | 5.34 | 31.33 | 107,864 |
| W90 | MJPEG q10 | 0.57 MiB | 2,483 | 29.7 dB (27.6) | 24.009 | 0 | 0 | 3.56 | 4.09 | 31.33 | 107,864 |
| W360 | **RV565** | 8.54 MiB | 37,327 | exact | 24.009 | 0 | 0 | 10.50 | 10.55 | 31.34 | 99,136 |
| W360 | MJPEG q2 | 2.58 MiB | 11,267 | 33.9 dB (33.7) | 24.009 | 0 | 0 | 7.81 | 8.05 | 31.34 | 107,864 |
| W360 | MJPEG q5 | 1.40 MiB | 6,133 | 30.9 dB (30.5) | 24.009 | 0 | 0 | 5.35 | 5.52 | 31.33 | 107,864 |
| W360 | MJPEG q10 | 0.84 MiB | 3,647 | 28.2 dB (27.8) | 24.009 | 0 | 0 | 4.13 | 4.24 | 31.33 | 107,864 |

### Serial (one core decodes, then transfers)

| Clip | Format | FPS | Misses | Drops | Decode mean | Frame mean | Frame p99 | RAM |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| W90 | **RV565** | 24.002 | 0 | 0 | 8.91 | 40.22 | 41.35 | 50,532 |
| W90 | MJPEG q5 | 24.005 | 0 | 0 | 4.44 | 35.75 | 36.65 | 59,260 |
| W360 | **RV565** | 23.905 | 7,200 | 20 | 10.52 | 41.83 | 41.88 | 50,532 |
| W360 | MJPEG q5 | 24.004 | 0 | 0 | 5.36 | 36.67 | 36.84 | 59,260 |

The RV565 rows reproduce the paper's measurements (serial W90 24.002 FPS;
serial W360 23.905 FPS, 20 drops, every frame late).

## What this shows

- **Dual-core, both formats play every frame on time** with 10.3 ms of
  slack. The display transfer (31.3 ms) bounds the frame, and both decoders
  fit inside it, so on this board the viewer sees the same playback.
- **MJPEG decodes faster on the S3**: 1.34–1.42× faster than RV565 at q2
  and about 2× at q5. `esp_new_jpeg` uses the S3's SIMD instructions; the
  RV565 build uses the ROM inflater.
- **MJPEG files are 3.3× smaller at q2 and 10–11× smaller at q10.**
- **On the serial path, MJPEG q5 holds 24 FPS on both windows; RV565 misses
  W360** by 0.16 ms per frame.
- **RV565 is lossless; MJPEG is not.** The best playable MJPEG (q2 4:2:0)
  averages 33.9–34.8 dB, and the mode that would come closest to exact
  colour (4:4:4) does not decode on this chip.
- **RV565 needs 8,728 bytes less RAM** in both modes, and no decoder library.

So RV565 does not win on size or decode speed on the ESP32-S3, where
Espressif ships an optimised JPEG decoder. What it offers is pixel-exact
RGB565 at the same frame rate, a smaller memory footprint, and a decoder
(`tinfl`) that is in ROM on the ESP32 family and plain portable C
elsewhere.

## Not measured

- **The RP2350**, which has no SIMD JPEG decoder; there the decode-speed
  comparison could come out differently.
- **Content where lossless matters most** (UI captures, pixel art, text),
  where JPEG artefacts are most visible. *Big Buck Bunny* is film, JPEG's
  best case.

## Reproduce

```bash
. ~/esp/esp-idf-v5.5.1/export.sh
tools/run_codec_comparison.sh /path/to/big_buck_bunny_480p_h264.mov /dev/ttyACM0 10
```

`tools/run_codec_comparison.sh` runs every configuration through
`tools/run_rv565_matrix.sh` and prints the table with
`tools/compare_codecs.py`; `RV565_RESUME=1` skips configurations that
already have results. The MJPEG encoder needs NumPy in the Python that
`export.sh` activates.
