"""Registry + speaker-identification tests. Requires numpy; skipped otherwise."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import fixtures as F

sys.path.insert(0, F.SCRIPTS)

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


def unit(v):
    v = np.asarray(v, dtype="float32")
    n = np.linalg.norm(v)
    return v / n if n else v


def orth(to):
    r = np.random.randn(*to.shape).astype("float32")
    r = r - (r @ to) / (to @ to) * to
    return unit(r)


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class TestRegistry(unittest.TestCase):
    def test_add_match_and_cap(self):
        import registry as R
        np.random.seed(1)
        with tempfile.TemporaryDirectory() as g:
            reg = R.load_registry(g)
            a = unit(np.random.randn(16))
            pid = R.add_participant(g, reg, a)
            R.save_registry(g, reg)
            self.assertEqual(pid, "p_0001")

            # near-identical query matches; orthogonal does not
            best, score = R.best_match(g, reg, unit(a + 0.01 * np.random.randn(16)))
            self.assertEqual(best, "p_0001")
            self.assertGreater(score, 0.9)
            _, low = R.best_match(g, reg, orth(a))
            self.assertLess(low, 0.5)

            # sample cap prunes oldest
            for _ in range(10):
                R.add_sample(g, reg, pid, unit(np.random.randn(16)), max_samples=3)
            self.assertEqual(len(R._by_id(reg, pid)["voiceprints"]), 3)

    def test_csv_export(self):
        import registry as R
        with tempfile.TemporaryDirectory() as g:
            reg = R.load_registry(g)
            R.add_participant(g, reg, unit(np.random.randn(16)),
                              {"first_name": "Ann", "last_name": "Lee"})
            R.save_registry(g, reg)
            self.assertTrue(os.path.isfile(os.path.join(g, "participants.csv")))


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class TestIdentifyFlow(unittest.TestCase):
    def _run(self, args):
        p = subprocess.run([sys.executable, os.path.join(F.SCRIPTS,
                            "identify_speakers.py")] + args,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def test_match_then_confirm(self):
        np.random.seed(2)
        with tempfile.TemporaryDirectory() as g:
            A, B = unit(np.random.randn(16)), unit(np.random.randn(16))
            F.make_embeddings(os.path.join(g, "r1.npz"),
                              {"SPEAKER_00": A, "SPEAKER_01": B})
            self._run(["match", "--embeddings", os.path.join(g, "r1.npz"),
                       "--global-dir", g, "--out", os.path.join(g, "m1.json"),
                       "--high", "0.75", "--low", "0.55"])
            m1 = F.read_json(os.path.join(g, "m1.json"))
            self.assertEqual({v["status"] for v in m1["mapping"].values()}, {"new"})

            near = unit(A + 0.01 * np.random.randn(16))
            a = 0.65
            gray = unit(a * B + np.sqrt(1 - a * a) * orth(B))
            C = unit(np.random.randn(16))
            F.make_embeddings(os.path.join(g, "r2.npz"),
                              {"SPEAKER_00": near, "SPEAKER_01": gray, "SPEAKER_02": C})
            self._run(["match", "--embeddings", os.path.join(g, "r2.npz"),
                       "--global-dir", g, "--out", os.path.join(g, "m2.json"),
                       "--high", "0.75", "--low", "0.55", "--add-sample-on-match"])
            m2 = F.read_json(os.path.join(g, "m2.json"))
            self.assertEqual(m2["mapping"]["SPEAKER_00"]["status"], "known")
            self.assertEqual(m2["mapping"]["SPEAKER_01"]["status"], "unconfirmed")
            self.assertEqual(m2["mapping"]["SPEAKER_02"]["status"], "new")
            self.assertEqual(m2["pending_confirmation"], ["SPEAKER_01"])

            cand = m2["mapping"]["SPEAKER_01"]["candidate_id"]
            F.write_json(os.path.join(g, "dec.json"),
                         {"SPEAKER_01": {"action": "match", "participant_id": cand}})
            self._run(["confirm", "--decisions", os.path.join(g, "dec.json"),
                       "--embeddings", os.path.join(g, "r2.npz"), "--global-dir", g,
                       "--mapping", os.path.join(g, "m2.json"),
                       "--out", os.path.join(g, "m3.json")])
            m3 = F.read_json(os.path.join(g, "m3.json"))
            self.assertEqual(m3["mapping"]["SPEAKER_01"]["status"], "known")
            self.assertEqual(m3["pending_confirmation"], [])


if __name__ == "__main__":
    unittest.main()
