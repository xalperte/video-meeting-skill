"""Shared test fixtures — synthetic pipeline data. Stdlib-only at import time
(numpy is imported lazily, only by the embedding helper)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")


def sample_segments():
    return {
        "language": "en", "language_probability": 0.99, "duration": 18.0,
        "segments": [
            {"id": 0, "start": 1.0, "end": 6.0,
             "text": "We agreed to ship the export feature next sprint."},
            {"id": 1, "start": 7.0, "end": 11.0,
             "text": "I will write the CSV exporter by Friday."},
            {"id": 2, "start": 12.0, "end": 17.0,
             "text": "We still need to decide on the file size limit."},
        ],
    }


def sample_turns():
    return {"turns": [
        {"start": 0.5, "end": 6.5, "speaker": "SPEAKER_00"},
        {"start": 6.8, "end": 11.5, "speaker": "SPEAKER_01"},
        {"start": 11.8, "end": 17.5, "speaker": "SPEAKER_00"},
    ]}


def sample_mapping():
    return {"mapping": {
        "SPEAKER_00": {"status": "known", "participant_id": "p_0001",
                       "name": "Alice Ng", "confidence": 0.83},
        "SPEAKER_01": {"status": "new", "participant_id": "p_0002",
                       "name": "Bob Li", "confidence": 0.2},
    }}


def sample_record():
    return {
        "meeting": {"title": "Export feature sync", "date": "2026-06-08",
                    "type": "feature", "language_out": "en", "duration_s": 1830.0},
        "participants": [
            {"participant_id": "p_0001", "name": "Alice Ng",
             "match_confidence": 0.83, "status": "known"},
            {"participant_id": "p_0002", "name": "Bob Li",
             "match_confidence": 0.2, "status": "new"},
        ],
        "summary": {
            "tldr": "The team agreed to build a CSV export feature next sprint.",
            "sections": [
                {"category": "Decisions", "points": ["Ship export feature next sprint",
                                                      "Use streaming for large files"]},
                {"category": "Open questions", "points": ["Max file size undecided"]},
            ],
        },
        "action_items": [
            {"title": "Write the CSV exporter", "type": "explicit",
             "assignee": "Bob Li", "priority": "high",
             "source_ts": ["00:00:07"], "confidence": 0.9},
            {"title": "Add unit tests for exporter", "type": "ai_suggested",
             "assignee": "", "priority": "medium", "source_ts": [], "confidence": 0.4},
        ],
        "decisions": ["Ship export feature next sprint"],
        "open_questions": ["What is the max file size?"],
        "transcript_ref": "transcript.md",
    }


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


def read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def write_inputs(d):
    """Write the standard set of intermediate inputs into directory d."""
    return {
        "segments": write_json(os.path.join(d, "segments.json"), sample_segments()),
        "turns": write_json(os.path.join(d, "turns.json"), sample_turns()),
        "mapping": write_json(os.path.join(d, "mapping.json"), sample_mapping()),
        "record": write_json(os.path.join(d, "record.json"), sample_record()),
    }


def make_embeddings(path, vectors):
    """Save a dict of {speaker: vector} to an .npz (lazy numpy import)."""
    import numpy as np
    np.savez(path, **{k: np.asarray(v, dtype="float32") for k, v in vectors.items()})
