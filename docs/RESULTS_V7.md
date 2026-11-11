# Format version 7: file sizes

Measured 2026-11-12 on the host with the reference encoder (`rv565 encode`,
Python package 2.0.0), on the same source and windows as the RV565 paper and
[`RESULTS_MJPEG.md`](RESULTS_MJPEG.md): *Big Buck Bunny* 480p (SHA-256
`b2acb9bd…55b9a27`), 10-second windows starting at 90 s (W90) and 360 s
(W360), 180×135 RGB565 big-endian at 24 FPS, 240 frames each.

These are file sizes only. Decode and playback timings of version 7 on the
ESP32-S3 and RP2350 have not been measured yet; until they are, nothing here
claims a frame rate.

## Results

| Clip | Encoding | Size | Bytes/frame | Frames (key / delta) | Against version 6 |
| --- | --- | ---: | ---: | --- | ---: |
| W90 | version 6 (every frame a keyframe, zlib level 1) | 6.12 MiB | 26,756 | 240 / 0 | 1.00× |
| W90 | version 7, keyframe every 24 frames, level 1 | 1.28 MiB | 5,585 | 12 / 228 | 4.79× smaller |
| W90 | version 7, keyframe every 240 frames, level 1 | 1.17 MiB | 5,121 | 3 / 237 | 5.22× smaller |
| W90 | version 7, keyframe every 24 frames, level 9 | 1.10 MiB | 4,821 | 12 / 228 | 5.55× smaller |
| W360 | version 6 | 8.54 MiB | 37,332 | 240 / 0 | 1.00× |
| W360 | version 7, keyframe every 24 frames, level 1 | 4.65 MiB | 20,319 | 33 / 207 | 1.84× smaller |
| W360 | version 7, keyframe every 240 frames, level 1 | 4.56 MiB | 19,915 | 25 / 215 | 1.87× smaller |
| W360 | version 7, keyframe every 24 frames, level 9 | 4.24 MiB | 18,542 | 33 / 207 | 2.01× smaller |

The version 6 rows reproduce the paper's file sizes (6.12 and 8.54 MiB).
With an interval above 24 the encoder still writes extra keyframes wherever a
keyframe is smaller than the delta, which is why W360 has more keyframes than
the interval requires (scene changes).

## Against MJPEG

From [`RESULTS_MJPEG.md`](RESULTS_MJPEG.md), same windows and frames:

| Clip | Format | Size | Exact? |
| --- | --- | ---: | --- |
| W90 | RV565 version 7, keyframe every 24, level 9 | 1.10 MiB | yes |
| W90 | MJPEG q2 | 1.84 MiB | no, 34.8 dB |
| W90 | MJPEG q5 | 0.97 MiB | no, 32.1 dB |
| W360 | RV565 version 7, keyframe every 24, level 9 | 4.24 MiB | yes |
| W360 | MJPEG q2 | 2.58 MiB | no, 33.9 dB |
| W360 | MJPEG q5 | 1.40 MiB | no, 30.9 dB |

On W90 the lossless version 7 file is smaller than MJPEG at its best quality.
On W360, where the scene changes often, MJPEG q2 is still 1.6× smaller.

## Reproduce

```bash
SRC=big_buck_bunny_480p_h264.mov
python3 tools/rv565.py encode $SRC w90_v6.rv565 --start 90 --seconds 10 --v6
python3 tools/rv565.py encode $SRC w90_k24.rv565 --start 90 --seconds 10 --keyframe-interval 24
python3 tools/rv565.py encode $SRC w90_k24_l9.rv565 --start 90 --seconds 10 --keyframe-interval 24 --level 9
python3 tools/rv565.py info w90_k24.rv565
```

Use `--start 360` for W360.

## Not measured yet

- Decode time and playback on the ESP32-S3 and RP2350. A delta adds one XOR
  pass over the frame (48,600 bytes at 180×135) but inflates a body that is
  typically 4–6× smaller, and the paper found inflate time linear in the
  body length.
- Content other than film: UI captures, pixel art, text, and the
  monochrome and grayscale formats on OLED and e-paper panels.
