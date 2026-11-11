"""RV565: video files for microcontroller displays.

Read, write and check RV565 files, the format played by the RV565
microcontroller library (arXiv:2610.35935). Version 7 files declare one of
nine pixel formats and a codec, and mix keyframes, XOR deltas and repeats;
version 6 files (RGB565 big-endian, zlib, every frame a keyframe) still read.

    import rv565

    clip = rv565.open("clip.rv565")
    print(clip.width, clip.height, clip.fps, len(clip), clip.pixel_format)
    frame = clip.frame(0)          # bytes in the clip's pixel format

    rv565.write("out.rv565", 180, 135, 24, frames)              # RGB565 BE, zlib
    rv565.write("oled.rv565", 128, 64, 15, frames,
                pixel_format="mono_vpage", keyframe_interval=15)

``rv565.convert`` turns packed RGB888 into any pixel format, and
``rv565.to_rgb888`` turns it back. With Pillow installed
(``pip install rv565[pillow]``), ``import rv565.pillow`` lets ``PIL.Image``
open and save RV565 files as animations.
"""

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "RV565Error", "Header", "Clip", "CostModel", "ScheduleReport",
    "COST_ESP32S3_180x135", "COST_RP2350_180x135", "open", "write", "encode_frames",
    "PIXEL_FORMATS", "CODECS", "frame_size", "convert", "to_rgb888",
    "rgb888_to_rgb565be", "rgb565be_to_rgb888",
]

__version__ = "2.0.0"

MAGIC = b"RV5"
VERSION = 7
VERSION_6 = 6
MAX_FPS = 60
MAX_FPS_V6 = 30
MAX_FRAMES = 0xFFFF
HEADER_V6 = struct.Struct("<3sBHHBBH")  # magic, version, width, height, fps, flags, frames
HEADER = struct.Struct("<3sBHHBBHBBBB")  # ... header size, pixel format, codec, keyframe interval
LENGTH = struct.Struct("<I")

# Pixel formats by value (docs/FORMAT.md).
PIXEL_FORMATS = ("rgb565be", "rgb565le", "rgb444", "rgb666", "rgb888",
                 "gray8", "gray4", "mono", "mono_vpage")
CODECS = ("stored", "zlib")
KEYFRAME, DELTA, REPEAT = 0, 1, 2
FRAME_TYPES = ("key", "delta", "repeat")


class RV565Error(ValueError):
    """The data is not a valid RV565 file, or an argument is out of range."""


def _format_index(pixel_format):
    if isinstance(pixel_format, int):
        if 0 <= pixel_format < len(PIXEL_FORMATS):
            return pixel_format
    elif pixel_format in PIXEL_FORMATS:
        return PIXEL_FORMATS.index(pixel_format)
    raise RV565Error("unknown pixel format %r" % (pixel_format,))


def _codec_index(codec):
    if isinstance(codec, int):
        if 0 <= codec < len(CODECS):
            return codec
    elif codec in CODECS:
        return CODECS.index(codec)
    raise RV565Error("unknown codec %r" % (codec,))


def row_bytes(pixel_format, width):
    """Bytes in one row of a frame (not defined for mono_vpage)."""
    fmt = PIXEL_FORMATS[_format_index(pixel_format)]
    return {"rgb565be": 2 * width, "rgb565le": 2 * width, "rgb444": (3 * width + 1) // 2,
            "rgb666": 3 * width, "rgb888": 3 * width, "gray8": width,
            "gray4": (width + 1) // 2, "mono": (width + 7) // 8,
            "mono_vpage": None}[fmt]


