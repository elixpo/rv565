# Format version 7: sizes, quality and display traffic

Measured 2026-11-12 on the host with the reference encoder (Python package
2.0.0, `tools/measure_v7.py`), at 180×135 and 24 FPS, 240 frames per clip:

- **Film:** *Big Buck Bunny* 480p (SHA-256 `b2acb9bd…55b9a27`), the paper's
  10-second windows from 90 s (W90) and 360 s (W360), as in
  [`RESULTS_MJPEG.md`](RESULTS_MJPEG.md).
- **UI:** `tools/make_ui_clip.py`, a deterministic status screen: a static
  background and header, a clock, a progress bar, a spinner and a scrolling
  ticker, the kind of content small displays mostly show.

PSNR is computed as in `RESULTS_MJPEG.md`: against the RGB565 frames FFmpeg
produces from the source, in 8-bit RGB, pooled over all frames (worst frame
in brackets). "Lines sent" is the share of frame rows a player has to
transfer to the display: all of them for keyframes and deltas, the changed
bands for partial deltas, none for repeats. On the ESP32-S3 and RP2350 the
transfer, not the decoder, bounds the frame time (31.3 and 33.4 ms of the
41.7 ms budget at 24 FPS).

These are file sizes and traffic counts. Decode and playback timings of
version 7 on hardware have not been measured yet, so nothing here claims a
frame rate.

## Results

Keyframe every 24 frames, bands of 8 lines, shift search ±8 pixels, zlib
level 9 unless noted. Tolerance 0 is lossless.

| Clip | Encoding | Size | Lines sent | Quality |
| --- | --- | ---: | ---: | --- |
| W90 | version 6 (paper) | 6.12 MiB | 100% | exact |
| W90 | version 7, tolerance 0 | 1.11 MiB | 87% | exact |
| W90 | version 7, tolerance 8 | 0.81 MiB | 75% | 40.2 dB (38.6) |
| W90 | version 7, tolerance 16 | 0.66 MiB | 57% | 37.2 dB (36.1) |
| W360 | version 6 (paper) | 8.54 MiB | 100% | exact |
| W360 | version 7, tolerance 0 | 4.07 MiB | 100% | exact |
| W360 | version 7, tolerance 8 | 3.06 MiB | 99% | 36.5 dB (35.3) |
| W360 | version 7, tolerance 16 | 2.38 MiB | 97% | 31.9 dB (31.2) |
| UI | version 7, tolerance 0, zlib level 1 | 0.16 MiB | 44% | exact |
| UI | version 7, tolerance 0 | 0.12 MiB | 44% | exact |

Without band shifts the UI clip is 0.49 MiB: the scrolling ticker accounts
for most of it, and a shift turns it into a near-empty residual. Without
partial deltas every row of every changed frame is sent.

## Against MJPEG and ZMBV

Same frames. MJPEG figures for the film are from
[`RESULTS_MJPEG.md`](RESULTS_MJPEG.md) (FFmpeg `-q:v`, 4:2:0); the UI figures
were measured the same way with `tools/encode_mjpeg_benchmark.py`. ZMBV is
FFmpeg's Zip Motion Blocks Video encoder (`-c:v zmbv -g 24`, RGB565
little-endian in AVI), which also combines zlib, XOR deltas and motion
vectors.

| Clip | Format | Size | Lines sent | Quality |
| --- | --- | ---: | ---: | --- |
| W90 | **RV565 v7, tolerance 8** | **0.81 MiB** | **75%** | **40.2 dB** |
| W90 | RV565 v7, tolerance 16 | 0.66 MiB | 57% | 37.2 dB |
| W90 | MJPEG q2 | 1.84 MiB | 100% | 34.8 dB |
| W90 | MJPEG q5 | 0.97 MiB | 100% | 32.1 dB |
| W90 | RV565 v7, lossless | 1.11 MiB | 87% | exact |
| W90 | ZMBV level 9, lossless | 1.14 MiB | 100% | exact |
| W360 | RV565 v7, tolerance 8 | 3.06 MiB | 99% | 36.5 dB |
| W360 | MJPEG q2 | 2.58 MiB | 100% | 33.9 dB |
| W360 | MJPEG q5 | 1.40 MiB | 100% | 30.9 dB |
| W360 | RV565 v7, lossless | 4.07 MiB | 100% | exact |
| W360 | ZMBV level 9, lossless | 4.05 MiB | 100% | exact |
| UI | **RV565 v7, lossless** | 0.12 MiB | **44%** | **exact** |
| UI | MJPEG q2 | 1.85 MiB | 100% | 31.8 dB |
| UI | MJPEG q5 | 1.14 MiB | 100% | 30.2 dB |
| UI | ZMBV level 9, lossless | **0.08 MiB** | 100% | exact |

What this shows:

- **Film with little motion (W90):** at tolerance 8 RV565 is 2.3× smaller
  than MJPEG at its best quality and 5.4 dB better, and sends a quarter fewer
  rows to the display. At tolerance 16 it is smaller than MJPEG q5 and 5 dB
  better.
- **Film with a lot of motion (W360):** MJPEG keeps the edge in size. At its
  best quality it is 16% smaller than RV565 at tolerance 8, which is 2.6 dB
  better; at lower quality MJPEG q5 is much smaller. RV565 sends almost every
  row here.
- **UI content:** RV565 is lossless at 6% of MJPEG q2's size, where JPEG
  blurs the text to 31.8 dB, and sends 44% of the rows.
- **ZMBV:** the same size as RV565 when both are lossless on film. On the UI
  clip ZMBV is 1.5× smaller: its motion vectors are per 16×16 block, RV565's
  per band of rows. ZMBV gives the device no way to send less than the whole
  frame, and its block motion compensation and AVI container are more work
  for a microcontroller than RV565's band copies.

## Reproduce

```bash
SRC=big_buck_bunny_480p_h264.mov
python3 tools/measure_v7.py $SRC --start 90 --tolerance 0 8 16 --level 9
python3 tools/measure_v7.py $SRC --start 360 --tolerance 0 8 16 --level 9
python3 tools/make_ui_clip.py ui.mkv
python3 tools/measure_v7.py ui.mkv --tolerance 0 --level 1 9
python3 tools/encode_mjpeg_benchmark.py ui.mkv ui_q2.mjpeg --q 2
ffmpeg -i ui.mkv -vf format=rgb565le -c:v zmbv -g 24 -compression_level 9 ui_zmbv.avi
```

`tools/measure_v7.py` needs NumPy for speed (it works without it, slowly).
For W90 and W360 add the same `fps`, `scale` and `crop` filter to the ZMBV
command as `tools/measure_v7.py` uses.

## Not measured yet

- Decode time and playback of version 7 on the ESP32-S3 and RP2350. A delta
  adds one XOR pass over the frame and a partial delta one over its changed
  bands, against an inflate of a body that is several times smaller; a
  shifted band adds a copy of its rows.
- What partial deltas save in transfer time and power on a real panel.
