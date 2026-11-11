# RV565

[![Arduino Library Manager](https://www.ardu-badge.com/badge/RV565.svg)](https://www.ardu-badge.com/RV565)
[![PyPI](https://img.shields.io/pypi/v/rv565.svg)](https://pypi.org/project/rv565/)
[![ESP Component Registry](https://components.espressif.com/components/elixpo/rv565/badge.svg)](https://components.espressif.com/components/elixpo/rv565)
[![arXiv](https://img.shields.io/badge/arXiv-2610.35935-b31b1b.svg)](https://arxiv.org/abs/2610.35935)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.23543367-blue.svg)](https://doi.org/10.5281/zenodo.23543367)

Frame-independent RGB565 video for microcontroller displays, with a dual-core
decode and DMA pipeline.

RV565 plays video on SPI panels such as the ST7789 from small, simple files:
every frame is an independent zlib stream whose decoded bytes are already the
panel's native RGB565. That makes three things possible on a microcontroller:

- **24 FPS with zero missed frames** on the ESP32-S3 and the RP2350 (Pico 2):
  core 1 inflates the next frame while core 0 scales and DMA-transfers the
  current one, so frame time equals the display transfer (98.1% of the SPI
  bound on both).
- **Schedulability from the file alone**: inflate time is linear in the stored
  payload length, so `rv565_check_schedule()` tells you before playback whether
  a clip will keep up.
- **O(1) seeking and local error recovery**: no frame depends on another.

The design and measurements are described in
*RV565: Cross-Layer Co-Design for Frame-Independent Video Playback on
MicroPython-Class ESP32-S3 Systems*
([arXiv:2610.35935](https://arxiv.org/abs/2610.35935); artifact
[doi:10.5281/zenodo.23543367](https://doi.org/10.5281/zenodo.23543367)).

## Use .rv565 for your video

1. **Make the file** from any video: in the
   [online converter](https://oreo.elixpo.com/rv565/convert/) (runs in your
   browser, nothing is uploaded), or with `pip install rv565` and
   `rv565 encode input.mp4 clip.rv565` (needs FFmpeg).
2. **Check it before you flash it:**

   ```bash
   rv565 verify clip.rv565                  # every frame decodes to its exact size
   rv565 info --chip esp32s3 clip.rv565     # or --chip rp2350: will it keep its frame rate?
   ```

   `info` predicts each frame's decode time from the sizes stored in the file,
   using the cost model measured on each chip. On a Pico 2 it predicted a
   49.00 ms worst frame for a clip that measured 49.03 ms.
3. **Play it:** in Arduino, *File → Examples → RV565 → ESP32S3_Player* or
   *Pico2_Player*; with ESP-IDF, the `elixpo/rv565` component
   (`examples_idf/player`).

**What you can rely on**

- **The format is frozen.** Version 6 is covered by the 1.x compatibility
  promise: a clip you make today plays on every 1.x release
  ([specification](docs/FORMAT.md)).
- **Damaged files are rejected, not drawn.** Readers validate the header and
  every frame, and a frame only counts if it decodes to exactly its RGB565
  size.
- **Verified hardware:** the ESP32-S3 and the RP2350, each with a 320x240
  ST7789, play 24 FPS clips with zero missed deadlines using dual-core
  decoding. Other boards and panels should work with the same code but have
  not been measured yet; please
  [report yours](https://github.com/elixpo/rv565/issues/28).

## Platforms

| Platform | Install | Status |
| --- | --- | --- |
| ESP32-S3, ESP-IDF | `idf.py add-dependency "elixpo/rv565"` ([registry](https://components.espressif.com/components/elixpo/rv565)) | Measured in the paper; [against MJPEG](docs/RESULTS_MJPEG.md) |
| ESP32-S3, Arduino | Library Manager → *RV565* | Same code as ESP-IDF |
| RP2350 (Pico 2), Pico SDK | `add_subdirectory(rv565)` | Measured: 24 FPS dual-core ([results](docs/RESULTS_RP2350.md); [against MJPEG](docs/RESULTS_MJPEG.md#raspberry-pi-pico-2-rp2350)) |
| RP2350 (Pico 2), Arduino-Pico | Library Manager → *RV565* | Same code as the Pico SDK |
| RP2040 (Pico) | as RP2350 | Compiles; not yet run on hardware |
| CircuitPython (ESP32-S3, RP2350, ...) | copy `ports/circuitpython/circuitpython_rv565.py` to `CIRCUITPY/lib` ([guide](ports/circuitpython/README.rst)) | Experimental: pure Python, a few FPS; host-tested, not yet run on a board |
| Desktop (Python 3.9+) | `pip install rv565` ([PyPI](https://pypi.org/project/rv565/)) | Encode, inspect, verify; Pillow plugin |
| Browser | [Online converter](https://oreo.elixpo.com/rv565/convert/) | No install, no upload |

Arduino: install *RV565* from the Library Manager, or run
`arduino-cli lib install RV565`. ESP-IDF: the component is on the
[ESP Component Registry](https://components.espressif.com/components/elixpo/rv565);
start from its example with
`idf.py create-project-from-example "elixpo/rv565^1.1.0:player"`.

## Panels

The ports drive any ST7789 module. Pick a preset from `rv565_panel.h` in the
display config and use the same size for the player:

```c
rv565_esp32_display_config_t display = { /* pins, clock, ... */
    .panel = RV565_PANEL_240X240,   /* 320X240 (default), 240X320, 135X240, 240X135 */
};
```

For another module, fill `rv565_panel_t` with its size, controller offset,
MADCTL rotation and inversion. Only the 320x240 preset is verified on
hardware so far; reports for other modules are welcome.

## Using your display library

Already drive your screen with TFT_eSPI or LovyanGFX? Keep it: RV565 decodes
and scales, your library sends the stripes by DMA. See
`examples/TFT_eSPI_Player` and `examples/LovyanGFX_Player` (ESP32); the
adapter is four small functions.

## Python

The Python package is published on PyPI:
[pypi.org/project/rv565](https://pypi.org/project/rv565/).

```bash
pip install rv565            # the rv565 command and library, no dependencies
pip install "rv565[pillow]"  # plus the Pillow plugin
```

It gives the `rv565` command (encode, info, verify, c-array) and a small
library; with Pillow, `Image.open("clip.rv565")` opens clips as animations.
See [python/](python/README.md). No Python? Use the
[online converter](https://oreo.elixpo.com/rv565/convert/), which runs in the
browser.

## CircuitPython (experimental)

No C toolchain? `ports/circuitpython/` is a pure-Python player for
CircuitPython boards with `zlib` and `displayio`, such as ESP32-S3 boards and
the Pico 2:

```python
import board
import circuitpython_rv565 as rv565

player = rv565.Player(rv565.open("/clip.rv565"), board.DISPLAY)
print(player.play())   # paced to the clip's rate, late frames skipped
```

It will play at a few frames per second, not 24: inflating and drawing run
one after the other in Python. It has passed host tests but not yet run on a
board; see [its README](ports/circuitpython/README.rst) for setup, the Pico 2
wiring and the experimental `DirectPlayer`, which writes frames straight to
the ST7789.

## Quick start

Encode a clip on your computer (needs FFmpeg), then check it:

```bash
python3 tools/rv565.py encode input.mp4 clip.rv565 --size 180x135 --fps 24
python3 tools/rv565.py info clip.rv565      # sizes and predicted late frames
python3 tools/rv565.py c-array clip.rv565 clip.h   # for Arduino sketches
```

Play it (ESP32-S3; see `examples/` and `examples_idf/` for complete code):

```c
#include <RV565.h>

rv565_clip_t clip;
static uint32_t frame_index[1024];
rv565_open(&clip, data, size, frame_index, 1024, 320, 240);

rv565_schedule_report_t report;
rv565_check_schedule(&clip, &RV565_COST_ESP32S3_180x135, 31312.0f, 1, &report);
// report.late_frames == 0 means the clip keeps up with dual-core decoding.

rv565_player_t player = { .clip = &clip, /* panel size, buffers, maps */ };
rv565_esp32_display_init(&display_config, &player.display);
rv565_esp32_decoder_init(&clip, 1, &player.decoder);   // inflate on core 1
rv565_player_init(&player);

rv565_pacer_t pacer;
rv565_pacer_start(&pacer, &clip.header, rv565_esp32_micros());
for (;;) {
    rv565_player_present(&player, pacer.frame, NULL);
    uint32_t wait;
    rv565_pacer_advance(&pacer, rv565_esp32_micros(), &wait);
    esp_rom_delay_us(wait);
}
```

Leave `player.decoder` empty to use the single-core serial path.

## Layout

```
src/                 portable core, player, and platform ports (Arduino src/)
  rv565.[ch]         container parsing, validation, inflate, scaling, cost model
  rv565_player.[ch]  stripe pipeline with optional second-core decoding
  port/esp32/        SPI GDMA display + FreeRTOS core-1 worker
  port/rp2/          SPI DMA display + multicore worker
  third_party/       inflate-only miniz (used where no ROM inflater exists)
examples/            Arduino sketches (ESP32-S3, Pico 2)
examples_idf/        ESP-IDF example project
examples_pico/       Pico SDK example project
ports/circuitpython/ CircuitPython library (experimental, pure Python)
ports/micropython/   MicroPython user C module
tools/rv565.py       encoder and inspection CLI
tests/               host tests (make -C tests)
benchmarks/          the paper's standalone ESP32-S3 benchmark and collectors
docs/                format specification, architecture notes, ecosystem plan
```

## Memory

On the ESP32-S3 with 180×135 frames and a 320×240 panel, the serial path uses
79.9 KiB of internal SRAM and the dual-core path 152.4 KiB (second decoded
frame and worker stack). `tinfl` keeps about 11 KB on the decoding task's
stack.

## Versioning

RV565 follows [semantic versioning](https://semver.org). From 1.0.0 the
container format and the public API in `rv565.h`, `rv565_player.h` and the
ESP32 and RP2 ports will not change incompatibly within 1.x. The RP2 port is
measured on the RP2350; on the RP2040 it compiles but has not yet run on
hardware. Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## Development

```bash
make -C tests                                    # host tests
make -C tests CLIPS="w90.rv565 w360.rv565"       # plus your own containers
python3 -m unittest discover -s python/tests     # Python package
python3 -m unittest discover -s ports/circuitpython/tests   # CircuitPython library
```

CI builds the Arduino sketches for ESP32-S3 and Pico 2, the ESP-IDF example,
and the Pico SDK example, and lints the library for the Arduino Library Manager.

## Community

- **Tried RV565 on a board or display?** Tell us how it went, working or not:
  [report your hardware](https://github.com/elixpo/rv565/issues/new?template=hardware-report.yml).
  Verified so far: the ESP32-S3 and the RP2350 (Pico 2), each with a 320x240
  ST7789, so every other board or panel report helps; see the
  [open requests](https://github.com/elixpo/rv565/issues/28).
- **Questions, ideas and projects** go to Elixpo's community discussions:
  [Q&A](https://github.com/elixpo/elixpo/discussions/categories/q-a),
  [Ideas](https://github.com/elixpo/elixpo/discussions/categories/ideas),
  [Show and tell](https://github.com/elixpo/elixpo/discussions/categories/show-and-tell).
- **Bugs:** [open an issue](https://github.com/elixpo/rv565/issues/new?template=bug-report.yml).

## Where RV565 is

**First device: the [Oreo Badge](https://github.com/elixpo/oreo).** RV565 was
built for the Gallery app of OreoOS, the MicroPython operating system of the
Oreo Badge, an ESP32-S3 conference badge. The badge is
[certified open source hardware](https://certification.oshwa.org/in000107.html)
by OSHWA (UID IN000107); its hardware is licensed under CERN-OHL-P-2.0 and
OreoOS under MIT.

**Published**

- Paper: [arXiv:2610.35935](https://arxiv.org/abs/2610.35935), archived on
  [Zenodo](https://doi.org/10.5281/zenodo.23543367)
- Arduino Library Manager (search *RV565*) and the
  [PlatformIO Registry](https://registry.platformio.org/libraries/elixpo/RV565)
- [ESP Component Registry](https://components.espressif.com/components/elixpo/rv565)
- [PyPI](https://pypi.org/project/rv565/)
- [Online converter](https://oreo.elixpo.com/rv565/convert/), in the browser
- Write-up of the Pico 2 port:
  [*The Screen Was Blank*](https://blogs.elixpo.com/elixpohere/rv565-pico-2-tweak)

**Submitted, under review**

- FFmpeg decoder, encoder, demuxer and muxer:
  [FFmpeg #25653](https://code.ffmpeg.org/FFmpeg/FFmpeg/pulls/25653)
- The `video/x-rv565` MIME type in freedesktop shared-mime-info:
  [!449](https://gitlab.freedesktop.org/xdg/shared-mime-info/-/merge_requests/449)
- A `file(1)` magic entry: [bugs.astron.com #819](https://bugs.astron.com/view.php?id=819)
- PRONOM, the National Archives' format registry:
  [PRONOM_Research #202](https://github.com/digital-preservation/PRONOM_Research/pull/202)
- [awesome-esp #67](https://github.com/agucova/awesome-esp/pull/67) and
  [Awesome-Embedded #92](https://github.com/nhivp/Awesome-Embedded/pull/92)

Using RV565 in a project? Tell us in
[Show and tell](https://github.com/elixpo/elixpo/discussions/categories/show-and-tell)
and we will list it here.

## The Oreo family

One project in three repositories, grouped under the
[`oreo-badge`](https://github.com/orgs/elixpo/repositories?q=topic%3Aoreo-badge) topic:

- [elixpo/oreo](https://github.com/elixpo/oreo): the Oreo Badge hardware, OreoOS and the `oreo` CLI
- [elixpo/rv565](https://github.com/elixpo/rv565): RV565, the badge's video format (C library, encoder, Arduino, ESP-IDF and Pico SDK)
- [elixpo/CircuitPython_RV565](https://github.com/elixpo/CircuitPython_RV565): RV565 playback for CircuitPython

## Citation

```bibtex
@misc{bhattacharya2026rv565,
  author        = {Ayushman Bhattacharya and Anwesha Chakraborty},
  title         = {RV565: Cross-Layer Co-Design for Frame-Independent Video Playback on MicroPython-Class ESP32-S3 Systems},
  year          = {2026},
  eprint        = {2610.35935},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AR}
}
```

## License

MIT; see [LICENSE](LICENSE). The bundled inflater is miniz (MIT); see
[NOTICE](NOTICE).