def frame_size(pixel_format, width, height):
    """Decoded size in bytes of one frame."""
    fmt = PIXEL_FORMATS[_format_index(pixel_format)]
    if fmt == "mono_vpage":
        return width * ((height + 7) // 8)
    return row_bytes(fmt, width) * height


@dataclass(frozen=True)
class Header:
    width: int
    height: int
    fps: int
    flags: int
    frames: int
    version: int = VERSION
    header_size: int = HEADER.size
    pixel_format: str = "rgb565be"
    codec: str = "zlib"
    keyframe_interval: int = 1

    @property
    def frame_bytes(self):
        """Decoded size of one frame, in the clip's pixel format."""
        return frame_size(self.pixel_format, self.width, self.height)

    @property
    def duration(self):
        """Length in seconds."""
        return self.frames / self.fps


def parse_header(data):
    """Parse and range-check a version 6 or 7 header."""
    if len(data) < HEADER_V6.size:
        raise RV565Error("file too short")
    magic, version, width, height, fps, flags, frames = HEADER_V6.unpack_from(data)
    if magic != MAGIC:
        raise RV565Error("not an RV565 file")
    if version == VERSION_6:
        if not (width and height and 1 <= fps <= MAX_FPS_V6 and frames):
            raise RV565Error("invalid header")
        return Header(width, height, fps, flags, frames, VERSION_6, HEADER_V6.size)
    if version != VERSION:
        raise RV565Error("unsupported RV565 version %d" % version)
    if len(data) < HEADER.size:
        raise RV565Error("file too short")
    fields = HEADER.unpack_from(data)
    header_size, fmt, codec, interval = fields[7:]
    if not (width and height and 1 <= fps <= MAX_FPS and frames):
        raise RV565Error("invalid header")
    if header_size < HEADER.size or len(data) < header_size:
        raise RV565Error("invalid header size %d" % header_size)
    if fmt >= len(PIXEL_FORMATS):
        raise RV565Error("unsupported pixel format %d" % fmt)
    if codec >= len(CODECS):
        raise RV565Error("unsupported codec %d" % codec)
    if interval == 0:
        raise RV565Error("invalid keyframe interval 0")
    return Header(width, height, fps, flags, frames, VERSION, header_size,
                  PIXEL_FORMATS[fmt], CODECS[codec], interval)


def _xor(a, b):
    return (int.from_bytes(a, "little") ^ int.from_bytes(b, "little")).to_bytes(len(a), "little")


class Clip:
    """An RV565 file held in memory, with an O(1) frame index.

    The whole container is validated on open (docs/FORMAT.md, Validation):
    everything except whether each zlib body inflates to the frame size, which
    ``verify()`` checks.
    """

    def __init__(self, data):
        self.data = bytes(data)
        self.header = h = parse_header(self.data)
        size = h.frame_bytes
        offsets, offset = [], h.header_size
        for i in range(h.frames):
            if len(self.data) - offset < LENGTH.size:
                raise RV565Error("truncated frame table at frame %d" % i)
            (length,) = LENGTH.unpack_from(self.data, offset)
            offset += LENGTH.size
            if length == 0 or len(self.data) - offset < length:
                raise RV565Error("invalid length for frame %d" % i)
            if h.version == VERSION_6:
                kind, body = KEYFRAME, offset
            else:
                kind, body = self.data[offset], offset + 1
                if kind >= len(FRAME_TYPES):
                    raise RV565Error("unsupported frame type %d at frame %d" % (kind, i))
                if i % h.keyframe_interval == 0 and kind != KEYFRAME:
                    raise RV565Error("frame %d must be a keyframe" % i)
                if kind == REPEAT and length != 1:
                    raise RV565Error("repeat frame %d has a body" % i)
                if kind != REPEAT and h.codec == "stored" and length - 1 != size:
                    raise RV565Error("stored frame %d has %d bytes, expected %d"
                                     % (i, length - 1, size))
            offsets.append((kind, body, offset + length - body))
            offset += length
        if offset != len(self.data):
            raise RV565Error("trailing bytes after the last frame")
        self._index = offsets
        self._last = None  # (index, decoded frame) for sequential decoding

    width = property(lambda self: self.header.width)
    height = property(lambda self: self.header.height)
    fps = property(lambda self: self.header.fps)
    pixel_format = property(lambda self: self.header.pixel_format)

    def __len__(self):
        return self.header.frames

    def frame_type(self, i):
        """'key', 'delta' or 'repeat'."""
        return FRAME_TYPES[self._index[self._check(i)][0]]

    def payload_sizes(self):
        """Body length of every frame (0 for repeats), in order."""
        return [length for _, _, length in self._index]

    def payload(self, i):
        """The encoded body of frame i (empty for a repeat)."""
        _, offset, length = self._index[self._check(i)]
        return self.data[offset:offset + length]

    def _body(self, i):
        body, size = self.payload(i), self.header.frame_bytes
        if self.header.codec == "stored":
            return body
        try:
            out = zlib.decompress(body)
        except zlib.error as exc:
            raise RV565Error("frame %d does not inflate: %s" % (i, exc)) from None
        if len(out) != size:
            raise RV565Error("frame %d inflates to %d bytes, expected %d" % (i, len(out), size))
        return out

    def _apply(self, i, prev):
        kind = self._index[i][0]
        if kind == KEYFRAME:
            return self._body(i)
        if kind == REPEAT:
            return prev
        return _xor(prev, self._body(i))

    def frame(self, i):
        """Frame i as bytes in the clip's pixel format (header.frame_bytes of them)."""
        self._check(i)
        if self._last is not None and self._last[0] in (i, i - 1):
            start, frame = self._last
            if start == i:
                return frame
        else:
            # The latest keyframe at or before i; the interval guarantees one
            # at i - (i mod K), so this looks back at most K - 1 records.
            start = i
            while self._index[start][0] != KEYFRAME:
                start -= 1
            frame = self._body(start)
        for j in range(start + 1, i + 1):
            frame = self._apply(j, frame)
        self._last = (i, frame)
        return frame

    def __iter__(self):
        return (self.frame(i) for i in range(len(self)))

    def verify(self):
        """Decode every frame; raises RV565Error on the first bad one."""
        self._last = None
        for i in range(len(self)):
            self.frame(i)
        return len(self)

    def check_schedule(self, model=None, transfer_us=31312.0, overlap=True):
        """Predict missed deadlines from the payload sizes alone.

        ``transfer_us`` is the display transfer per frame (31312 us is 320x240
        at 40 MHz SPI). With ``overlap`` the next frame inflates on another
        core during the transfer, so frame work is max(transfer, inflate);
        otherwise it is transfer + inflate. Repeats cost nothing to decode.
        """
        model = model or COST_ESP32S3_180x135
        period = 1e6 / self.fps
        sizes = self.payload_sizes()
        decode = [model.predict(s) if s else 0.0 for s in sizes]
        work = [max(transfer_us, d) if overlap else transfer_us + d for d in decode]
        return ScheduleReport(late_frames=sum(w > period for w in work),
                              max_payload=max(sizes), worst_frame_us=max(work),
                              period_us=period)

    def _check(self, i):
        if not 0 <= i < len(self):
            raise IndexError("frame %d out of range (0-%d)" % (i, len(self) - 1))
        return i


@dataclass(frozen=True)
class CostModel:
    """T_inflate(L) = intercept_us + slope_us_per_byte * L."""
    intercept_us: float
    slope_us_per_byte: float

    def predict(self, payload_len):
        return self.intercept_us + self.slope_us_per_byte * payload_len


@dataclass(frozen=True)
class ScheduleReport:
    late_frames: int
    max_payload: int
    worst_frame_us: float
    period_us: float


# Pooled fit from the RV565 paper: ESP32-S3 at 240 MHz, ROM tinfl, 180x135
# frames. Refit for other chips, clocks or frame sizes.
COST_ESP32S3_180x135 = CostModel(4858.0, 0.1515)

# Pooled fit on a Raspberry Pi Pico 2: RP2350 at 150 MHz, bundled tinfl, clip in
# XIP flash, 180x135 frames (docs/RESULTS_RP2350.md in the library repository).
COST_RP2350_180x135 = CostModel(8108.1, 0.2446)


def open(source):  # noqa: A001 - mirrors the module-level open() idiom
    """Open an RV565 file from a path, bytes, or a binary file object."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        return Clip(source)
    if hasattr(source, "read"):
        return Clip(source.read())
    return Clip(Path(source).read_bytes())


def _encode(data, codec, level):
    return bytes(data) if codec == "stored" else zlib.compress(bytes(data), level)


def encode_frames(frames, width, height, level=1, pixel_format="rgb565be", codec="zlib",
                  keyframe_interval=1):
    """Yield (frame type, body) for each frame, already in ``pixel_format``.

    Frames at multiples of ``keyframe_interval`` are keyframes; any other frame
    is a repeat when it equals the previous one, else the smaller of a delta
    and a keyframe. ``level`` is the zlib level (1 is what the paper measured).
    """
    size = frame_size(pixel_format, width, height)
    codec = CODECS[_codec_index(codec)]
    if keyframe_interval < 1 or keyframe_interval > 255:
        raise RV565Error("keyframe interval must be 1-255")
    prev = None
    for i, frame in enumerate(frames):
        frame = bytes(frame)
        if len(frame) != size:
            raise RV565Error("frame %d has %d bytes, expected %d" % (i, len(frame), size))
        if i % keyframe_interval == 0:
            yield KEYFRAME, _encode(frame, codec, level)
        elif frame == prev:
            yield REPEAT, b""
        else:
            key = _encode(frame, codec, level)
            delta = _encode(_xor(frame, prev), codec, level) if codec != "stored" else key
            yield (DELTA, delta) if len(delta) < len(key) else (KEYFRAME, key)
        prev = frame


def write(target, width, height, fps, frames, level=1, *, pixel_format="rgb565be",
          codec="zlib", keyframe_interval=1, version=VERSION):
    """Write frames (an iterable of bytes in ``pixel_format``) as an RV565 file.

    ``target`` is a path or a seekable binary file object. ``version=6``
    writes a version 6 file for players older than RV565 2.0; it allows only
    rgb565be, zlib and keyframe_interval 1. Returns the number of frames.
    """
    if not (0 < width <= 0xFFFF and 0 < height <= 0xFFFF):
        raise RV565Error("size %dx%d out of range" % (width, height))
    fmt, cod = _format_index(pixel_format), _codec_index(codec)
    if version == VERSION_6:
        if (fmt, cod, keyframe_interval) != (0, 1, 1):
            raise RV565Error("version 6 supports only rgb565be, zlib, keyframe_interval 1")
        if not 1 <= fps <= MAX_FPS_V6:
            raise RV565Error("fps must be 1-%d" % MAX_FPS_V6)
    elif version == VERSION:
        if not 1 <= fps <= MAX_FPS:
            raise RV565Error("fps must be 1-%d" % MAX_FPS)
    else:
        raise RV565Error("can write version 6 or 7, not %r" % (version,))
    if hasattr(target, "write"):
        return _write(target, width, height, fps, frames, level, fmt, cod,
                      keyframe_interval, version)
    with Path(target).open("wb") as out:
        return _write(out, width, height, fps, frames, level, fmt, cod,
                      keyframe_interval, version)


def _write(out, width, height, fps, frames, level, fmt, codec, interval, version):
    start = out.tell()
    if version == VERSION_6:
        out.write(HEADER_V6.pack(MAGIC, version, width, height, fps, 0, 0))
    else:
        out.write(HEADER.pack(MAGIC, version, width, height, fps, 0, 0,
                              HEADER.size, fmt, codec, interval))
    count = 0
    for kind, body in encode_frames(frames, width, height, level, fmt, codec, interval):
        count += 1
        if count > MAX_FRAMES:
            raise RV565Error("more than %d frames" % MAX_FRAMES)
        if version == VERSION_6:
            out.write(LENGTH.pack(len(body)))
        else:
            out.write(LENGTH.pack(len(body) + 1))
            out.write(bytes((kind,)))
        out.write(body)
    if count == 0:
        raise RV565Error("no frames")
    end = out.tell()
    out.seek(start + 10)
    out.write(struct.pack("<H", count))
    out.seek(end)
    return count


# Pixel conversion -----------------------------------------------------------

_R5 = bytes(v & 0xF8 for v in range(256))
_G_HI = bytes(v >> 5 for v in range(256))
_G_LO = bytes((v & 0x1C) << 3 for v in range(256))
_B5 = bytes(v >> 3 for v in range(256))


def _or_bytes(a, b):
    return (int.from_bytes(a, "big") | int.from_bytes(b, "big")).to_bytes(len(a), "big")


def rgb888_to_rgb565be(rgb):
    """Convert packed RGB888 bytes to RGB565 big-endian bytes."""
    rgb = bytes(rgb)
    if len(rgb) % 3:
        raise RV565Error("RGB data length is not a multiple of 3")
    r, g, b = rgb[0::3], rgb[1::3], rgb[2::3]
    hi = _or_bytes(r.translate(_R5), g.translate(_G_HI))
    lo = _or_bytes(g.translate(_G_LO), b.translate(_B5))
    out = bytearray(2 * len(r))
    out[0::2] = hi
    out[1::2] = lo
    return bytes(out)


def _expand(bits):
    top = (1 << bits) - 1
    return [(v * 255 + top // 2) // top for v in range(1 << bits)]


_E5, _E6 = _expand(5), _expand(6)
_HI_R = bytes(_E5[v >> 3] for v in range(256))
_LO_B = bytes(_E5[v & 0x1F] for v in range(256))
_HI_G = bytes((v & 0x07) << 3 for v in range(256))
_LO_G = bytes(v >> 5 for v in range(256))
_G6 = bytes(_E6[v & 0x3F] for v in range(256))


def rgb565be_to_rgb888(data):
    """Convert RGB565 big-endian bytes to packed RGB888 bytes."""
    data = bytes(data)
    if len(data) % 2:
        raise RV565Error("RGB565 data length is odd")
    hi, lo = data[0::2], data[1::2]
    r = hi.translate(_HI_R)
    b = lo.translate(_LO_B)
    g = _or_bytes(hi.translate(_HI_G), lo.translate(_LO_G)).translate(_G6)
    out = bytearray(3 * len(hi))
    out[0::3], out[1::3], out[2::3] = r, g, b
    return bytes(out)


# Every pixel format -----------------------------------------------------------

def _luma(r, g, b):
    return (299 * r + 587 * g + 114 * b + 500) // 1000


def convert(rgb, width, height, pixel_format):
    """Convert packed RGB888 bytes (width * height pixels) to one frame in
    ``pixel_format``, with the conversions in docs/FORMAT.md, Writing."""
    rgb = bytes(rgb)
    if len(rgb) != 3 * width * height:
        raise RV565Error("expected %d RGB bytes, got %d" % (3 * width * height, len(rgb)))
    fmt = PIXEL_FORMATS[_format_index(pixel_format)]
    if fmt == "rgb565be":
        return rgb888_to_rgb565be(rgb)
    if fmt == "rgb565le":
        be = rgb888_to_rgb565be(rgb)
        out = bytearray(len(be))
        out[0::2], out[1::2] = be[1::2], be[0::2]
        return bytes(out)
    if fmt == "rgb888":
        return rgb
    if fmt == "rgb666":
        return rgb.translate(bytes(v & 0xFC for v in range(256)))
    out = bytearray(frame_size(fmt, width, height))
    if fmt == "rgb444":
        stride = row_bytes(fmt, width)
        for y in range(height):
            nibbles = []
            for x in range(width):
                p = 3 * (y * width + x)
                nibbles += (rgb[p] >> 4, rgb[p + 1] >> 4, rgb[p + 2] >> 4)
            if len(nibbles) % 2:
                nibbles.append(0)
            for k in range(0, len(nibbles), 2):
                out[y * stride + k // 2] = (nibbles[k] << 4) | nibbles[k + 1]
        return bytes(out)
    lum = bytes(_luma(rgb[p], rgb[p + 1], rgb[p + 2]) for p in range(0, len(rgb), 3))
    if fmt == "gray8":
        return lum
    if fmt == "gray4":
        stride = row_bytes(fmt, width)
        for y in range(height):
            for x in range(width):
                v = lum[y * width + x] >> 4
                out[y * stride + x // 2] |= v << 4 if x % 2 == 0 else v
        return bytes(out)
    if fmt == "mono":
        stride = row_bytes(fmt, width)
        for y in range(height):
            for x in range(width):
                if lum[y * width + x] >= 128:
                    out[y * stride + x // 8] |= 0x80 >> (x % 8)
        return bytes(out)
    # mono_vpage
    for y in range(height):
        for x in range(width):
            if lum[y * width + x] >= 128:
                out[(y // 8) * width + x] |= 1 << (y % 8)
    return bytes(out)


def to_rgb888(frame, width, height, pixel_format):
    """Convert one frame in ``pixel_format`` to packed RGB888 bytes, for
    previews and tools. Channels with fewer bits are scaled to 0-255."""
    frame = bytes(frame)
    fmt = PIXEL_FORMATS[_format_index(pixel_format)]
    if len(frame) != frame_size(fmt, width, height):
        raise RV565Error("expected %d bytes, got %d"
                         % (frame_size(fmt, width, height), len(frame)))
    if fmt == "rgb565be":
        return rgb565be_to_rgb888(frame)
    if fmt == "rgb565le":
        be = bytearray(len(frame))
        be[0::2], be[1::2] = frame[1::2], frame[0::2]
        return rgb565be_to_rgb888(be)
    if fmt == "rgb888":
        return frame
    if fmt == "rgb666":
        return frame.translate(bytes(_E6[v >> 2] for v in range(256)))
    out = bytearray(3 * width * height)
    stride = row_bytes(fmt, width) if fmt != "mono_vpage" else 0
    for y in range(height):
        for x in range(width):
            p = 3 * (y * width + x)
            if fmt == "rgb444":
                n = 3 * x
                nib = [(frame[y * stride + (n + k) // 2] >> (4 if (n + k) % 2 == 0 else 0)) & 0xF
                       for k in range(3)]
                out[p:p + 3] = bytes(v * 17 for v in nib)
                continue
            if fmt == "gray8":
                v = frame[y * width + x]
            elif fmt == "gray4":
                b = frame[y * stride + x // 2]
                v = ((b >> 4) if x % 2 == 0 else (b & 0xF)) * 17
            elif fmt == "mono":
                v = 255 if frame[y * stride + x // 8] & (0x80 >> (x % 8)) else 0
            else:  # mono_vpage
                v = 255 if frame[(y // 8) * width + x] & (1 << (y % 8)) else 0
            out[p:p + 3] = bytes((v, v, v))
    return bytes(out)
