#!/usr/bin/env python3
"""rv565: encode, inspect, verify and export RV565 video files.

  rv565.py encode SOURCE OUT.rv565 [--start S] [--seconds N] [--fps F] [--size WxH] [--level L]
  rv565.py info FILE.rv565 [--transfer-us T]
  rv565.py verify FILE.rv565
  rv565.py c-array FILE.rv565 OUT.h [--name NAME]
  rv565.py testpattern OUT.rv565 [--frames N] [--fps F] [--size WxH]

`encode` needs FFmpeg on PATH. Everything else uses only the standard library.
"""

import argparse
import hashlib
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

HEADER = struct.Struct("<3sBHHBBH")  # magic, version, width, height, fps, flags, frames
VERSION = 6

# Pooled decode-cost model from the RV565 paper: ESP32-S3, 240 MHz, ROM tinfl,
# 180x135 frames. Refit for other chips or frame sizes.
COST_INTERCEPT_US = 4858.0
COST_SLOPE_US_PER_BYTE = 0.1515


def write_container(path, width, height, fps, frames, level):
    """Write frames (iterable of RGB565BE bytes) and return the frame count."""
    frame_bytes = width * height * 2
    count = 0
    with open(path, "wb") as out:
        out.write(HEADER.pack(b"RV5", VERSION, width, height, fps, 0, 0))
        for frame in frames:
            if len(frame) != frame_bytes:
                raise SystemExit("frame has %d bytes, expected %d" % (len(frame), frame_bytes))
            packed = zlib.compress(frame, level)
            out.write(struct.pack("<I", len(packed)))
            out.write(packed)
            count += 1
        if not 0 < count <= 0xFFFF:
            raise SystemExit("frame count %d out of range" % count)
        out.seek(10)
        out.write(struct.pack("<H", count))
    return count


def read_container(path):
    data = Path(path).read_bytes()
    if len(data) < HEADER.size:
        raise SystemExit("file too short")
    magic, version, width, height, fps, flags, count = HEADER.unpack_from(data)
    if magic != b"RV5":
        raise SystemExit("not an RV565 file")
    if version != VERSION:
        raise SystemExit("unsupported RV565 version %d" % version)
    if not (width and height and 1 <= fps <= 30 and count):
        raise SystemExit("invalid header")
    sizes, payloads, offset = [], [], HEADER.size
    for i in range(count):
        if len(data) - offset < 4:
            raise SystemExit("truncated frame table at frame %d" % i)
        (size,) = struct.unpack_from("<I", data, offset)
        offset += 4
        if size == 0 or len(data) - offset < size:
            raise SystemExit("invalid length for frame %d" % i)
        sizes.append(size)
        payloads.append(data[offset:offset + size])
        offset += size
    if offset != len(data):
        raise SystemExit("trailing bytes after the last frame")
    return data, (width, height, fps, flags, count), sizes, payloads


def parse_size(text):
    try:
        width, height = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 180x135")
    if not (0 < width <= 1024 and 0 < height <= 1024):
        raise argparse.ArgumentTypeError("size out of range")
    return width, height


def ffmpeg_frames(source, start, seconds, fps, width, height):
    vf = ("fps=%d,scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,"
          "crop=%d:%d,format=rgb565be" % (fps, width, height, width, height))
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(source),
           "-t", str(seconds), "-an", "-vf", vf, "-pix_fmt", "rgb565be",
           "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    frame_bytes = width * height * 2
    try:
        while True:
            frame = proc.stdout.read(frame_bytes)
            if not frame:
                break
            if len(frame) != frame_bytes:
                raise SystemExit("ffmpeg returned a partial frame")
            yield frame
    finally:
        proc.stdout.close()
        if proc.wait() != 0:
            raise SystemExit("ffmpeg failed")


def cmd_encode(args):
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is required for encode")
    width, height = args.size
    count = write_container(args.output, width, height, args.fps,
                            ffmpeg_frames(args.source, args.start, args.seconds,
                                          args.fps, width, height), args.level)
    print("encoded %d frames, %dx%d, %d FPS -> %s (%d bytes)" % (
        count, width, height, args.fps, args.output, Path(args.output).stat().st_size))


