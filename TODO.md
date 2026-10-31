# TODO for Ayushman

Everything below needs hardware, an account, or a decision. The library,
packaging, examples, tests and CI are done; see `docs/ECOSYSTEM.md`.

## Done

- PR #1 merged; `v0.1.0` tagged.
- ESP-IDF example verified on the badge: 180x135 @ 24 FPS, 0 predicted late
  frames, colour bars scroll.
- Arduino Library Manager: accepted (arduino/library-registry#9534).
- Repository description and topics set.
- Espressif `elixpo` namespace requested (2026-10-31).

## Open

1. Espressif: when the namespace is approved, create component `rv565`
   under `elixpo` on components.espressif.com, add the trusted uploader
   (`elixpo/rv565`, workflow `publish-idf.yml`), then run
   `gh workflow run publish-idf.yml --ref v0.1.0`. Afterwards add the tag
   trigger noted in the workflow.
2. Arduino: once indexed, install RV565 from the IDE's Library Manager and
   upload `examples/ESP32S3_Player` to the badge.
3. Optional: play a real clip by replacing `examples_idf/player/main/clip.rv565`
   with one from `tools/rv565.py encode`.

## Pico 2 (when you have the board)

4. Wire an ST7789 to GP17-22 (see `examples_pico/player/main.c`), build with
   the Pico SDK or upload `examples/Pico2_Player` via Arduino-Pico, and check
   the image. Expect to adjust SPI pins or the clock; the RP2350 port has only
   been compiled, never run.
5. Measure with the paper's methodology and record a cost model for RP2350.

## Write-ups

6. Espressif Developer Portal article and Arduino Project Hub post once the
   listings are live.
