# SPDX-FileCopyrightText: 2026 Ayushman Bhattacharya
# SPDX-License-Identifier: MIT
"""Format version 7 conformance and players, with CPython and fake displayio.

Checks circuitpython_rv565 against tests/data/v7/manifest.json: every valid
vector decodes to the listed SHA-256 per frame, in order and by random seeks,
from bytes and from a file; every invalid vector is rejected at the stage the
manifest names ("open": opening plus building the index; "decode": decoding).
Player and DirectPlayer pixels are compared with the reference package's
to_rgb888.

    python3 -m unittest discover -s ports/circuitpython/tests -v
"""

import hashlib
import importlib.util
import json
import random
import struct
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import circuitpython_rv565 as rv565  # noqa: E402
import fakes  # noqa: E402

ROOT = HERE.parent.parent.parent
V7 = ROOT / "tests" / "data" / "v7"
MANIFEST = json.loads((V7 / "manifest.json").read_text())


def _load_reference():
    """The CPython reference package (python/src/rv565), loaded by path."""
    path = ROOT / "python" / "src" / "rv565" / "__init__.py"
    spec = importlib.util.spec_from_file_location("rv565_reference", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rv565_reference"] = module
    spec.loader.exec_module(module)
    return module


REFERENCE = _load_reference()


def sha(frame):
    return hashlib.sha256(bytes(frame)).hexdigest()


def vector(name):
    return (V7 / name).read_bytes()


def entry(name):
    for item in MANIFEST["valid"]:
        if item["file"] == name:
            return item
    raise KeyError(name)


class ConformanceTest(unittest.TestCase):
    def check_header(self, clip, item):
        self.assertEqual(
            (clip.version, clip.width, clip.height, clip.fps, len(clip),
             clip.pixel_format, clip.pixel_format_id, clip.codec,
             clip.keyframe_interval, clip.frame_bytes),
            (item["version"], item["width"], item["height"], item["fps"],
             item["frames"], item["pixel_format"], item["pixel_format_id"],
             item["codec"], item["keyframe_interval"], item["frame_bytes"]))
        self.assertEqual([clip.frame_type(i) for i in range(len(clip))],
                         item["frame_types"])

    def test_every_valid_vector_in_order(self):
        for item in MANIFEST["valid"]:
            with self.subTest(item["file"]):
                clip = rv565.open(vector(item["file"]))
                self.check_header(clip, item)
                self.assertEqual([sha(f) for f in clip], item["frame_sha256"])
                self.assertEqual(clip.verify(), item["frames"])

    def test_every_valid_vector_from_a_file(self):
        # Stored frames from a file are read straight into the frame buffer
        # (and stored deltas into a scratch buffer).
        for item in MANIFEST["valid"]:
            with self.subTest(item["file"]):
                with rv565.open(str(V7 / item["file"])) as clip:
                    self.check_header(clip, item)
                    self.assertEqual([sha(f) for f in clip], item["frame_sha256"])

    def test_every_valid_vector_by_random_seeks(self):
        rng = random.Random(7)
        for item in MANIFEST["valid"]:
            with self.subTest(item["file"]):
                n = item["frames"]
                order = [rng.randrange(n) for _ in range(3 * n)]
                order += [n - 1, 0, n - 1, n - 2, n - 2]
                for source in (vector(item["file"]), str(V7 / item["file"])):
                    with rv565.open(source) as clip:
                        for i in order:
                            self.assertEqual(sha(clip.frame(i)),
                                             item["frame_sha256"][i],
                                             "frame %d" % i)

    def test_every_invalid_vector_is_rejected_at_its_stage(self):
        for item in MANIFEST["invalid"]:
            with self.subTest(item["file"]):
                data = vector(item["file"])
                if item["stage"] == "open":
                    with self.assertRaises(rv565.RV565Error):
                        rv565.open(data).build_index()
                else:
                    clip = rv565.open(data)
                    clip.build_index()  # the container itself is valid
                    with self.assertRaises(rv565.RV565Error):
                        clip.verify()

    def test_invalid_vectors_rejected_from_files_too(self):
        for item in MANIFEST["invalid"]:
            with self.subTest(item["file"]):
                with self.assertRaises(rv565.RV565Error):
                    with rv565.open(str(V7 / item["file"])) as clip:
                        clip.verify()

    def test_xor_fallback_without_long_integers(self):
        saved = rv565._BIGINT
        rv565._BIGINT = False
        try:
            for name in ("rgb565be_zlib_forced_delta_k8.rv565",
                         "rgb444_stored_forced_delta_k8.rv565",
                         "mono_zlib_k4.rv565"):
                item = entry(name)
                clip = rv565.open(vector(name))
                self.assertEqual([sha(f) for f in clip], item["frame_sha256"])
        finally:
            rv565._BIGINT = saved

    def test_xor_into_across_chunks(self):
        rng = random.Random(1)
        for n in (0, 1, 3, rv565._XOR_CHUNK - 1, rv565._XOR_CHUNK,
                  2 * rv565._XOR_CHUNK + 5):
            a = bytes(rng.randrange(256) for _ in range(n))
            b = bytes(rng.randrange(256) for _ in range(n))
            dst = bytearray(a)
            rv565._xor_into(dst, memoryview(b))
            self.assertEqual(bytes(dst), bytes(x ^ y for x, y in zip(a, b)))

    def test_frame_buffer_is_reused(self):
        clip = rv565.open(vector("rgb565be_zlib_k4.rv565"))
        first = clip.frame(0)
        self.assertIs(clip.frame(1), first)
        self.assertEqual(len(first), clip.frame_bytes)

    def test_content_index_follows_repeats(self):
        clip = rv565.open(vector("rgb565be_zlib_k4.rv565"))
        self.assertEqual(clip.frame_type(5), "repeat")
        self.assertEqual(clip.content_index(5), 4)
        self.assertEqual(clip.content_index(6), 6)
        self.assertEqual(clip.payload_sizes()[5], 0)
        self.assertEqual(bytes(clip.payload(5)), b"")

    def test_header_reports_reserved_values(self):
        cases = {
            "invalid_pixel_format_9.rv565": "pixel format 9",
            "invalid_codec_2.rv565": "codec 2",
            "invalid_keyframe_interval_0.rv565": "keyframe interval 0",
            "invalid_header_size_15.rv565": "header size 15",
            "invalid_fps_61.rv565": "fps 61",
            "invalid_v6_fps_31.rv565": "fps 31",
        }
        for name, message in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(rv565.RV565Error, message):
                    rv565.open(vector(name))

    def test_index_rules(self):
        cases = {
            "invalid_frame_type_3.rv565": "frame type 3",
            "invalid_first_frame_delta.rv565": "frame 0 must be a keyframe",
            "invalid_missing_keyframe.rv565": "must be a keyframe",
            "invalid_repeat_with_body.rv565": "has a body",
            "invalid_stored_wrong_size.rv565": "stored frame",
        }
        for name, message in cases.items():
            with self.subTest(name):
                clip = rv565.open(vector(name))  # the header is fine
                with self.assertRaisesRegex(rv565.RV565Error, message):
                    clip.build_index()

    def test_frame_size(self):
        self.assertEqual(rv565.frame_size("rgb565be", 180, 135), 48600)
        self.assertEqual([rv565.frame_size(f, 21, 13) for f in rv565.PIXEL_FORMATS],
                         [REFERENCE.frame_size(f, 21, 13) for f in rv565.PIXEL_FORMATS])
        with self.assertRaises(rv565.RV565Error):
            rv565.frame_size("rgb332", 1, 1)

    def test_version(self):
        self.assertEqual(rv565.__version__, "2.0.0")


def expected_rgb(item, frame):
    """Packed RGB888 of a frame, from the reference package."""
    return REFERENCE.to_rgb888(bytes(frame), item["width"], item["height"],
                               item["pixel_format"])


class V7PlayerTest(unittest.TestCase):
    def setUp(self):
        self.displayio = fakes.install()

    def tearDown(self):
        fakes.uninstall()

    def shown_rgb(self, player):
        """What each bitmap pixel looks like through the shader, as RGB888."""
        out = bytearray()
        conv = player.converter
        for value in player.bitmap.values:
            if isinstance(conv, fakes.Palette):
                c = conv[value]
                out += bytes(((c >> 16) & 255, (c >> 8) & 255, c & 255))
            else:
                out += REFERENCE.rgb565be_to_rgb888(struct.pack(">H", conv.rgb565(value)))
        return bytes(out)

    def check_formats(self):
        for name, colorspace in (
                ("rgb565be_zlib_k4.rv565", "RGB565_SWAPPED"),
                ("rgb565le_stored_k3.rv565", "RGB565"),
                ("rgb565le_zlib_k4.rv565", "RGB565"),
                ("gray8_zlib_k4.rv565", None),
                ("gray4_stored_k3.rv565", None),
                ("mono_zlib_k4.rv565", None),
                ("mono_stored_forced_delta_k8.rv565", None)):
            with self.subTest(name):
                item = entry(name)
                player = rv565.Player(rv565.open(vector(name)), fakes.Display())
                if colorspace is None:
                    self.assertIsInstance(player.converter, fakes.Palette)
                else:
                    self.assertEqual(player.converter.input_colorspace, colorspace)
                for i in range(item["frames"]):
                    player.show(i)
                    frame = player.clip.frame(i)
                    self.assertEqual(self.shown_rgb(player), expected_rgb(item, frame),
                                     "frame %d" % i)

    def test_formats_through_readinto(self):
        self.check_formats()

    def test_formats_without_readinto(self):
        fakes.install(with_readinto=False)
        self.check_formats()

    def test_repeat_frames_cost_nothing(self):
        display = fakes.Display()
        clock = fakes.FakeClock()
        clip = rv565.open(vector("rgb565be_zlib_k4.rv565"))  # frame 5 repeats 4
        player = rv565.Player(clip, display, clock=clock, sleep=clock.sleep)
        decoded = []
        real_frame = clip.frame

        def counting_frame(i):
            decoded.append(i)
            return real_frame(i)

        clip.frame = counting_frame
        stats = player.play()
        self.assertEqual((stats.shown, stats.repeated, stats.skipped), (10, 1, 0))
        self.assertEqual(display.refreshes, 9)
        self.assertNotIn(5, decoded)
        self.assertIn("1 repeats", repr(stats))
        # Frame 6 is a delta on frame 5 = frame 4, and still decodes right.
        item = entry("rgb565be_zlib_k4.rv565")
        self.assertEqual(self.shown_rgb(player),
                         expected_rgb(item, clip.frame(9)))

    def test_skipping_through_deltas(self):
        clock = fakes.FakeClock()
        name = "rgb565be_zlib_forced_delta_k8.rv565"
        item = entry(name)
        clip = rv565.open(vector(name))
        player = rv565.Player(clip, None, clock=clock, sleep=clock.sleep)
        real_show = player.show

        def slow_show(i):
            clock.now += 0.25  # 4 FPS on a 12 FPS clip: two of three skipped
            result = real_show(i)
            self.assertEqual(self.shown_rgb(player), expected_rgb(item, clip.frame(i)))
            return result

        player.show = slow_show
        stats = player.play()
        self.assertGreater(stats.skipped, 0)
        self.assertEqual(stats.shown + stats.skipped, 10)

    def test_unsupported_format(self):
        for name in ("rgb444_zlib_k4.rv565", "rgb666_zlib_k4.rv565",
                     "rgb888_zlib_k4.rv565", "mono_vpage_zlib_k4.rv565"):
            with self.subTest(name):
                with self.assertRaisesRegex(rv565.RV565Error,
                                            "rgb565be, rgb565le, gray8, gray4, mono"):
                    rv565.Player(rv565.open(vector(name)))


class V7DirectPlayerTest(unittest.TestCase):
    def play(self, name):
        bus = fakes.FourWire()
        clock = fakes.FakeClock()
        clip = rv565.open(vector(name))
        player = rv565.DirectPlayer(clip, bus, 320, 240, clock=clock, sleep=clock.sleep)
        stats = player.play()
        return clip, bus, stats

    def test_rgb565be_deltas_and_repeats(self):
        name = "rgb565be_zlib_k4.rv565"
        item = entry(name)
        clip, bus, stats = self.play(name)
        self.assertEqual(stats.repeated, 1)
        frames = [data for cmd, data in bus.sent if cmd == 0x2C]
        expected = [h for i, h in enumerate(item["frame_sha256"]) if i != 5]
        self.assertEqual([sha(f) for f in frames], expected)
        self.assertEqual(bus.sent[0], (0x36, b"\x60"))
        self.assertEqual(bus.sent[-1], (0x36, b"\xc0"))
        self.assertNotIn(0x3A, [c for c, _ in bus.sent])

    def test_rgb666_switches_colmod(self):
        name = "rgb666_stored_k3.rv565"
        item = entry(name)
        clip, bus, stats = self.play(name)
        self.assertEqual(bus.sent[:2], [(0x36, b"\x60"), (0x3A, b"\x66")])
        self.assertEqual(bus.sent[-2:], [(0x36, b"\xc0"), (0x3A, b"\x55")])
        frames = [data for cmd, data in bus.sent if cmd == 0x2C]
        shown = [h for i, h in enumerate(item["frame_sha256"])
                 if item["frame_types"][i] != "repeat"]
        self.assertEqual([sha(f) for f in frames], shown)
        self.assertEqual(len(frames[0]), 3 * 21 * 13)

    def test_unsupported_format(self):
        with self.assertRaisesRegex(rv565.RV565Error, "rgb565be and rgb666"):
            rv565.DirectPlayer(rv565.open(vector("gray8_zlib_k4.rv565")),
                               fakes.FourWire(), 320, 240)


if __name__ == "__main__":
    unittest.main()
