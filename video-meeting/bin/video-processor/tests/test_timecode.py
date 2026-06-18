import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from video_processor.timecode import parse_timecode, format_timecode


class ParseTimecode(unittest.TestCase):
    def test_bare_seconds(self):
        self.assertEqual(parse_timecode("70"), 70.0)

    def test_mm_ss(self):
        self.assertEqual(parse_timecode("01:10"), 70.0)

    def test_hh_mm_ss(self):
        self.assertEqual(parse_timecode("01:00:00"), 3600.0)

    def test_sec_prefix(self):
        self.assertEqual(parse_timecode("sec 70"), 70.0)

    def test_fractional(self):
        self.assertEqual(parse_timecode("130.5"), 130.5)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            parse_timecode("-5")

    def test_too_many_colons(self):
        with self.assertRaises(ValueError):
            parse_timecode("1:2:3:4")

    def test_non_numeric(self):
        with self.assertRaises(ValueError):
            parse_timecode("abc")

    def test_empty(self):
        with self.assertRaises(ValueError):
            parse_timecode("   ")


class FormatTimecode(unittest.TestCase):
    def test_mm_ss(self):
        self.assertEqual(format_timecode(70), "01:10")

    def test_hh_mm_ss(self):
        self.assertEqual(format_timecode(3661), "01:01:01")

    def test_drops_fraction(self):
        self.assertEqual(format_timecode(130.5), "02:10")

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            format_timecode(-1)


if __name__ == "__main__":
    unittest.main()
