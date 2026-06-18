import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from templates import (  # noqa: E402
    DEFAULT_XLSX,
    discover_templates,
    find_layout_by_name,
    resolve_template,
    slides_layouts,
    xlsx_style,
)


class _Layout:
    def __init__(self, name):
        self.name = name


class Discover(unittest.TestCase):
    def test_lists_dirs_sorted_ignores_files(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "client"))
            os.mkdir(os.path.join(d, "executive"))
            open(os.path.join(d, "notes.txt"), "w").close()
            self.assertEqual(discover_templates(d), ["client", "executive"])

    def test_missing_root_is_empty(self):
        self.assertEqual(discover_templates("/no/such/dir/xyz"), [])


class FindLayout(unittest.TestCase):
    def setUp(self):
        self.layouts = [_Layout("Title Slide"), _Layout("Title and Content"),
                        _Layout("Blank")]

    def test_match_by_name_case_insensitive(self):
        lay, fell = find_layout_by_name(self.layouts, "title and content", 0)
        self.assertEqual(lay.name, "Title and Content")
        self.assertFalse(fell)

    def test_fallback_to_index_when_no_name_match(self):
        lay, fell = find_layout_by_name(self.layouts, "Nonexistent", 2)
        self.assertEqual(lay.name, "Blank")
        self.assertTrue(fell)

    def test_fallback_to_first_when_index_out_of_range(self):
        lay, fell = find_layout_by_name(self.layouts, "Nonexistent", 99)
        self.assertEqual(lay.name, "Title Slide")
        self.assertTrue(fell)


class Style(unittest.TestCase):
    def test_xlsx_defaults_when_absent(self):
        self.assertEqual(xlsx_style({}), DEFAULT_XLSX)

    def test_xlsx_override_merges(self):
        merged = xlsx_style({"xlsx": {"header_fill": "000000"}})
        self.assertEqual(merged["header_fill"], "000000")
        self.assertEqual(merged["explicit_fill"], DEFAULT_XLSX["explicit_fill"])

    def test_slides_defaults(self):
        self.assertEqual(slides_layouts({})["title_layout"], "Title Slide")


class Resolve(unittest.TestCase):
    def test_unknown_raises_with_available(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "internal"))
            with self.assertRaises(SystemExit) as ctx:
                resolve_template(d, "nope")
            self.assertIn("internal", str(ctx.exception))

    def test_known_returns_folder_and_data(self):
        with tempfile.TemporaryDirectory() as d:
            folder = os.path.join(d, "internal")
            os.mkdir(folder)
            path, data = resolve_template(d, "internal")
            self.assertEqual(path, folder)
            self.assertIsInstance(data, dict)


if __name__ == "__main__":
    unittest.main()
