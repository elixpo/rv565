# SPDX-FileCopyrightText: 2026 Ayushman Bhattacharya
# SPDX-License-Identifier: MIT
"""Minimal stand-ins for CircuitPython's displayio and bitmaptools.

They model only what circuitpython_rv565 relies on, with CircuitPython's
semantics: a Bitmap holds one integer per pixel, and bitmaptools.readinto
reads each 16-bit element in the board's native (little-endian) byte order
unless swap_bytes_in_element is set.
"""

import sys
import types


class Bitmap:
    def __init__(self, width, height, value_count):
        if not 1 <= value_count <= 65536:
            raise ValueError("value_count")
        self.width = width
        self.height = height
        self.value_count = value_count
        self.values = [0] * (width * height)
        self.writes = 0

    def __setitem__(self, index, value):
        if isinstance(index, tuple):
            x, y = index
            index = y * self.width + x
        if not 0 <= value < self.value_count:
            raise ValueError("value out of range")
        self.values[index] = value
        self.writes += 1

    def __getitem__(self, index):
        if isinstance(index, tuple):
            x, y = index
            index = y * self.width + x
        return self.values[index]


class Colorspace:
    RGB888 = "RGB888"
    RGB565 = "RGB565"
    RGB565_SWAPPED = "RGB565_SWAPPED"


class ColorConverter:
    def __init__(self, *, input_colorspace=Colorspace.RGB888, dither=False):
        self.input_colorspace = input_colorspace

    def rgb565(self, value):
        """The true RGB565 value a bitmap value stands for."""
        if self.input_colorspace == Colorspace.RGB565_SWAPPED:
            return ((value & 0xFF) << 8) | (value >> 8)
        if self.input_colorspace == Colorspace.RGB565:
            return value
        raise NotImplementedError(self.input_colorspace)


class TileGrid:
    def __init__(self, bitmap, *, pixel_shader):
        self.bitmap = bitmap
        self.pixel_shader = pixel_shader


class Group:
    def __init__(self, *, scale=1, x=0, y=0):
        self.scale = scale
        self.x = x
        self.y = y
        self.items = []

    def append(self, item):
        self.items.append(item)


class Display:
    def __init__(self, width=320, height=240):
        self.width = width
        self.height = height
        self.root_group = None
        self.auto_refresh = True
        self.refreshes = 0
        self.auto_refresh_seen = []

    def refresh(self, *, target_frames_per_second=None, minimum_frames_per_second=0):
        self.refreshes += 1
        self.auto_refresh_seen.append(self.auto_refresh)


class FourWire:
    def __init__(self):
        self.sent = []

    def send(self, command, data, *, toggle_every_byte=False):
        self.sent.append((command, bytes(data)))


def readinto(bitmap, file, bits_per_pixel, element_size=1,
             reverse_pixels_in_element=False, swap_bytes_in_element=False,
             reverse_rows=False):
    if bits_per_pixel != 16 or element_size != 2 or reverse_pixels_in_element \
            or reverse_rows:
        raise NotImplementedError("fake readinto models 16-bit elements only")
    for y in range(bitmap.height):
        row = file.read(2 * bitmap.width)
        for x in range(bitmap.width):
            lo, hi = row[2 * x], row[2 * x + 1]
            if swap_bytes_in_element:
                lo, hi = hi, lo
            bitmap[x, y] = lo | (hi << 8)


def install(with_readinto=True):
    """Register fake displayio and bitmaptools modules; return displayio."""
    displayio = types.ModuleType("displayio")
    for name in ("Bitmap", "Colorspace", "ColorConverter", "TileGrid", "Group"):
        setattr(displayio, name, globals()[name])
    bitmaptools = types.ModuleType("bitmaptools")
    if with_readinto:
        bitmaptools.readinto = readinto
    sys.modules["displayio"] = displayio
    sys.modules["bitmaptools"] = bitmaptools
    return displayio


def uninstall():
    sys.modules.pop("displayio", None)
    sys.modules.pop("bitmaptools", None)


class FakeClock:
    """A clock that advances only when told to (by decode work or sleep)."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
