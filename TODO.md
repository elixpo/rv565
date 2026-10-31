# TODO for Ayushman

Everything below needs hardware, an account, or a decision. The library,
packaging, examples, tests and CI are done; see `docs/ECOSYSTEM.md`.

## Before merging PR #1

1. Read the PR diff, especially `src/port/esp32/rv565_esp32.c` (lifted from the
   benchmark) and `src/port/rp2/rv565_rp2.c` (new, untested on hardware).
2. Check the CI run on the PR: host tests, Arduino lint, Arduino ESP32-S3 and
   Pico 2 builds, ESP-IDF build, Pico SDK build. Fix anything red before merging.
3. Merge with **squash** or **rebase**; the 8 history commits extracted from
   OreoOS are already on `main`.

## Hardware (badge)

4. Flash the ESP-IDF example and confirm the test pattern plays:
   ```bash
   . ~/esp/esp-idf-v5.5.1/export.sh
   cd examples_idf/player && idf.py set-target esp32s3 && idf.py -p /dev/ttyACM0 flash monitor
   ```
   The log prints the predicted late frames; the panel should show scrolling
   colour bars. Pins match the OreoOS badge (MOSI 11, SCLK 12, CS 14, DC 15, RST 16, BL 17).
5. Same check through Arduino: open `examples/ESP32S3_Player` and upload.
6. Optional: play a real clip by replacing `examples_idf/player/main/clip.rv565`
   with one from `tools/rv565.py encode`.

## Accounts and listings

7. Espressif namespace: request `elixpo` via the Component Registry's
   Namespace Request Form. When approved, run the *Publish to ESP Component
   Registry* workflow (Actions tab) once, then add the tag trigger noted in
   `.github/workflows/publish-idf.yml`.
8. Arduino: confirm no existing library is named *RV565*, tag `v0.1.0`
   (`git tag v0.1.0 && git push origin v0.1.0`), then open a PR adding
   `https://github.com/elixpo/rv565` to `repositories.txt` in
   `arduino/library-registry`. The bot comments with any fixes.
9. Repository settings: add a description and topics (`esp32`, `rp2350`,
   `arduino-library`, `esp-idf-component`, `video`, `rgb565`, `st7789`).

## Pico 2 (when you have the board)

10. Wire an ST7789 to GP17-22 (see `examples_pico/player/main.c`), build with
    the Pico SDK or upload `examples/Pico2_Player` via Arduino-Pico, and check
    the image. Expect to adjust SPI pins or the clock; the RP2350 port has only
    been compiled, never run.
11. Measure with the paper's methodology and record a cost model for RP2350.

## Write-ups

12. Espressif Developer Portal article and Arduino Project Hub post once the
    listings are live.
