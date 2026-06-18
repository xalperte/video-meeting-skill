"""Frame-step logic tests — stdlib only; ffmpeg/Ollama parts skip when absent."""
import os
import sys
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


if __name__ == "__main__":
    unittest.main()
