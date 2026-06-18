#!/usr/bin/env python3
"""
Stage 5/8 — Assemble the named transcript and the meeting_record.json.

Stdlib only. This is the join point of the pipeline: it aligns Whisper segments
(text + timestamps) with pyannote turns (who spoke when) and the identify mapping
(local speaker -> real person), then bundles everything the renderers need into a
single source of truth.

Inputs:
  --segments  segments.json   (transcribe)
  --turns     turns.json      (diarize)        [optional but recommended]
  --mapping   mapping.json    (identify)       [optional]
  --summary   summary.json    (summarize)      [optional]
  --tasks     tasks.json      (extract_tasks)  [optional]

Outputs:
  --transcript-out  transcript.md       (named, timestamped)
  --record-out      meeting_record.json  (consumed by xlsx/pptx/pdf/email)
"""
import argparse
import json
import os
import sys


def load_json(path, default=None):
    if not path or not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def hhmmss(seconds):
    if seconds is None:
        return "00:00:00"
    s = int(round(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def overlap(a_start, a_end, b_start, b_end):
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def speaker_for_segment(seg, turns):
    """Pick the diarization speaker overlapping a segment the most; fall back to
    the nearest turn by midpoint."""
    if not turns:
        return None
    best_spk, best_ov = None, 0.0
    for t in turns:
        ov = overlap(seg["start"], seg["end"], t["start"], t["end"])
        if ov > best_ov:
            best_spk, best_ov = t["speaker"], ov
    if best_spk is not None:
        return best_spk
    mid = 0.5 * (seg["start"] + seg["end"])
    return min(turns, key=lambda t: abs(0.5 * (t["start"] + t["end"]) - mid))["speaker"]


def resolve_name(spk, mapping):
    """Human-facing label for a local speaker, honoring match status."""
    info = mapping.get(spk)
    if not info:
        return spk
    status = info.get("status")
    if status in ("known", "new"):
        return info.get("name") or spk
    if status == "unconfirmed":
        cand = info.get("candidate_name")
        return f"{cand} (?)" if cand else f"{spk} (?)"
    return spk  # ignored / unknown


def build_transcript_md(segments, turns, mapping, title):
    lines = [f"# Transcript — {title}", ""]
    blocks = []  # (timestamp, name, text) merging consecutive same-speaker segments
    last_name = None
    for seg in segments:
        spk = speaker_for_segment(seg, turns)
        name = resolve_name(spk, mapping) if spk is not None else "Speaker"
        text = seg["text"].strip()
        if not text:
            continue
        if name == last_name and blocks:
            blocks[-1][2].append(text)
        else:
            blocks.append([hhmmss(seg["start"]), name, [text]])
            last_name = name
    for ts, name, texts in blocks:
        lines.append(f"**[{ts}] {name}:** {' '.join(texts)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def participants_from_mapping(mapping):
    seen, out = set(), []
    for info in mapping.values():
        pid = info.get("participant_id")
        key = pid or info.get("candidate_id") or json.dumps(info, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "participant_id": pid,
            "name": info.get("name") or info.get("candidate_name") or "",
            "match_confidence": info.get("confidence", 0.0),
            "status": info.get("status", "unknown"),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="Assemble transcript + meeting record.")
    ap.add_argument("--segments", required=True)
    ap.add_argument("--turns", default=None)
    ap.add_argument("--mapping", default=None)
    ap.add_argument("--summary", default=None)
    ap.add_argument("--tasks", default=None)
    ap.add_argument("--transcript-out", required=True)
    ap.add_argument("--record-out", required=True)
    ap.add_argument("--title", default="Meeting")
    ap.add_argument("--date", default="")
    ap.add_argument("--meeting-type", default="other")
    ap.add_argument("--language-out", default="auto")
    ap.add_argument("--duration", type=float, default=None)
    args = ap.parse_args()

    seg_doc = load_json(args.segments)
    if not seg_doc:
        sys.exit(f"segments not found/empty: {args.segments}")
    segments = seg_doc.get("segments", [])
    turns = (load_json(args.turns, {}) or {}).get("turns", [])
    mapping = (load_json(args.mapping, {}) or {}).get("mapping", {})
    summary = load_json(args.summary, {}) or {}
    tasks = load_json(args.tasks, {}) or {}

    # --- transcript.md ------------------------------------------------------ #
    transcript_md = build_transcript_md(segments, turns, mapping, args.title)
    os.makedirs(os.path.dirname(os.path.abspath(args.transcript_out)) or ".", exist_ok=True)
    with open(args.transcript_out, "w", encoding="utf-8") as fh:
        fh.write(transcript_md)

    # --- duration / language ------------------------------------------------ #
    duration = args.duration
    if duration is None:
        duration = seg_doc.get("duration")
    if duration is None and segments:
        duration = segments[-1].get("end")
    language_out = args.language_out
    if language_out == "auto":
        language_out = seg_doc.get("language", "auto")

    record = {
        "meeting": {
            "title": args.title,
            "date": args.date,
            "type": args.meeting_type,
            "language_out": language_out,
            "detected_language": seg_doc.get("language"),
            "duration_s": round(float(duration), 3) if duration else None,
        },
        "participants": participants_from_mapping(mapping),
        "summary": {
            "tldr": summary.get("tldr", ""),
            "sections": summary.get("sections", []),
        },
        "action_items": tasks.get("action_items", []),
        "decisions": tasks.get("decisions", []),
        "open_questions": tasks.get("open_questions", []),
        "transcript_ref": os.path.basename(args.transcript_out),
    }
    with open(args.record_out, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)

    n_exp = sum(1 for t in record["action_items"] if t.get("type") == "explicit")
    n_sug = sum(1 for t in record["action_items"] if t.get("type") == "ai_suggested")
    sys.stderr.write(
        f"  record: {len(record['participants'])} participants, "
        f"{n_exp} explicit + {n_sug} suggested tasks, "
        f"language={language_out} -> {args.record_out}\n"
    )


if __name__ == "__main__":
    main()
