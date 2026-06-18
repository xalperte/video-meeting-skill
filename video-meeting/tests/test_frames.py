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


if __name__ == "__main__":
    unittest.main()