def cmd_info(args):
    data, (width, height, fps, flags, count), sizes, _ = read_container(args.file)
    period = 1e6 / fps
    print("file      %s" % args.file)
    print("sha256    %s" % hashlib.sha256(data).hexdigest())
    print("format    RV565 v%d, %dx%d, %d FPS, %d frames (%.2f s)" % (
        VERSION, width, height, fps, count, count / fps))
    print("size      %d bytes (raw %d, ratio %.2fx)" % (
        len(data), HEADER.size + width * height * 2 * count,
        (HEADER.size + width * height * 2 * count) / len(data)))
    print("payloads  min %d, mean %.0f, max %d bytes" % (
        min(sizes), sum(sizes) / len(sizes), max(sizes)))
    if (width, height) != (180, 135):
        print("schedule  cost model fitted for 180x135; refit before trusting it")
    inflate = [COST_INTERCEPT_US + COST_SLOPE_US_PER_BYTE * s for s in sizes]
    for label, work in (("serial", [i + args.transfer_us for i in inflate]),
                        ("overlap", [max(i, args.transfer_us) for i in inflate])):
        late = sum(w > period for w in work)
        print("schedule  %-7s worst %.2f ms, %d/%d frames late at %d FPS (ESP32-S3 model)" % (
            label, max(work) / 1e3, late, count, fps))


def cmd_verify(args):
    _, (width, height, _, _, count), _, payloads = read_container(args.file)
    expected = width * height * 2
    for i, payload in enumerate(payloads):
        try:
            frame = zlib.decompress(payload)
        except zlib.error as exc:
            raise SystemExit("frame %d does not inflate: %s" % (i, exc))
        if len(frame) != expected:
            raise SystemExit("frame %d inflates to %d bytes, expected %d" % (i, len(frame), expected))
    print("ok: %d frames verified" % count)


def cmd_c_array(args):
    data, (width, height, fps, _, count), _, _ = read_container(args.file)
    name = args.name
    lines = ["/* Generated by tools/rv565.py from %s: %dx%d, %d FPS, %d frames. */" % (
        Path(args.file).name, width, height, fps, count),
        "#pragma once", "#include <stddef.h>", "#include <stdint.h>", "",
        "static const uint8_t %s[] __attribute__((aligned(4))) = {" % name]
    for i in range(0, len(data), 16):
        lines.append("    " + ", ".join("0x%02x" % b for b in data[i:i + 16]) + ",")
    lines += ["};", "static const size_t %s_size = sizeof(%s);" % (name, name), ""]
    Path(args.output).write_text("\n".join(lines))
    print("wrote %s (%d bytes of data)" % (args.output, len(data)))


def testpattern_frames(count, width, height):
    """Scrolling colour bars: deterministic and highly compressible."""
    bars = [(0xFF, 0xFF, 0xFF), (0xFF, 0xFF, 0x00), (0x00, 0xFF, 0xFF), (0x00, 0xFF, 0x00),
            (0xFF, 0x00, 0xFF), (0xFF, 0x00, 0x00), (0x00, 0x00, 0xFF), (0x00, 0x00, 0x00)]

    def rgb565be(r, g, b):
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        return bytes((v >> 8, v & 0xFF))

    for f in range(count):
        shift = f * width // count
        row = b"".join(rgb565be(*bars[((x + shift) % width) * len(bars) // width])
                       for x in range(width))
        yield row * height


def cmd_testpattern(args):
    width, height = args.size
    count = write_container(args.output, width, height, args.fps,
                            testpattern_frames(args.frames, width, height), 9)
    print("wrote %d-frame test pattern %dx%d -> %s (%d bytes)" % (
        count, width, height, args.output, Path(args.output).stat().st_size))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("encode", help="encode a video with FFmpeg")
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--start", type=float, default=0.0, help="offset into the source, in seconds")
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--fps", type=int, default=24, choices=range(1, 31), metavar="1-30")
    p.add_argument("--size", type=parse_size, default=(180, 135))
    p.add_argument("--level", type=int, default=1, choices=range(1, 10), metavar="1-9",
                   help="zlib level; 1 is what the paper measured")
    p.set_defaults(func=cmd_encode)

    p = sub.add_parser("info", help="print header, sizes and a schedule prediction")
    p.add_argument("file", type=Path)
    p.add_argument("--transfer-us", type=float, default=31312.0,
                   help="display transfer per frame (31312 us: 320x240 at 40 MHz SPI)")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("verify", help="check that every frame inflates to its RGB565 size")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("c-array", help="export a file as a C header for Arduino sketches")
    p.add_argument("file", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--name", default="rv565_clip")
    p.set_defaults(func=cmd_c_array)

    p = sub.add_parser("testpattern", help="write a synthetic scrolling colour-bar clip")
    p.add_argument("output", type=Path)
    p.add_argument("--frames", type=int, default=24)
    p.add_argument("--fps", type=int, default=24, choices=range(1, 31), metavar="1-30")
    p.add_argument("--size", type=parse_size, default=(180, 135))
    p.set_defaults(func=cmd_testpattern)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
