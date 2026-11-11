# SPDX-FileCopyrightText: 2026 Ayushman Bhattacharya
# SPDX-License-Identifier: MIT
"""
`circuitpython_rv565`
================================================================================

Play RV565 video files on CircuitPython displays.

RV565 (https://github.com/elixpo/rv565, arXiv:2610.35935) stores video as
independently zlib-compressed frames whose decoded bytes are big-endian
RGB565, the native pixel format of ST7789-class SPI panels. This module reads
version 6 files and shows them with ``displayio``.

This is the easy route, not the fast one: the C library plays 24 FPS with
dual-core decoding, while this pure-Python reader inflates with CircuitPython's
``zlib`` and draws through ``displayio``, so expect a few frames per second.
Frames that fall behind are skipped, so a clip still plays at its own speed.

* Author: Ayushman Bhattacharya

Implementation Notes
--------------------

**Hardware:**

* Any CircuitPython board whose build includes ``zlib`` (most ESP32-S3 and
  RP2350 boards), with an RGB565 display such as an ST7789.

**Software and Dependencies:**

* CircuitPython firmware: https://circuitpython.org/downloads
* ``zlib``, ``displayio`` and ``bitmaptools`` built-in modules
"""

import struct

try:
    from zlib import decompress as _zlib_decompress
except ImportError:  # boards built without zlib
    _zlib_decompress = None

try:
    from time import monotonic_ns as _monotonic_ns
except ImportError:  # boards without long integers
    _monotonic_ns = None

__version__ = "0.1.0"
__repo__ = "https://github.com/elixpo/rv565.git"

MAGIC = b"RV5"
VERSION = 6
MAX_FPS = 30
HEADER_SIZE = 12
_HEADER = "<3sBHHBBH"  # magic, version, width, height, fps, flags, frames
_LENGTH = "<I"

# ST7789 / ILI9341 commands used by DirectPlayer.
_CASET = 0x2A
_RASET = 0x2B
_RAMWR = 0x2C

_builtin_open = open  # noqa: A001 - this module defines its own open()


class RV565Error(ValueError):
    """The data is not a valid RV565 file, or a frame does not decode."""


def parse_header(data):
    """Parse and range-check the 12-byte header.

    :param data: at least the first 12 bytes of the file
    :return: ``(width, height, fps, flags, frames)``
    """
    if len(data) < HEADER_SIZE:
        raise RV565Error("file too short")
    magic, version, width, height, fps, flags, frames = struct.unpack_from(
        _HEADER, data, 0
    )
    if bytes(magic) != MAGIC:
        raise RV565Error("not an RV565 file")
    if version != VERSION:
        raise RV565Error("unsupported RV565 version %d" % version)
    if not width or not height:
        raise RV565Error("invalid header: zero width or height")
    if not 1 <= fps <= MAX_FPS:
        raise RV565Error("invalid header: fps %d outside 1-30" % fps)
    if not frames:
        raise RV565Error("invalid header: no frames")
    return width, height, fps, flags, frames


class _BytesSource:
    """Random access over bytes already in RAM (no copies)."""

    def __init__(self, data):
        self._view = memoryview(data)
        self.size = len(self._view)

    def read(self, offset, size):
        return self._view[offset : offset + size]

    def close(self):
        pass


class _FileSource:
    """Random access over a file object opened in binary mode."""

    def __init__(self, stream, owned):
        self._stream = stream
        self._owned = owned
        stream.seek(0, 2)
        self.size = stream.tell()

    def read(self, offset, size):
        self._stream.seek(offset)
        return self._stream.read(size)

    def close(self):
        if self._owned:
            self._stream.close()


