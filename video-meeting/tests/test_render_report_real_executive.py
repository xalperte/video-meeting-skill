import os
import sys
import json
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

try:
    from docx import Document
    HAVE_DOCX = True
except ImportError:
    HAVE_DOCX = False

EXEC_DIR = os.path.join(HERE, "..", "templates", "presentation", "executive")


def _record():
    return {
        "meeting": {"title": "Q2 Review", "date": "2026-06-18", "type": "catchup"},
        "summary": {"tldr": "Solid quarter.", "sections": [
            {"category": "Highlights", "points": ["Shipped", "Closed 12 issues"]}]},
        "participants": [{"name": "Xavi", "status": "known", "match_confidence": 0.9}],
        "action_items": [{"title": "Send recap", "type": "explicit"}],
        "decisions": ["Adopt template system"],
        "open_questions": ["Budget for Q3?"],
    }


@unittest.skipUnless(HAVE_DOCX, "python-docx required")
@unittest.skipUnless(os.path.isdir(EXEC_DIR) and
                     os.path.isfile(os.path.join(EXEC_DIR, "report.docx")),
                     "executive template not present")
class RealExecutiveReport(unittest.TestCase):
    def test_renders_against_real_executive_base(self):
        from render_report import render
        with tempfile.TemporaryDirectory() as d:
            rec = os.path.join(d, "rec.json")
            with open(rec, "w") as fh:
                json.dump(_record(), fh)
            out_pdf = os.path.join(d, "report.pdf")
            render(rec, out_pdf, "soffice", True, EXEC_DIR)  # must not raise
            docx = os.path.splitext(out_pdf)[0] + ".docx"
            self.assertTrue(os.path.isfile(docx))
            text = "\n".join(p.text for p in Document(docx).paragraphs)
            self.assertIn("Q2 Review", text)
            self.assertIn("Highlights", text)   # a heading rendered (styled or fallback)


if __name__ == "__main__":
    unittest.main()
