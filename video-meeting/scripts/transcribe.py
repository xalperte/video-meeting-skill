#!/usr/bin/env python3
"""
Stage 2 — Transcribe a WAV with faster-whisper.

Runs INSIDE whisper-env (invoke via the interpreter at env.whisper.python). It is
a pure-argument CLI: the orchestrator resolves config values and passes them in,
so this script has no PyYAML/config dependency.

Whisper auto-detects the spoken language (one dominant language per file via
`info.language`). True per-segment language is not native to Whisper; downstream
output language is chosen from this detected language (see SKILL.md).

Usage (typical, from the orchestrator):
  CUDA_VISIBLE_DEVICES=0 $WHISPER_PY transcribe.py \
    --in audio.wav --out segments.json \
    --model large-v3 --model-dir ~/models/whisper \
    --device cuda --compute-type float16 --beam-size 5 --vad-filter

Output (--out, JSON):
  {
    "language": "es", "language_probability": 0.99, "duration": 1234.5,
    "segments": [{"id": 0, "start": 0.0, "end": 4.2, "text": "..."}]
  }
"""
import argparse
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser(description="Transcribe a WAV with faster-whisper.")
    ap.add_argument("--in", dest="inp", required=True, help="input 16 kHz mono WAV")
    ap.add_argument("--out", dest="out", required=True, help="output segments JSON")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--model-dir", default=None, help="download_root for weights")
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu", "auto"])
    ap.add_argument("--compute-type", default="float16",
                    help="float16 | int8_float16 | int8 | float32")
    ap.add_argument("--beam-size", type=int, default=5)
    ap.add_argument("--vad-filter", action="store_true",
                    help="drop silence with the built-in VAD")
    ap.add_argument("--language", default=None,
                    help="force a language code; omit to auto-detect")
    args = ap.parse_args()

    if not os.path.isfile(args.inp):
        sys.exit(f"input WAV not found: {args.inp}")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster_whisper not importable — is this whisper-env? (see install.md)")

    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=args.compute_type,
        download_root=args.model_dir,
    )

    segments_iter, info = model.transcribe(
        args.inp,
        beam_size=args.beam_size,
        vad_filter=args.vad_filter,
        language=args.language,
    )

    # faster-whisper yields segments lazily; materialize and report progress.
    segments = []
    total = getattr(info, "duration", None)
    for seg in segments_iter:
        segments.append({
            "id": len(segments),
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
        })
        if total:
            pct = min(100, int(100 * seg.end / total))
            sys.stderr.write(f"\r  transcribing… {pct:3d}%  ({len(segments)} segments)")
            sys.stderr.flush()
    sys.stderr.write("\n")

    result = {
        "language": info.language,
        "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
        "duration": round(float(info.duration), 3) if getattr(info, "duration", None) else None,
        "segments": segments,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    sys.stderr.write(
        f"  done: {len(segments)} segments, language={info.language} "
        f"({result['language_probability']}) -> {args.out}\n"
    )


if __name__ == "__main__":
    main()
