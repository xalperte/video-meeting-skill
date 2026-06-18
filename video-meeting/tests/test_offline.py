"""Offline unit tests — pure logic, stdlib only. These run in any environment."""
import json
import os
import sys
import tempfile
import unittest

import fixtures as F

sys.path.insert(0, F.SCRIPTS)


class TestConfigGet(unittest.TestCase):
    def test_expand_and_get(self):
        import config_get as C
        os.environ["FOO"] = "/data/foo"
        os.environ.setdefault("USER_HOME", "/home/tester")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.yaml")
            with open(p, "w") as fh:
                fh.write('a:\n  home: "${USER_HOME}/x"\n  foo: "${FOO}/y"\n'
                         'list: [one, two]\nflag: true\n')
            cfg = C.load_config(p)
            self.assertTrue(C.get(cfg, "a.home").endswith("/x"))
            self.assertEqual(C.get(cfg, "a.foo"), "/data/foo/y")
            self.assertEqual(C.get(cfg, "list"), ["one", "two"])
            self.assertTrue(C.get(cfg, "flag"))
            self.assertIsNone(C.get(cfg, "missing.key"))
            self.assertEqual(C.get(cfg, "missing", "dflt"), "dflt")


class TestParseJsonLoose(unittest.TestCase):
    def test_variants(self):
        from ollama_client import parse_json_loose
        self.assertEqual(parse_json_loose('{"a":1}')["a"], 1)
        self.assertEqual(parse_json_loose('```json\n{"a":2}\n```')["a"], 2)
        self.assertEqual(parse_json_loose('Sure:\n{"a":3}\nthanks')["a"], 3)
        with self.assertRaises(Exception):
            parse_json_loose("no json here")


class TestGeneratePayload(unittest.TestCase):
    def test_think_disabled_and_fields(self):
        from ollama_client import build_payload
        p = build_payload("qwen3.5:9b", "hi", options={"num_ctx": 64}, fmt="json")
        # thinking models put output in `thinking` and leave `response` empty
        # unless think is explicitly disabled; non-thinking models ignore it.
        self.assertIs(p["think"], False)
        self.assertEqual(p["model"], "qwen3.5:9b")
        self.assertEqual(p["prompt"], "hi")
        self.assertIs(p["stream"], False)
        self.assertEqual(p["format"], "json")
        self.assertEqual(p["options"], {"num_ctx": 64})
        self.assertNotIn("system", p)

    def test_optional_fields_omitted(self):
        from ollama_client import build_payload
        p = build_payload("m", "p")
        self.assertNotIn("format", p)
        self.assertNotIn("options", p)
        p2 = build_payload("m", "p", system="s")
        self.assertEqual(p2["system"], "s")


class TestDiarizeUnwrap(unittest.TestCase):
    """pyannote.audio 3.x returns an Annotation; 4.x wraps it in DiarizeOutput."""

    def test_pyannote3_annotation_passes_through(self):
        from diarize import diarization_annotation
        annotation = object()  # 3.x: pipeline() returns the Annotation itself
        self.assertIs(diarization_annotation(annotation), annotation)

    def test_pyannote4_diarize_output_unwrapped(self):
        from diarize import diarization_annotation

        class FakeDiarizeOutput:  # 4.x: dataclass holding the Annotation
            def __init__(self, ann):
                self.speaker_diarization = ann
                self.exclusive_speaker_diarization = object()
                self.speaker_embeddings = None

        annotation = object()
        out = FakeDiarizeOutput(annotation)
        self.assertIs(diarization_annotation(out), annotation)


