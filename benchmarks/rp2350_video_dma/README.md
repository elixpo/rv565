# RP2350 (Raspberry Pi Pico 2) video benchmark

Measures RV565 on the Pico 2 with the method used for the ESP32-S3 in the
paper (`benchmarks/esp32s3_video_dma`): two seconds of warm-up, then 30
seconds of per-frame timings recorded in RAM and printed afterwards in the
same `RV565_*` format, so the same collector records it and
`tools/fit_cost_model.py` turns the runs into an RP2350 cost model.

Differences from the ESP32-S3 setup, all reported in the output:

- **Clip windows are 4 s (96 frames), not 10 s.** The paper's windows are
  6.4 MB (W90) and 9.0 MB (W360); the Pico 2 has 4 MB of flash. The 30-second
  measurement loops the window.
- **Inflate uses the bundled miniz**, not a ROM inflater (the RP2350 has none).
- **SPI runs at what the RP2350 can divide from 150 MHz**: a 40 MHz request
  gives 37.5 MHz. The actual rate is printed as `spi_khz` and used for the
  wire-time bound.
- Output goes over the Pico's USB serial, and each run starts when the host
  sends a byte (there is no reset line).

## Hardware

Raspberry Pi Pico 2 (or Pico 2 W) and a 2.0" 320×240 ST7789 SPI module:

| Display | Pico 2 pin |
| --- | --- |
| VCC | 3V3 (pin 36) |
| GND | GND (pin 38) |
| SCL / SCK | GP18 |
| SDA / MOSI | GP19 |
| CS | GP17 |
| DC | GP20 |
| RST | GP21 |
| BL | GP22 |

## Prerequisites

```bash
sudo apt install cmake gcc-arm-none-eabi libnewlib-arm-none-eabi picotool
git clone --depth 1 --branch 2.1.1 https://github.com/raspberrypi/pico-sdk.git ~/pico-sdk
git -C ~/pico-sdk submodule update --init --depth 1 lib/tinyusb   # needed for USB serial
export PICO_SDK_PATH=~/pico-sdk
python3 -m pip install pyserial   # for the collector
```

If your distribution has no `picotool` package, hold BOOTSEL while plugging
the Pico in and copy `build/rv565_rp2350_bench.uf2` to the drive that appears.

## 1. Bring-up with the test pattern

Check wiring and colours before measuring anything:

```bash
cd benchmarks/rp2350_video_dma
cmake -B build -DPICO_BOARD=pico2 -DRV565_VIDEO=$PWD/../../tests/data/testpattern.rv565
cmake --build build -j
picotool load -f -x build/rv565_rp2350_bench.uf2
cd ../.. && python3 tools/collect_video_benchmark.py --platform rp2350 --label rp2350-bringup
```

The panel shows scrolling colour bars (white, yellow, cyan, green, magenta,
red, blue, black from left to right) and the collector prints FPS and timing
percentiles. Then delete `build/` before the real runs:
`rm -rf benchmarks/rp2350_video_dma/build`.

## 2. Measure

From the repository root, with the Big Buck Bunny source used in the paper
(CC BY 3.0, Blender Foundation):

```bash
for start in 90 360; do
  for mode in serial overlap; do
    tools/run_rv565_matrix_rp2350.sh /path/to/big_buck_bunny.mp4 $start $mode
  done
done
```

Each configuration encodes the window, builds, flashes and records ten runs
into `benchmarks/measurements/`. Keep the two clips for the fit:

```bash
python3 tools/encode_video_benchmark.py /path/to/big_buck_bunny.mp4 /tmp/w90.rv565  --start 90  --seconds 4
python3 tools/encode_video_benchmark.py /path/to/big_buck_bunny.mp4 /tmp/w360.rv565 --start 360 --seconds 4
```

## 3. Fit the cost model

```bash
python3 tools/fit_cost_model.py \
  --window /tmp/w90.rv565  benchmarks/measurements/video-benchmark-rp2350-bbb090-serial-r*.json \
  --window /tmp/w360.rv565 benchmarks/measurements/video-benchmark-rp2350-bbb360-serial-r*.json
```

It prints FPS, drops and misses per window, transfer time against the wire
bound, the pooled `T(L) = a + b·L` model with r² and hold-out error, the
serial admission threshold, and a `rv565_cost_model_t` initialiser for the
library. Run it on the overlap records too, for their FPS and miss counts.

The same script reproduces the paper's ESP32-S3 numbers from its committed
records (4.858 ms + 0.1515 µs/byte, r² 0.9987).

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Backlight on, nothing drawn | Loose SCK/MOSI/DC wire, or the module needs 5 V on VCC |
| Colours inverted (white shows black) | Non-IPS panel: set `.invert = 0` in the panel (use a custom `rv565_panel_t`) |
| Image shifted or wrapped | Different module size or offset: pick another preset |
| Noise or tearing streaks | Long jumper wires at 37.5 MHz: lower `.clock_hz` to 20 MHz to confirm |
| Collector times out | Wrong port (`ls /dev/ttyACM*`), or the Pico is still in BOOTSEL mode |
