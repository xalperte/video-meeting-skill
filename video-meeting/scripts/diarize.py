#!/usr/bin/env python3
"""
Stage 3 — Speaker diarization + voiceprints with pyannote.audio.

Runs INSIDE pyannote-env (invoke via env.pyannote.python). Pure-argument CLI;
the orchestrator passes resolved config values. Two outputs:

  1. Speaker turns: who spoke when (SPEAKER_00, SPEAKER_01, …).
  2. A per-speaker voiceprint embedding (the matchable fingerprint), saved to an
     .npz so the next stage can match speakers against the global registry.

Whisper does NOT do this — diarization is a separate model. The labels here are
local to this recording; identify_speakers.py maps them to real people.

Usage (typical, from the orchestrator):
  CUDA_VISIBLE_DEVICES=0 $PYANNOTE_PY diarize.py \
    --in audio.wav --out turns.json --embeddings-out voiceprints.npz \
    --diarization-model pyannote/speaker-diarization-3.1 \
    --embedding-model pyannote/embedding \
    --model-dir ~/models/pyannote --hf-token-file ~/.config/video-meeting/hf_token \
    --device cuda --min-turn-seconds 3.0

Output (--out, JSON):
  {
    "audio": "...", "turns": [{"start": 0.0, "end": 4.2, "speaker": "SPEAKER_00"}],
    "speakers": ["SPEAKER_00", ...],
    "embedding_file": "voiceprints.npz", "embedding_dim": 512
  }
"""
import argparse
import json
import os
import sys


def diarization_annotation(result):
    """Unwrap the diarization pipeline output to a pyannote.core.Annotation.

    pyannote.audio 3.x returns the Annotation directly; 4.x wraps it in a
    DiarizeOutput dataclass whose .speaker_diarization field holds it.
    """
    return getattr(result, "speaker_diarization", result)


def read_token(path):
    if not path:
        return None
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        sys.exit(f"HF token missing/empty: {path} (see references/install.md)")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().strip()


def main():
    ap = argparse.ArgumentParser(description="Diarize a WAV and extract voiceprints.")
    ap.add_argument("--in", dest="inp", required=True, help="input 16 kHz mono WAV")
    ap.add_argument("--out", dest="out", required=True, help="output turns JSON")
    ap.add_argument("--embeddings-out", required=True, help="output .npz of voiceprints")
    ap.add_argument("--diarization-model", default="pyannote/speaker-diarization-3.1")
    ap.add_argument("--embedding-model", default="pyannote/embedding")
    ap.add_argument("--model-dir", default=None, help="cache_dir for the models")
    ap.add_argument("--hf-token-file", default=None, help="file holding the HF token")
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--min-turn-seconds", type=float, default=3.0,
                    help="ignore turns shorter than this when building voiceprints")
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--min-speakers", type=int, default=None)
    ap.add_argument("--max-speakers", type=int, default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.inp):
        sys.exit(f"input WAV not found: {args.inp}")

    try:
        import numpy as np
        import torch
        from pyannote.audio import Inference, Model, Pipeline
        from pyannote.core import Segment
    except ImportError as exc:
        sys.exit(f"pyannote/torch not importable — is this pyannote-env? ({exc})")

    token = read_token(args.hf_token_file)
    device = torch.device(args.device)

    # --- Diarization -------------------------------------------------------- #
    pipeline = Pipeline.from_pretrained(
        args.diarization_model, token=token, cache_dir=args.model_dir,
    )
    if pipeline is None:
        sys.exit("Pipeline.from_pretrained returned None — license accepted + token valid?")
    pipeline.to(device)

    diar_kwargs = {}
    if args.num_speakers is not None:
        diar_kwargs["num_speakers"] = args.num_speakers
    else:
        if args.min_speakers is not None:
            diar_kwargs["min_speakers"] = args.min_speakers
        if args.max_speakers is not None:
            diar_kwargs["max_speakers"] = args.max_speakers

    sys.stderr.write("  diarizing…\n")
    diarization = diarization_annotation(pipeline(args.inp, **diar_kwargs))

    turns = []
    per_speaker = {}  # speaker -> list of (start, end, duration)
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append({"start": round(turn.start, 3),
                      "end": round(turn.end, 3),
                      "speaker": speaker})
        per_speaker.setdefault(speaker, []).append((turn.start, turn.end, turn.duration))

    speakers = sorted(per_speaker.keys())
    if not speakers:
        sys.exit("no speakers detected — check the audio")

    # --- Voiceprints -------------------------------------------------------- #
    emb_model = Model.from_pretrained(
        args.embedding_model, token=token, cache_dir=args.model_dir,
    )
    inference = Inference(emb_model, window="whole")
    inference.to(device)

    embeddings = {}
    dim = None
    for speaker in speakers:
        segs = per_speaker[speaker]
        usable = [s for s in segs if s[2] >= args.min_turn_seconds]
        if not usable:                       # fall back to the longest turn
            usable = [max(segs, key=lambda s: s[2])]
        vecs, weights = [], []
        for start, end, dur in usable:
            try:
                vec = inference.crop(args.inp, Segment(start, end))
            except Exception as exc:         # edge segments can fail; skip them
                sys.stderr.write(f"    warn: embedding failed for {speaker} "
                                 f"[{start:.1f}-{end:.1f}]: {exc}\n")
                continue
            vec = np.asarray(vec, dtype="float32").reshape(-1)
            vecs.append(vec)
            weights.append(float(dur))
        if not vecs:
            sys.stderr.write(f"    warn: no embedding for {speaker}; skipping\n")
            continue
        mean = np.average(np.vstack(vecs), axis=0, weights=weights).astype("float32")
        embeddings[speaker] = mean
        dim = mean.shape[0]
        sys.stderr.write(f"  voiceprint: {speaker} from {len(vecs)} segment(s)\n")

    if not embeddings:
        sys.exit("failed to compute any voiceprints")

    os.makedirs(os.path.dirname(os.path.abspath(args.embeddings_out)) or ".", exist_ok=True)
    np.savez(args.embeddings_out, **embeddings)

    result = {
        "audio": os.path.abspath(args.inp),
        "turns": turns,
        "speakers": list(embeddings.keys()),
        "embedding_file": os.path.abspath(args.embeddings_out),
        "embedding_dim": dim,
        "min_turn_seconds": args.min_turn_seconds,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    sys.stderr.write(
        f"  done: {len(turns)} turns, {len(embeddings)} speaker(s), "
        f"dim={dim} -> {args.out}\n"
    )


if __name__ == "__main__":
    main()
