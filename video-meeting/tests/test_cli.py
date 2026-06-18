"""CLI smoke tests: every script parses --help, and extract_audio works with a
real ffmpeg. Tool-dependent parts skip cleanly when the tool is absent."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import fixtures as F

ALL_SCRIPTS = [
    "extract_audio.py", "transcribe.py", "diarize.py", "build_record.py",
    "summarize.py", "extract_tasks.py", "render_email.py", "render_tasks_xlsx.py",
    "render_slides.py", "render_report.py", "identify_speakers.py", "registry.py",
    "preflight.py", "run.py", "config_get.py",
]


class TestHelp(unittest.TestCase):
    def test_scripts_parse_help(self):
        """--help must exit 0. A missing OPTIONAL dependency is an allowed skip;
        any other failure is a real error (syntax, bad argparse, etc.)."""
        failures, skipped = [], []
        for s in ALL_SCRIPTS:
            p = subprocess.run([sys.executable, os.path.join(F.SCRIPTS, s), "--help"],
                               capture_output=True, text=True)
            if p.returncode == 0:
                continue
            if "ModuleNotFoundError" in p.stderr or "ImportError" in p.stderr:
                skipped.append(s)
            else:
                failures.append((s, p.stderr.strip().splitlines()[-1:] or p.stderr))
        if skipped:
            sys.stderr.write(f"\n  (help skipped, missing deps: {', '.join(skipped)})\n")
        self.assertEqual(failures, [], f"scripts failed --help: {failures}")


class TestExtractAudio(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_extract(self):
        with tempfile.TemporaryDirectory() as d:
            mp4 = os.path.join(d, "t.mp4")
            wav = os.path.join(d, "t.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                 "-f", "lavfi", "-i", "color=c=black:s=128x128:d=2",
                 "-shortest", mp4], check=True)
            p = subprocess.run([sys.executable, os.path.join(F.SCRIPTS,
                                "extract_audio.py"), "--in", mp4, "--out", wav],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            meta = json.loads(p.stdout)
            self.assertEqual(meta["sample_rate"], 16000)
            self.assertEqual(meta["channels"], 1)
            self.assertGreater(meta["duration_s"], 1.0)
            self.assertTrue(os.path.isfile(wav))


if __name__ == "__main__":
    unittest.main()
