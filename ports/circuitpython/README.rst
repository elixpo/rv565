circuitpython-rv565
===================

Play `RV565 <https://github.com/elixpo/rv565>`_ video files on CircuitPython
displays.

RV565 stores video as independently zlib-compressed frames whose decoded
bytes are already big-endian RGB565, the native pixel format of ST7789-class
SPI panels (`format specification
<https://github.com/elixpo/rv565/blob/main/docs/FORMAT.md>`_,
`arXiv:2610.35935 <https://arxiv.org/abs/2610.35935>`_). This library reads
them in pure Python with CircuitPython's built-in ``zlib`` and shows them with
``displayio``.

**Status: experimental.** It passes host tests against the RV565 test vector
(every frame matches CPython's zlib) but has not yet been run on a
CircuitPython board.

**Expect a few frames per second, not 24.** The C library reaches 24 FPS by
inflating on one core while DMA sends the previous frame from the other.
Here, inflating and drawing happen one after the other in a single Python
thread, so a 180x135 clip will play at a fraction of its rate. Frames that
fall behind are skipped, so playback keeps the clip's timing, and
``Player.play()`` returns the frame rate it actually achieved. Use this
library to try RV565 without a C toolchain; use the C library when you need
the full frame rate.

Dependencies
------------

* CircuitPython 9 or later (8.x should work but is untested), on a board whose
  build includes ``zlib``, ``displayio`` and ``bitmaptools``. Most ESP32-S3
  and RP2350 builds include all three; check the
  `module support matrix
  <https://docs.circuitpython.org/en/latest/shared-bindings/support_matrix.html>`_
  for your board.
* `adafruit_st7789 <https://github.com/adafruit/Adafruit_CircuitPython_ST7789>`_,
  only for the examples that drive an external ST7789.

Installing on a CircuitPython board
-----------------------------------

1. Copy ``circuitpython_rv565.py`` to the ``lib`` folder on your
   ``CIRCUITPY`` drive. (To save RAM, compile it first with the
   ``mpy-cross`` that matches your CircuitPython version and copy
   ``circuitpython_rv565.mpy`` instead.)
2. Copy a clip to ``CIRCUITPY``. To start, use the test pattern,
   ``tests/data/testpattern.rv565`` in the RV565 repository (180x135,
   24 FPS, 24 frames, 6 KB).
3. Copy one of the files in ``examples/`` to ``CIRCUITPY`` as ``code.py``.
   For an external ST7789, also copy ``adafruit_st7789.mpy`` from the
   `Adafruit bundle <https://circuitpython.org/libraries>`_ into ``lib``.

Once the library is in the Community Bundle, ``circup install rv565`` will do
step 1.

Making clips
------------

Use the `online converter <https://oreo.elixpo.com/rv565/convert/>`_, which
runs in your browser, or the Python tool::

    pip install rv565
    rv565 encode input.mp4 clip.rv565 --size 180x135 --fps 12
    rv565 verify clip.rv565

Because this library will not reach 24 FPS, a lower rate such as 8 or 12 FPS
wastes less of the file on frames that will be skipped. Keep clips at 180x135
or smaller on boards without PSRAM, such as the Pico 2: a 320x240 frame needs
150 KiB inflated and as much again for the bitmap.

Usage
-----

.. code-block:: python

    import board
    import circuitpython_rv565 as rv565

    clip = rv565.open("/clip.rv565")        # path, file object or bytes
    print(clip.width, clip.height, clip.fps, len(clip))

    player = rv565.Player(clip, board.DISPLAY)
    stats = player.play()                   # paced to clip.fps, late frames skipped
    print(stats)  # <PlayStats x.xx of 24 FPS: n shown, m skipped ...>

``rv565.open()`` reads only the 12-byte header. The frame index is built on
first use with one pass over the length fields (4 bytes of RAM per frame),
which also validates the whole container; call ``clip.build_index()`` to do
that before playback. Frames are read from the file one at a time, so a clip
on CIRCUITPY or an SD card does not have to fit in RAM. ``clip.frame(i)``
returns frame ``i`` as big-endian RGB565 bytes and raises ``RV565Error`` if it
does not inflate to exactly ``2 * width * height`` bytes.

How a frame reaches the display
-------------------------------

``Player`` inflates each frame into a ``displayio.Bitmap`` with 65536 values,
drawn through ``ColorConverter(input_colorspace=Colorspace.RGB565_SWAPPED)``.
The bitmap stores each value as a little-endian 16-bit word, so copying the
file's big-endian bytes in unchanged gives byte-swapped values, which is
exactly what ``RGB565_SWAPPED`` describes (the same convention ``gifio`` uses).
The copy is one ``bitmaptools.readinto()`` call; boards without it fall back
to a much slower per-pixel loop.

``DirectPlayer`` (experimental) skips ``displayio``: since RV565 bytes are
already what an ST7789 expects, it sets the address window and sends each
frame with one ``bus.send()``. It should be considerably faster, but it needs
the display to be initialised first (for example by ``adafruit_st7789``) and
takes the panel over while playing. Modules smaller than the controller's
240x320 RAM need ``x_offset``/``y_offset`` for their rotation.

Examples
--------

* ``rv565_simpletest.py``: any board with ``board.DISPLAY``.
* ``rv565_pico2_st7789.py``: Raspberry Pi Pico 2 with a 2.0" 320x240 ST7789
  on SPI0 (SCK GP18, MOSI GP19, CS GP17, DC GP20, RST GP21, BL GP22, the
  wiring of the RV565 Pico 2 benchmark).
* ``rv565_pico2_direct.py``: the same wiring with ``DirectPlayer``.
* ``rv565_esp32s3_tft.py``: Adafruit ESP32-S3 TFT Feather (built-in 240x135
  ST7789).

Testing on a computer
---------------------

The tests run with CPython and stand-ins for ``displayio`` and
``bitmaptools``::

    python3 -m unittest discover -s ports/circuitpython/tests -v

They check the reader against ``tests/data/testpattern.rv565`` (all 24 frames
must equal CPython's zlib output), every validation rule of the format, that
the bitmap shows the right colour for every pixel, frame pacing and skipping,
and the bytes ``DirectPlayer`` sends.

Submitting to the Community Bundle
----------------------------------

The library is laid out like an Adafruit cookiecutter library so it can move
out unchanged when it has run on hardware:

1. Create a repository named ``CircuitPython_RV565`` with the contents of
   this folder (the module, ``examples/``, ``docs/``, ``tests/``,
   ``pyproject.toml``, ``requirements.txt``, ``LICENSE``), or regenerate it
   with ``cookiecutter gh:adafruit/cookiecutter-adafruit-circuitpython``
   (library name ``RV565``, target bundle *Community*) and copy the code in.
2. Add the cookiecutter's CI (pre-commit with black and pylint, Sphinx docs
   build, ``circuitpython-build-tools``) and make it pass; switch
   ``__version__`` to ``"0.0.0+auto.0"`` so the bundle tooling stamps
   releases.
3. Tag a release (GitHub release, semver).
4. Open a pull request on
   `CircuitPython_Community_Bundle
   <https://github.com/adafruit/CircuitPython_Community_Bundle>`_ adding the
   repository as a submodule under ``libraries/drivers`` (or ``helpers``),
   following its README.
5. Optionally publish to PyPI as ``circuitpython-rv565`` (the name the
   ``pyproject.toml`` already uses).

License
-------

MIT; see ``LICENSE``.
