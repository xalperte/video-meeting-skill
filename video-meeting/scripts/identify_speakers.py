#!/usr/bin/env python3
"""
Stage 4 — Map local diarization speakers (SPEAKER_00, …) to real people in the
global registry, using their voiceprints.

Runs with a python that has numpy (e.g. env.pyannote.python). No GPU needed.

Hybrid matching (the agreed behaviour):
  score >= high          -> known      (assign automatically; grow the voiceprint set)
  score <  low           -> new        (no match; register a new participant)
  low <= score < high    -> unconfirmed (DO NOT guess — leave pending for a human)

`match` makes registry changes only for confident matches and new speakers.
Unconfirmed speakers are written to `pending_confirmation`; the orchestrator/SKILL
asks the user, then calls `confirm` to apply their decisions.

Examples:
  identify_speakers.py match \
    --turns turns.json --embeddings voiceprints.npz --global-dir ~/.../global \
    --out mapping.json --high 0.75 --low 0.55 --strategy best --max-samples 8 \
    --add-sample-on-match --hint-names "Alice Ng" "Bob Li"

  identify_speakers.py confirm \
    --decisions decisions.json --embeddings voiceprints.npz \
    --global-dir ~/.../global --mapping mapping.json --out mapping.json
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry as R  # noqa: E402


def load_embeddings(npz_path):
    if not os.path.isfile(npz_path):
        sys.exit(f"embeddings not found: {npz_path}")
    data = np.load(npz_path)
    return {k: data[k].astype("float32").reshape(-1) for k in data.files}


def speaking_time(turns):
    secs = {}
    for t in turns:
        secs[t["speaker"]] = secs.get(t["speaker"], 0.0) + (t["end"] - t["start"])
    return secs


# --------------------------------------------------------------------------- #
def cmd_match(args):
    embeddings = load_embeddings(args.embeddings)
    turns = json.load(open(args.turns, encoding="utf-8")).get("turns", []) \
        if args.turns else []
    talk = speaking_time(turns)
    # Process the most-talkative speakers first (more reliable voiceprints).
    order = sorted(embeddings.keys(), key=lambda s: talk.get(s, 0.0), reverse=True)

    mapping = {}
    pending = []
    with R.locked(args.global_dir):
        reg = R.load_registry(args.global_dir)
        for spk in order:
            vec = embeddings[spk]
            pid, score = R.best_match(args.global_dir, reg, vec, args.strategy)
            score = round(float(score), 4)
            if pid is not None and score >= args.high:
                if args.add_sample_on_match:
                    R.add_sample(args.global_dir, reg, pid, vec, args.max_samples)
                R.touch_meeting(reg, pid)
                p = R._by_id(reg, pid)
                mapping[spk] = {"status": "known", "participant_id": pid,
                                "name": R.display_name(p), "confidence": score}
            elif pid is None or score < args.low:
                if args.auto_register_new:
                    new_pid = R.add_participant(args.global_dir, reg, vec)
                    p = R._by_id(reg, new_pid)
                    mapping[spk] = {"status": "new", "participant_id": new_pid,
                                    "name": R.display_name(p), "confidence": score}
                else:
                    mapping[spk] = {"status": "new_pending", "confidence": score}
                    pending.append(spk)
            else:  # gray zone
                p = R._by_id(reg, pid)
                mapping[spk] = {"status": "unconfirmed",
                                "candidate_id": pid,
                                "candidate_name": R.display_name(p),
                                "confidence": score}
                pending.append(spk)
        R.save_registry(args.global_dir, reg)

    out = {
        "audio": json.load(open(args.turns, encoding="utf-8")).get("audio")
        if args.turns else None,
        "thresholds": {"high": args.high, "low": args.low},
        "strategy": args.strategy,
        "mapping": mapping,
        "pending_confirmation": pending,
        "hint_names": args.hint_names or [],
        "registry_updated": True,
    }
    write_json(args.out, out)
    summarize(out)


def cmd_confirm(args):
    embeddings = load_embeddings(args.embeddings)
    decisions = json.load(open(args.decisions, encoding="utf-8"))
    mapping_doc = json.load(open(args.mapping, encoding="utf-8")) if args.mapping else {}
    mapping = mapping_doc.get("mapping", {})

    with R.locked(args.global_dir):
        reg = R.load_registry(args.global_dir)
        for spk, decision in decisions.items():
            action = decision.get("action")
            vec = embeddings.get(spk)
            if vec is None:
                sys.stderr.write(f"  warn: no embedding for {spk}; skipping\n")
                continue
            if action == "match":
                pid = decision["participant_id"]
                if R._by_id(reg, pid) is None:
                    sys.exit(f"confirm: unknown participant_id {pid} for {spk}")
                R.add_sample(args.global_dir, reg, pid, vec, args.max_samples)
                R.touch_meeting(reg, pid)
                mapping[spk] = {"status": "known", "participant_id": pid,
                                "name": R.display_name(R._by_id(reg, pid)),
                                "confidence": mapping.get(spk, {}).get("confidence", 0.0)}
            elif action == "new":
                meta = {k: decision.get(k, "") for k in
                        ("first_name", "last_name", "display_name",
                         "description", "email", "contact")}
                pid = R.add_participant(args.global_dir, reg, vec, meta)
                mapping[spk] = {"status": "new", "participant_id": pid,
                                "name": R.display_name(R._by_id(reg, pid)),
                                "confidence": mapping.get(spk, {}).get("confidence", 0.0)}
            elif action == "ignore":
                mapping[spk] = {"status": "ignored",
                                "confidence": mapping.get(spk, {}).get("confidence", 0.0)}
            else:
                sys.exit(f"confirm: unknown action '{action}' for {spk}")
        R.save_registry(args.global_dir, reg)

    mapping_doc["mapping"] = mapping
    mapping_doc["pending_confirmation"] = [
        s for s in mapping_doc.get("pending_confirmation", []) if s not in decisions
    ]
    write_json(args.out, mapping_doc)
    summarize(mapping_doc)


# --------------------------------------------------------------------------- #
def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def summarize(doc):
    m = doc.get("mapping", {})
    by = {}
    for v in m.values():
        by[v["status"]] = by.get(v["status"], 0) + 1
    parts = ", ".join(f"{k}={v}" for k, v in sorted(by.items()))
    sys.stderr.write(f"  speakers: {parts or 'none'}\n")
    if doc.get("pending_confirmation"):
        sys.stderr.write("  NEEDS CONFIRMATION: "
                         + ", ".join(doc["pending_confirmation"]) + "\n")


def build_parser():
    ap = argparse.ArgumentParser(description="Map diarization speakers to people.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("match", help="match speakers and update the registry")
    m.add_argument("--turns", default=None, help="turns.json (for speaking-time ordering)")
    m.add_argument("--embeddings", required=True, help="voiceprints .npz from diarize")
    m.add_argument("--global-dir", required=True)
    m.add_argument("--out", required=True, help="output mapping.json")
    m.add_argument("--high", type=float, default=0.75)
    m.add_argument("--low", type=float, default=0.55)
    m.add_argument("--strategy", default="best", choices=["best", "mean"])
    m.add_argument("--max-samples", type=int, default=8)
    m.add_argument("--add-sample-on-match", action="store_true")
    m.add_argument("--no-auto-register-new", dest="auto_register_new",
                   action="store_false",
                   help="leave sub-low speakers pending instead of registering")
    m.set_defaults(auto_register_new=True)
    m.add_argument("--hint-names", nargs="*", default=None,
                   help="expected attendee names (for the human's reference)")
    m.set_defaults(func=cmd_match)

    c = sub.add_parser("confirm", help="apply human decisions for pending speakers")
    c.add_argument("--decisions", required=True, help="decisions.json")
    c.add_argument("--embeddings", required=True)
    c.add_argument("--global-dir", required=True)
    c.add_argument("--mapping", required=True, help="existing mapping.json to update")
    c.add_argument("--out", required=True)
    c.add_argument("--max-samples", type=int, default=8)
    c.set_defaults(func=cmd_confirm)
    return ap


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
