"""Non-destructive config migration tests — stdlib + PyYAML (skip if absent)."""
import os
import sys
import tempfile
import unittest

import fixtures as F

sys.path.insert(0, F.SCRIPTS)

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


@unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
class TestMigrateConfig(unittest.TestCase):
    def _write(self, d, name, text):
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def test_missing_keys_detected(self):
        import migrate_config as M
        example = {"ollama": {"host": "h", "vision_model": "v"},
                   "frames": {"image_format": "png"}}
        user = {"ollama": {"host": "h"}}
        self.assertEqual(sorted(M.missing_keys(example, user)),
                         ["frames.image_format", "ollama.vision_model"])

    def test_build_missing_tree(self):
        import migrate_config as M
        example = {"ollama": {"host": "h", "vision_model": "v"},
                   "frames": {"image_format": "png"}}
        user = {"ollama": {"host": "h"}}
        tree = M.build_missing_tree(example, user)
        self.assertEqual(tree, {"ollama": {"vision_model": "v"},
                                "frames": {"image_format": "png"}})

    def test_apply_preserves_customizations_and_adds_keys(self):
        import migrate_config as M
        from config_get import load_config
        with tempfile.TemporaryDirectory() as d:
            example = self._write(d, "config.example.yaml",
                'ollama:\n  host: "http://x"\n  summary_model: "gemma4:12b"\n'
                '  vision_model: "qwen3-vl:8b"\n'
                'frames:\n  image_format: "png"\n  describe_max_chars: 4000\n')
            # user customized summary_model AND has a key not in example
            cfg = self._write(d, "config.yaml",
                'ollama:\n  host: "http://x"\n  summary_model: "myllm:70b"\n'
                '  max_chunk_chars: 100000\n')
            changed = M.apply(cfg, example)
            self.assertTrue(changed)
            self.assertTrue(os.path.isfile(cfg + ".bak"))  # backup made
            loaded = load_config(cfg)
            # customizations preserved
            self.assertEqual(loaded["ollama"]["summary_model"], "myllm:70b")
            self.assertEqual(loaded["ollama"]["max_chunk_chars"], 100000)
            # siblings under ollama NOT wiped, new key inserted
            self.assertEqual(loaded["ollama"]["host"], "http://x")
            self.assertEqual(loaded["ollama"]["vision_model"], "qwen3-vl:8b")
            # new top-level block appended
            self.assertEqual(loaded["frames"]["image_format"], "png")
            self.assertEqual(loaded["frames"]["describe_max_chars"], 4000)

    def test_idempotent(self):
        import migrate_config as M
        with tempfile.TemporaryDirectory() as d:
            example = self._write(d, "config.example.yaml",
                'ollama:\n  host: "h"\n  vision_model: "v"\n')
            cfg = self._write(d, "config.yaml", 'ollama:\n  host: "h"\n')
            self.assertTrue(M.apply(cfg, example))     # first run adds vision_model
            self.assertFalse(M.apply(cfg, example))    # second run: nothing to do


if __name__ == "__main__":
    unittest.main()
