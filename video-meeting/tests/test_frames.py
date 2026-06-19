"""Frame-step logic tests — stdlib only; ffmpeg/Ollama parts skip when absent."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import fixtures as F

sys.path.insert(0, F.SCRIPTS)


class TestOllamaImages(unittest.TestCase):
    def test_images_included_only_when_present(self):
        from ollama_client import build_payload
        p = build_payload("v", "describe", images=["BASE64DATA"])
        self.assertEqual(p["images"], ["BASE64DATA"])
        p2 = build_payload("v", "describe")
        self.assertNotIn("images", p2)


class TestTimestampParsing(unittest.TestCase):
    def test_formats(self):
        import extract_frames as E
        self.assertEqual(E.parse_timestamp("10:20"), 620)       # mm:ss
        self.assertEqual(E.parse_timestamp("01:10:23"), 4223)   # hh:mm:ss
        self.assertEqual(E.parse_timestamp("90"), 90)           # bare seconds
        self.assertEqual(E.parse_timestamp("0:05"), 5)

    def test_rejects_bad(self):
        import extract_frames as E
        for bad in ("1:2:3:4", "aa:bb", "-5", "", "10:xx"):
            with self.assertRaises(ValueError, msg=bad):
                E.parse_timestamp(bad)


class TestSlideIdAndManifest(unittest.TestCase):
    def test_slide_id(self):
        import extract_frames as E
        self.assertEqual(E.slide_id(1), "slide-0001")
        self.assertEqual(E.slide_id(42), "slide-0042")

    def test_build_manifest_order_and_shape(self):
        import extract_frames as E
        m = E.build_manifest("/x/meeting.mp4", ["10:20", "01:10:23"], image_format="png")
        self.assertEqual(m["image_format"], "png")
        self.assertEqual([f["slide"] for f in m["frames"]], ["slide-0001", "slide-0002"])
        self.assertEqual(m["frames"][0]["timestamp"], "10:20")
        self.assertEqual(m["frames"][0]["timestamp_s"], 620)
        self.assertEqual(m["frames"][0]["image"], "frames/slide-0001.png")
        self.assertEqual(m["frames"][1]["timestamp_s"], 4223)


class TestExtractFramesFfmpeg(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_extract_two_frames(self):
        with tempfile.TemporaryDirectory() as d:
            mp4 = os.path.join(d, "v.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=4",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                 "-shortest", mp4], check=True)
            manifest = os.path.join(d, "frames_manifest.json")
            p = subprocess.run(
                [sys.executable, os.path.join(F.SCRIPTS, "extract_frames.py"),
                 "--video", mp4, "--out-dir", d, "--manifest", manifest,
                 "0:01", "0:03"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(os.path.isfile(os.path.join(d, "frames", "slide-0001.png")))
            self.assertTrue(os.path.isfile(os.path.join(d, "frames", "slide-0002.png")))
            m = F.read_json(manifest)
            self.assertEqual(len(m["frames"]), 2)
            self.assertEqual(m["frames"][1]["timestamp_s"], 3)


class TestDescribeHelpers(unittest.TestCase):
    def _manifest(self):
        return {
            "video": "/abs/meeting.mp4",
            "image_format": "png",
            "frames": [
                {"slide": "slide-0001", "timestamp": "10:20", "timestamp_s": 620,
                 "image": "frames/slide-0001.png"},
                {"slide": "slide-0002", "timestamp": "15:10", "timestamp_s": 910,
                 "image": "frames/slide-0002.png"},
            ],
        }

    def test_build_details_shape(self):
        import describe_frames as D
        det = D.build_details(self._manifest(),
                              {"slide-0001": "Title slide about Q3 plan",
                               "slide-0002": "Architecture diagram with 3 services"},
                              vision_model="chandra-ocr-2", output_language="English")
        self.assertEqual(det["video"], "meeting.mp4")        # basename only
        self.assertEqual(det["vision_model"], "chandra-ocr-2")
        self.assertEqual(len(det["frames"]), 2)
        self.assertEqual(det["frames"][0]["slide"], "slide-0001")
        self.assertEqual(det["frames"][0]["image"], "frames/slide-0001.png")
        self.assertEqual(det["frames"][1]["text"], "Architecture diagram with 3 services")

    def test_missing_description_is_empty_string(self):
        import describe_frames as D
        det = D.build_details(self._manifest(), {"slide-0001": "x"},
                              vision_model="m", output_language="English")
        self.assertEqual(det["frames"][1]["text"], "")

    def test_render_digest_md(self):
        import describe_frames as D
        det = D.build_details(self._manifest(),
                              {"slide-0001": "A", "slide-0002": "B"}, "m", "English")
        md = D.render_digest_md(det)
        self.assertIn("## slide-0001 [10:20]", md)
        self.assertIn("A", md)
        self.assertIn("## slide-0002 [15:10]", md)

    def test_truncate(self):
        import describe_frames as D
        self.assertEqual(D.truncate("abc", 10), "abc")
        self.assertTrue(D.truncate("a" * 100, 10).endswith("…"))
        self.assertLessEqual(len(D.truncate("a" * 100, 10)), 11)


if __name__ == "__main__":
    unittest.main()
