"""Tests for the rv565 package. Run from the repository root:

    python3 -m unittest discover -s python/tests
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python" / "src"))

import rv565  # noqa: E402
from rv565.cli import testpattern_frames  # noqa: E402

VECTOR = ROOT / "tests" / "data" / "testpattern.rv565"

try:
    from PIL import Image, ImageSequence
    import rv565.pillow  # noqa: F401
except ImportError:  # Pillow is optional
    Image = None


class CoreTests(unittest.TestCase):
    def test_vector(self):
        clip = rv565.open(VECTOR)
        self.assertEqual((clip.width, clip.height, clip.fps, len(clip)), (180, 135, 24, 24))
        self.assertEqual(clip.verify(), 24)
        self.assertEqual(len(clip.frame(5)), 180 * 135 * 2)

    def test_round_trip(self):
        frames = list(testpattern_frames(6, 32, 16))
        buf = io.BytesIO()
        self.assertEqual(rv565.write(buf, 32, 16, 12, frames), 6)
        clip = rv565.open(buf.getvalue())
        self.assertEqual(list(clip), frames)
        self.assertEqual(clip.header.duration, 0.5)

    def test_matches_committed_vector_frames(self):
        # zlib output can differ between versions, so compare decoded frames.
        clip = rv565.open(VECTOR)
        self.assertEqual(list(clip), list(testpattern_frames(24, 180, 135)))

    def test_rejects_malformed(self):
        data = VECTOR.read_bytes()
        cases = {
            "not an RV565 file": b"XYZ" + data[3:],
            "unsupported RV565 version": data[:3] + b"\x05" + data[4:],
            "trailing bytes": data + b"\x00",
            "invalid length": data[:-1],
            "file too short": data[:5],
        }
        for message, bad in cases.items():
            with self.subTest(message):
                with self.assertRaisesRegex(rv565.RV565Error, message):
                    rv565.open(bad)

    def test_write_validates(self):
        with self.assertRaises(rv565.RV565Error):
            rv565.write(io.BytesIO(), 4, 4, 61, [bytes(32)])
        with self.assertRaises(rv565.RV565Error):
            rv565.write(io.BytesIO(), 4, 4, 31, [bytes(32)], version=6)
        with self.assertRaises(rv565.RV565Error):
            rv565.write(io.BytesIO(), 4, 4, 24, [bytes(16)], pixel_format="gray8", version=6)
        with self.assertRaises(rv565.RV565Error):
            rv565.write(io.BytesIO(), 4, 4, 24, [bytes(32)], keyframe_interval=0)
        with self.assertRaises(rv565.RV565Error):
            rv565.write(io.BytesIO(), 4, 4, 24, [bytes(32)], pixel_format="rgb555")
        with self.assertRaises(rv565.RV565Error):
            rv565.write(io.BytesIO(), 4, 4, 24, [bytes(31)])
        with self.assertRaises(rv565.RV565Error):
            rv565.write(io.BytesIO(), 4, 4, 24, [])

    def test_schedule_matches_paper_model(self):
        report = rv565.open(VECTOR).check_schedule(overlap=True)
        self.assertEqual(report.late_frames, 0)
        self.assertAlmostEqual(report.worst_frame_us, 31312.0)

    def test_rp2350_model(self):
        model = rv565.COST_RP2350_180x135
        self.assertLess(model.predict(256) + 33419.0, 41667.0)      # test pattern fits
        self.assertGreater(model.predict(30000) + 33419.0, 41667.0)  # a film frame does not

    def test_pixel_conversion(self):
        rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255, 0, 0, 0])
        be = rv565.rgb888_to_rgb565be(rgb)
        self.assertEqual(be.hex(), "f80007e0001fffff0000")
        self.assertEqual(rv565.rgb565be_to_rgb888(be), rgb)


V7 = ROOT / "tests" / "data" / "v7"


class ConformanceTests(unittest.TestCase):
    """The reference must match the committed vectors (tests/data/v7)."""

    @classmethod
    def setUpClass(cls):
        import json
        cls.manifest = json.loads((V7 / "manifest.json").read_text())

    def test_valid_sequential_and_seek(self):
        import hashlib
        import random
        for entry in self.manifest["valid"]:
            with self.subTest(entry["file"]):
                clip = rv565.open(V7 / entry["file"])
                h = clip.header
                self.assertEqual((h.version, h.width, h.height, h.fps, len(clip), h.pixel_format,
                                  h.codec, h.keyframe_interval, h.frame_bytes),
                                 (entry["version"], entry["width"], entry["height"], entry["fps"],
                                  entry["frames"], entry["pixel_format"], entry["codec"],
                                  entry["keyframe_interval"], entry["frame_bytes"]))
                self.assertEqual([clip.frame_type(i) for i in range(len(clip))],
                                 entry["frame_types"])
                got = [hashlib.sha256(f).hexdigest() for f in clip]
                self.assertEqual(got, entry["frame_sha256"])
                self.assertEqual([[list(r) for r in clip.changed_lines(i)]
                                  for i in range(len(clip))], entry["changed_lines"])
                order = list(range(len(clip)))
                random.Random(entry["file"]).shuffle(order)
                for i in order:
                    fresh = rv565.open(V7 / entry["file"])
                    self.assertEqual(hashlib.sha256(fresh.frame(i)).hexdigest(),
                                     entry["frame_sha256"][i])

    def test_invalid(self):
        for entry in self.manifest["invalid"]:
            with self.subTest(entry["file"]):
                data = (V7 / entry["file"]).read_bytes()
                if entry["stage"] == "open":
                    with self.assertRaises(rv565.RV565Error):
                        rv565.open(data)
                else:
                    clip = rv565.open(data)
                    with self.assertRaises(rv565.RV565Error):
                        clip.verify()

    def test_round_trip_every_format(self):
        rgb = bytes((x * 37 + y * 11) % 256 for y in range(7) for x in range(3 * 9))
        rgb2 = bytes((v + 64) % 256 for v in rgb)
        for fmt in rv565.PIXEL_FORMATS:
            for codec in rv565.CODECS:
                with self.subTest(fmt=fmt, codec=codec):
                    a, b = (rv565.convert(x, 9, 7, fmt) for x in (rgb, rgb2))
                    frames = [a, a, b, a, b, b]
                    buf = io.BytesIO()
                    rv565.write(buf, 9, 7, 60, frames, pixel_format=fmt, codec=codec,
                                keyframe_interval=3)
                    clip = rv565.open(buf.getvalue())
                    self.assertEqual(list(clip), frames)
                    self.assertEqual(clip.frame_type(1), "repeat")
                    self.assertEqual(clip.frame(4), b)
                    self.assertEqual(rv565.convert(rv565.to_rgb888(a, 9, 7, fmt), 9, 7, fmt), a)

    def test_tolerance_bounds_error(self):
        import random
        rnd = random.Random(7)
        base = bytes(rnd.randrange(256) for _ in range(3 * 12 * 9))
        noisy = [bytes(min(255, max(0, b + rnd.randint(-6, 6))) for b in base) for _ in range(8)]
        for fmt in ("rgb565be", "rgb888", "gray8", "gray4", "rgb444"):
            frames = [rv565.convert(f, 12, 9, fmt) for f in noisy]
            for tol in (0, 4, 12):
                with self.subTest(fmt=fmt, tol=tol):
                    buf = io.BytesIO()
                    rv565.write(buf, 12, 9, 24, frames, pixel_format=fmt, keyframe_interval=8,
                                tolerance=tol)
                    for got, want in zip(rv565.open(buf.getvalue()), frames):
                        a = rv565.to_rgb888(got, 12, 9, fmt)
                        b = rv565.to_rgb888(want, 12, 9, fmt)
                        self.assertLessEqual(max(abs(x - y) for x, y in zip(a, b)), tol)

    def test_partial_frames_written(self):
        buf = io.BytesIO()
        top = bytes(2 * 16 * 8)
        frames = [top + bytes(2 * 16 * 8), top + bytes([1]) * (2 * 16 * 8)]
        rv565.write(buf, 16, 16, 24, frames, keyframe_interval=4)
        clip = rv565.open(buf.getvalue())
        self.assertEqual(clip.frame_type(1), "partial")
        self.assertEqual(clip.changed_lines(1), [(8, 8)])
        self.assertEqual(list(clip), frames)
        buf = io.BytesIO()
        rv565.write(buf, 16, 16, 24, frames, keyframe_interval=4, band_lines=0)
        self.assertEqual(rv565.open(buf.getvalue()).frame_type(1), "delta")

    def test_write_v6_matches_vector(self):
        buf = io.BytesIO()
        rv565.write(buf, 180, 135, 24, testpattern_frames(24, 180, 135), 9, version=6)
        self.assertEqual(list(rv565.open(buf.getvalue())), list(rv565.open(VECTOR)))
        self.assertEqual(buf.getvalue()[3], 6)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "rv565.py"), *args],
                              capture_output=True, text=True, check=True).stdout

    def test_info_and_verify(self):
        self.assertIn("v6, 180x135, 24 FPS, 24 frames", self.run_cli("info", str(VECTOR)))
        self.assertIn("24 frames verified", self.run_cli("verify", str(VECTOR)))
        info = self.run_cli("info", str(V7 / "mono_vpage_zlib_k4.rv565"))
        self.assertIn("mono_vpage, 42 bytes per frame", info)
        self.assertIn("3 key, 6 delta, 0 partial, 1 repeat", info)
        self.assertIn("keyframe interval 4", info)

    def test_testpattern_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "tp.rv565")
            self.run_cli("testpattern", out, "--v6")
            self.assertEqual(Path(out).read_bytes()[3], 6)
            self.run_cli("testpattern", out, "--format", "gray4", "--size", "33x20", "--fps", "60")
            clip = rv565.open(out)
            self.assertEqual((clip.pixel_format, clip.fps, clip.header.keyframe_interval),
                             ("gray4", 60, 60))
            self.assertEqual(clip.verify(), 24)

    def test_c_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "clip.h")
            self.run_cli("c-array", str(VECTOR), out)
            self.assertIn("rv565_clip_size", Path(out).read_text())


@unittest.skipIf(Image is None, "Pillow not installed")
class PillowTests(unittest.TestCase):
    def test_open(self):
        with Image.open(VECTOR) as im:
            self.assertEqual(im.format, "RV565")
            self.assertEqual((im.size, im.mode, im.n_frames), ((180, 135), "RGB", 24))
            self.assertEqual(im.info["fps"], 24)
            first = im.getpixel((0, 0))
            im.seek(23)
            self.assertEqual(im.tell(), 23)
        self.assertEqual(first, (255, 255, 255))

    def test_save_all_round_trip(self):
        with Image.open(VECTOR) as im:
            frames = [f.copy() for f in ImageSequence.Iterator(im)]
        buf = io.BytesIO()
        frames[0].save(buf, format="RV565", save_all=True, append_images=frames[1:], fps=24)
        clip = rv565.open(buf.getvalue())
        self.assertEqual(list(clip), list(rv565.open(VECTOR)))

    def test_open_v7_formats(self):
        for name in ("rgb888_zlib_k4.rv565", "mono_vpage_stored_k3.rv565", "gray4_zlib_k4.rv565"):
            with self.subTest(name), Image.open(V7 / name) as im:
                clip = rv565.open(V7 / name)
                self.assertEqual((im.size, im.mode, im.n_frames), ((21, 13), "RGB", 10))
                im.seek(7)
                self.assertEqual(im.tobytes(), rv565.to_rgb888(clip.frame(7), 21, 13,
                                                               clip.pixel_format))

    def test_save_v7_options(self):
        frames = [Image.new("RGB", (16, 8), c) for c in ("white", "white", "black")]
        buf = io.BytesIO()
        frames[0].save(buf, format="RV565", save_all=True, append_images=frames[1:], fps=50,
                       pixel_format="mono", keyframe_interval=3)
        clip = rv565.open(buf.getvalue())
        self.assertEqual((clip.pixel_format, clip.fps, clip.frame_type(1)), ("mono", 50, "repeat"))
        self.assertEqual(clip.frame(2), bytes(16))

    def test_save_from_duration(self):
        frames = [Image.new("RGB", (8, 8), c) for c in ("red", "blue")]
        buf = io.BytesIO()
        frames[0].save(buf, format="RV565", save_all=True, append_images=frames[1:], duration=100)
        self.assertEqual(rv565.open(buf.getvalue()).fps, 10)


if __name__ == "__main__":
    unittest.main()