class Clip:
    """An RV565 file: header, a lazily built frame index, and frame decoding.

    Use :func:`open` rather than constructing this directly. Only the header
    is read on open; the frame index is built on first use by one pass over
    the length fields (4 bytes of RAM per frame), which also validates the
    whole container: every length is nonzero and inside the file, and no
    bytes follow the last frame.

    :param source: an internal byte source (see :func:`open`)
    :param decompress: function inflating a zlib stream to bytes; defaults to
        the built-in ``zlib.decompress``
    """

    def __init__(self, source, decompress=None):
        self._source = source
        try:
            header = bytes(source.read(0, HEADER_SIZE))
            (
                self.width,
                self.height,
                self.fps,
                self.flags,
                self.frame_count,
            ) = parse_header(header)
        except Exception:
            source.close()
            raise
        self.frame_bytes = 2 * self.width * self.height
        self._offsets = None
        self._decompress = decompress or _zlib_decompress
        self._sized_inflate = decompress is None  # try passing the output size

    # -- container -----------------------------------------------------------

    def __len__(self):
        return self.frame_count

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """Close the underlying file, if :func:`open` opened it."""
        self._source.close()

    @property
    def duration(self):
        """Length in seconds."""
        return self.frame_count / self.fps

    @property
    def indexed(self):
        """True once the frame index has been built."""
        return self._offsets is not None

    def build_index(self):
        """Scan the length fields once and validate the container.

        Called automatically by :meth:`frame`, :meth:`payload` and
        :meth:`payload_sizes`; call it yourself to fail early on a damaged
        file. Raises :class:`RV565Error` if the container is invalid.
        """
        if self._offsets is not None:
            return
        import array  # pylint: disable=import-outside-toplevel

        offsets = array.array("L")
        size = self._source.size
        offset = HEADER_SIZE
        for i in range(self.frame_count):
            if size - offset < 4:
                raise RV565Error("truncated frame table at frame %d" % i)
            (length,) = struct.unpack_from(
                _LENGTH, bytes(self._source.read(offset, 4)), 0
            )
            offset += 4
            if length == 0 or size - offset < length:
                raise RV565Error("invalid length for frame %d" % i)
            offsets.append(offset)
            offset += length
        if offset != size:
            raise RV565Error("trailing bytes after the last frame")
        self._offsets = offsets

    def _span(self, i):
        if not 0 <= i < self.frame_count:
            raise IndexError(
                "frame %d out of range (0-%d)" % (i, self.frame_count - 1)
            )
        self.build_index()
        start = self._offsets[i]
        if i + 1 < self.frame_count:
            end = self._offsets[i + 1] - 4
        else:
            end = self._source.size
        return start, end - start

    def payload_sizes(self):
        """Compressed length of every frame, in order."""
        return [self._span(i)[1] for i in range(self.frame_count)]

    def payload(self, i):
        """The zlib payload of frame ``i`` (bytes or a memoryview)."""
        offset, length = self._span(i)
        return self._source.read(offset, length)

    # -- decoding ------------------------------------------------------------

    def _inflate(self, data):
        if self._decompress is None:
            raise RV565Error(
                "this CircuitPython build has no zlib module; use a board "
                "whose build includes zlib (most ESP32-S3 and RP2350 boards), "
                "or pass decompress= to open()"
            )
        if self._sized_inflate:
            # CPython and some CircuitPython builds accept (data, wbits,
            # bufsize); wbits 15 means "zlib header, any window up to 32 KiB".
            # Builds that only take (data) raise TypeError once, and from then
            # on we call the one-argument form.
            try:
                return self._decompress(data, 15, self.frame_bytes)
            except TypeError:
                self._sized_inflate = False
        return self._decompress(data)

    def frame(self, i):
        """Frame ``i`` as big-endian RGB565 bytes (``2 * width * height``).

        Raises :class:`RV565Error` if the payload does not inflate to exactly
        that many bytes.
        """
        payload = self.payload(i)
        try:
            data = self._inflate(payload)
        except MemoryError:
            raise
        except RV565Error:
            raise
        except Exception as exc:  # zlib.error, ValueError, OSError by port
            raise RV565Error("frame %d does not inflate: %s" % (i, exc))
        if len(data) != self.frame_bytes:
            raise RV565Error(
                "frame %d inflates to %d bytes, expected %d"
                % (i, len(data), self.frame_bytes)
            )
        return data

    def __iter__(self):
        for i in range(self.frame_count):
            yield self.frame(i)

    def verify(self):
        """Inflate every frame; raise :class:`RV565Error` on the first bad one.

        :return: the number of frames checked
        """
        for i in range(self.frame_count):
            self.frame(i)
        return self.frame_count


def open(source, decompress=None):  # noqa: A001 pylint: disable=redefined-builtin
    """Open an RV565 clip.

    :param source: a path such as ``"/clip.rv565"`` or ``"/sd/clip.rv565"``,
        a file object opened in binary mode, or ``bytes``/``bytearray``
    :param decompress: optional replacement for ``zlib.decompress``
    :return: a :class:`Clip`

    A path is opened and read frame by frame, so the clip does not have to fit
    in RAM; :meth:`Clip.close` (or a ``with`` block) closes it again.
    """
    if isinstance(source, (bytes, bytearray, memoryview)):
        return Clip(_BytesSource(source), decompress)
    if hasattr(source, "read"):
        return Clip(_FileSource(source, False), decompress)
    return Clip(_FileSource(_builtin_open(source, "rb"), True), decompress)


# -- pacing ------------------------------------------------------------------


class _Clock:
    """Seconds since the last reset(), as a float.

    CircuitPython floats have about 22 bits of mantissa, so absolute uptime in
    seconds loses millisecond precision after an hour or so. Counting from the
    start of each play() in integer nanoseconds keeps the values small.
    """

    def __init__(self):
        self._t0 = 0
        self.reset()

    def reset(self):
        if _monotonic_ns is not None:
            self._t0 = _monotonic_ns()
        else:
            import time  # pylint: disable=import-outside-toplevel

            self._t0 = time.monotonic()

    def __call__(self):
        if _monotonic_ns is not None:
            return (_monotonic_ns() - self._t0) / 1e9
        import time  # pylint: disable=import-outside-toplevel

        return time.monotonic() - self._t0


