import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

try:
    import pptx  # noqa: F401
    import docx  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "python-pptx + python-docx required")
class BuildStarters(unittest.TestCase):
    def test_builds_three_templates(self):
        from build_starter_templates import build_all, STARTERS
        with tempfile.TemporaryDirectory() as d:
            build_all(d)
            base = os.path.join(d, "templates", "presentation")
            for key in STARTERS:
                folder = os.path.join(base, key)
                for f in ("slides.pptx", "report.docx", "template.yaml", "logo.png"):
                    self.assertTrue(os.path.isfile(os.path.join(folder, f)),
                                    f"{key}/{f} missing")


if __name__ == "__main__":
    unittest.main()