class TestTasks(unittest.TestCase):
    def test_normalize_coercion_and_filter(self):
        from extract_tasks import normalize
        raw = {"action_items": [
            {"title": "A", "type": "explicit", "priority": "URGENT",
             "source_ts": "00:01", "confidence": "0.9"},
            {"title": "B", "type": "ai_suggested", "priority": "low", "confidence": 0.4},
            {"type": "explicit"},  # no title -> dropped
        ], "decisions": ["d"], "open_questions": ["q"]}
        keep = normalize(raw, suggest_tasks=True)
        drop = normalize(raw, suggest_tasks=False)
        self.assertEqual(len(keep["action_items"]), 2)
        self.assertEqual(keep["action_items"][0]["priority"], "medium")  # coerced
        self.assertEqual(keep["action_items"][0]["source_ts"], ["00:01"])  # listified
        self.assertEqual(keep["action_items"][0]["confidence"], 0.9)       # floatified
        self.assertEqual(len(drop["action_items"]), 1)                     # suggested removed

    def test_merge_dedup(self):
        from extract_tasks import merge, normalize
        a = normalize({"action_items": [{"title": "X", "type": "explicit"}],
                       "decisions": ["same"]}, True)
        b = normalize({"action_items": [{"title": "x", "type": "explicit"},
                                        {"title": "Y", "type": "explicit"}],
                       "decisions": ["same"]}, True)
        m = merge([a, b])
        self.assertEqual(len(m["action_items"]), 2)   # X/x deduped, Y added
        self.assertEqual(len(m["decisions"]), 1)


class TestSummarizeHelpers(unittest.TestCase):
    def test_chunk_fill_lang_md(self):
        import summarize as S
        self.assertEqual(len(S.chunk_text("abc", 100)), 1)
        self.assertGreater(len(S.chunk_text("a\n" * 100, 20)), 1)
        self.assertEqual(S.fill("__X__ and __Y__", {"__X__": "1", "__Y__": "2"}),
                         "1 and 2")
        self.assertIn("transcript", S.language_phrase("auto"))
        self.assertEqual(S.language_phrase("Spanish"), "Spanish")
        md = S.render_markdown({"tldr": "hi", "sections":
                                [{"category": "C", "points": ["p1", "p2"]}]})
        self.assertIn("**TL;DR:** hi", md)
        self.assertIn("## C", md)
        self.assertIn("- p1", md)


class TestBuildRecord(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, F.SCRIPTS)
        import build_record as B
        self.B = B

    def test_segment_to_speaker_overlap(self):
        turns = F.sample_turns()["turns"]
        seg = {"start": 7.0, "end": 11.0}     # overlaps SPEAKER_01 most
        self.assertEqual(self.B.speaker_for_segment(seg, turns), "SPEAKER_01")

    def test_resolve_name_status(self):
        mapping = F.sample_mapping()["mapping"]
        self.assertEqual(self.B.resolve_name("SPEAKER_00", mapping), "Alice Ng")
        unconf = {"SPEAKER_X": {"status": "unconfirmed", "candidate_name": "Cy"}}
        self.assertEqual(self.B.resolve_name("SPEAKER_X", unconf), "Cy (?)")
        self.assertEqual(self.B.resolve_name("UNKNOWN", {}), "UNKNOWN")

    def test_transcript_and_participants(self):
        segs = F.sample_segments()["segments"]
        turns = F.sample_turns()["turns"]
        mapping = F.sample_mapping()["mapping"]
        md = self.B.build_transcript_md(segs, turns, mapping, "T")
        self.assertIn("[00:00:01] Alice Ng", md)
        self.assertIn("[00:00:07] Bob Li", md)
        parts = self.B.participants_from_mapping(mapping)
        self.assertEqual(len(parts), 2)


class TestRunWiring(unittest.TestCase):
    def test_helpers_and_config_keys(self):
        import run
        from config_get import load_config, get
        self.assertEqual(run.slugify("Sprint Grooming!! v2"), "sprint-grooming-v2")
        self.assertEqual(run.lang_name("es"), "Spanish")
        self.assertEqual(run.lang_name("xx"), "xx")
        cfg = load_config(os.path.join(F.ROOT, "config.example.yaml"))
        keys = ["paths.meetings_dir", "paths.work_dir", "paths.global_dir",
                "env.ffmpeg_bin", "env.whisper.python", "env.pyannote.python",
                "env.render.python", "env.cuda.visible_devices",
                "speaker_id.thresholds.high", "speaker_id.thresholds.low",
                "ollama.host", "ollama.num_ctx", "ollama.summary_model",
                "ollama.tasks_model", "ollama.vision_model",
                "ollama.summary_max_chunk_chars",
                "frames.image_format", "frames.jpeg_quality",
                "frames.describe_max_chars",
                "frames.frames_summary_max_chunk_chars",
                "rendering.slides.formats", "context_defaults"]
        missing = [k for k in keys if get(cfg, k) is None]
        self.assertEqual(missing, [], f"config.example.yaml missing: {missing}")


if __name__ == "__main__":
    unittest.main()