def _default_sleep(seconds):
    import time  # pylint: disable=import-outside-toplevel

    time.sleep(seconds)


class PlayStats:
    """What :meth:`Player.play` achieved.

    :ivar shown: frames decoded and drawn
    :ivar skipped: frames dropped to keep up with the clip's rate
    :ivar elapsed: wall time in seconds
    :ivar decode_time: seconds spent inflating
    :ivar draw_time: seconds spent filling the bitmap and refreshing
    """

    def __init__(self, fps):
        self.target_fps = fps
        self.shown = 0
        self.skipped = 0
        self.elapsed = 0.0
        self.decode_time = 0.0
        self.draw_time = 0.0

    @property
    def fps(self):
        """Frames actually shown per second."""
        return self.shown / self.elapsed if self.elapsed > 0 else 0.0

    def __repr__(self):
        per = self.shown or 1
        return (
            "<PlayStats %.2f of %d FPS: %d shown, %d skipped in %.2f s; "
            "%.1f ms inflate + %.1f ms draw per frame>"
            % (
                self.fps,
                self.target_fps,
                self.shown,
                self.skipped,
                self.elapsed,
                1000 * self.decode_time / per,
                1000 * self.draw_time / per,
            )
        )


class _Pacer:
    """Shared play loop: shows frames on the clip's timeline, skipping late ones."""

    def __init__(self, clip, clock=None, sleep=None):
        self.clip = clip
        self._clock = clock or _Clock()
        self._sleep = sleep or _default_sleep

    def show(self, i):
        """Decode and draw frame ``i``; return (decode_s, draw_s)."""
        raise NotImplementedError

    def play(self, loops=1, start=0, on_frame=None):
        """Play the clip at its frame rate, skipping frames that are late.

        :param loops: how many times to play the clip; 0 loops forever
        :param start: first frame
        :param on_frame: optional ``callback(index, stats)``; return ``False``
            to stop
        :return: :class:`PlayStats`
        """
        clip = self.clip
        n = len(clip)
        fps = clip.fps
        total = n * loops - start if loops else None
        stats = PlayStats(fps)
        if hasattr(self._clock, "reset"):
            self._clock.reset()
        t0 = self._clock()
        position = 0  # frames since start on the clip's timeline
        while total is None or position < total:
            index = (start + position) % n
            decode_s, draw_s = self.show(index)
            stats.shown += 1
            stats.decode_time += decode_s
            stats.draw_time += draw_s
            if on_frame is not None and on_frame(index, stats) is False:
                break
            position += 1
            now = self._clock()
            due = int((now - t0) * fps)  # frame the timeline has reached
            if due > position:
                # Behind: drop the frames that are already late.
                if total is not None and due > total:
                    due = total
                stats.skipped += due - position
                position = due
            else:
                wait = t0 + position / fps - now
                if wait > 0:
                    self._sleep(wait)
        stats.elapsed = self._clock() - t0
        return stats


