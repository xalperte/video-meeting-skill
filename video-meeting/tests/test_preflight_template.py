import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import preflight  # noqa: E402


class TemplateCheck(unittest.TestCase):
    def test_ok_when_template_exists(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "templates", "presentation", "internal")
            os.makedirs(folder)
            open(os.path.join(folder, "slides.pptx"), "w").close()
            open(os.path.join(folder, "report.docx"), "w").close()
            self.assertTrue(preflight.check_template(root, "internal"))

    def test_fail_when_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "templates", "presentation", "internal"))
            self.assertFalse(preflight.check_template(root, "missing"))


if __name__ == "__main__":
    unittest.main()