class Player(_Pacer):
    """Show an RV565 clip through ``displayio``.

    Frames are inflated into a ``displayio.Bitmap`` with 65536 values and
    drawn through a ``ColorConverter`` whose input colorspace is
    ``RGB565_SWAPPED``. RV565 stores pixels big-endian; copying those bytes
    into the bitmap's little-endian 16-bit storage gives byte-swapped values,
    which is what ``RGB565_SWAPPED`` describes, so no per-pixel conversion
    happens in Python.

    :param clip: a :class:`Clip`
    :param display: a display object (``board.DISPLAY``, ``busdisplay.BusDisplay``
        or ``adafruit_st7789.ST7789``), or ``None`` to only build :attr:`group`
    :param int scale: integer zoom for the group (1 = native size)
    :param x: left edge on the display; centred when omitted
    :param y: top edge on the display; centred when omitted
    :param clock: function returning seconds (for tests)
    :param sleep: function sleeping for seconds (for tests)
    """

    def __init__(
        self, clip, display=None, scale=1, x=None, y=None, clock=None, sleep=None
    ):
        super().__init__(clip, clock, sleep)
        import displayio  # pylint: disable=import-outside-toplevel

        try:
            import bitmaptools  # pylint: disable=import-outside-toplevel
        except ImportError:
            bitmaptools = None
        self._readinto = getattr(bitmaptools, "readinto", None)
        try:
            from io import BytesIO  # pylint: disable=import-outside-toplevel
        except ImportError:
            BytesIO = None  # pylint: disable=invalid-name
        if BytesIO is None:
            self._readinto = None
        self._bytesio = BytesIO

        self.display = display
        self.bitmap = displayio.Bitmap(clip.width, clip.height, 65536)
        self.converter = displayio.ColorConverter(
            input_colorspace=displayio.Colorspace.RGB565_SWAPPED
        )
        self.tilegrid = displayio.TileGrid(self.bitmap, pixel_shader=self.converter)
        if display is not None:
            if x is None:
                x = max(0, (display.width - clip.width * scale) // 2)
            if y is None:
                y = max(0, (display.height - clip.height * scale) // 2)
        self.group = displayio.Group(scale=scale, x=x or 0, y=y or 0)
        self.group.append(self.tilegrid)
        if display is not None:
            display.root_group = self.group

    def blit(self, frame):
        """Copy one decoded frame (big-endian RGB565 bytes) into :attr:`bitmap`."""
        if self._readinto is not None:
            # One C call: reads 16-bit elements into the bitmap row by row,
            # handling the bitmap's row padding.
            self._readinto(
                self.bitmap, self._bytesio(frame), bits_per_pixel=16, element_size=2
            )
            return
        # Fallback without bitmaptools.readinto: one Python step per pixel,
        # far slower, but correct.
        bitmap = self.bitmap
        for i in range(len(frame) // 2):
            bitmap[i] = frame[2 * i] | (frame[2 * i + 1] << 8)

    def show(self, i):
        """Decode frame ``i``, draw it, and refresh the display.

        :return: ``(inflate_seconds, draw_seconds)``
        """
        clock = self._clock
        t0 = clock()
        frame = self.clip.frame(i)
        t1 = clock()
        self.blit(frame)
        if self.display is not None and not getattr(self.display, "auto_refresh", True):
            self.display.refresh()
        return t1 - t0, clock() - t1

    def play(self, loops=1, start=0, on_frame=None):
        """Play at the clip's rate, skipping late frames; see :class:`PlayStats`.

        ``auto_refresh`` is turned off while playing so each frame is pushed
        once, and restored afterwards.
        """
        display = self.display
        restore = None
        if display is not None and hasattr(display, "auto_refresh"):
            restore = display.auto_refresh
            display.auto_refresh = False
        try:
            return super().play(loops, start, on_frame)
        finally:
            if restore is not None:
                display.auto_refresh = restore


class DirectPlayer(_Pacer):
    """Experimental: send frames straight to an ST7789 over its display bus.

    RV565 frames are already in the byte order an ST7789 expects on SPI, so
    this skips ``displayio`` entirely: it sets the address window and sends
    the inflated bytes with one ``bus.send()`` per frame. It is much faster
    than :class:`Player` but bypasses ``displayio``, so the display must be
    initialised first (for example by ``adafruit_st7789.ST7789``) and then left
    alone: this class sets ``root_group = None`` and turns off
    ``auto_refresh``.

    :param clip: a :class:`Clip`
    :param bus: the ``fourwire.FourWire`` (CircuitPython 9+) or
        ``displayio.FourWire`` bus the display was created on
    :param int panel_width: width of the panel in the current rotation
    :param int panel_height: height of the panel in the current rotation
    :param int x_offset: controller column offset for this module and rotation
        (0 for 320x240 panels; 40 or 52/53 for 240x135 ones, depending on
        rotation)
    :param int y_offset: controller row offset, likewise
    :param display: the display object, so it can be quieted while playing
    """

    def __init__(
        self,
        clip,
        bus,
        panel_width,
        panel_height,
        x_offset=0,
        y_offset=0,
        display=None,
        clock=None,
        sleep=None,
    ):
        super().__init__(clip, clock, sleep)
        if clip.width > panel_width or clip.height > panel_height:
            raise RV565Error(
                "clip is %dx%d, larger than the %dx%d panel"
                % (clip.width, clip.height, panel_width, panel_height)
            )
        self.bus = bus
        self.display = display
        x0 = (panel_width - clip.width) // 2 + x_offset
        y0 = (panel_height - clip.height) // 2 + y_offset
        self._caset = struct.pack(">HH", x0, x0 + clip.width - 1)
        self._raset = struct.pack(">HH", y0, y0 + clip.height - 1)

    def show(self, i):
        """Decode frame ``i`` and send it to the panel."""
        clock = self._clock
        t0 = clock()
        frame = self.clip.frame(i)
        t1 = clock()
        bus = self.bus
        bus.send(_CASET, self._caset)
        bus.send(_RASET, self._raset)
        bus.send(_RAMWR, frame)
        return t1 - t0, clock() - t1

    def play(self, loops=1, start=0, on_frame=None):
        """Play at the clip's rate, skipping late frames."""
        display = self.display
        if display is not None:
            display.root_group = None
            if hasattr(display, "auto_refresh"):
                display.auto_refresh = False
        return super().play(loops, start, on_frame)
