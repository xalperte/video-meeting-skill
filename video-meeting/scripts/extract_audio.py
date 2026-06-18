#!/usr/bin/env python3
"""
Stage 1 — Extract a normalized 16 kHz mono WAV from a video/audio file.

Pure stdlib + ffmpeg, so it runs with the system python3 (no venv needed).
Whisper and pyannote both expect 16 kHz mono PCM, so we normalize once here and
every downstream stage reuses the same WAV.

Usage:
  extract_audio.py --in meeting.mp4 --out audio.wav [--ffmpeg /usr/bin/ffmpeg]

Output (stdout, JSON):
  {"audio": "...", "duration_s": 1234.5, "sample_rate": 16000, "channels": 1}
"""
import argparse
import json
import os
import subprocess
import sys
import wave


def main():
    ap = argparse.ArgumentParser(description="Extract 16 kHz mono WAV via ffmpeg.")
    ap.add_argument("--in", dest="inp", required=True, help="input video/audio file")
    ap.add_argument("--out", dest="out", required=True, help="output .wav path")
    ap.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg binary (abs path ok)")
    ap.add_argument("--sample-rate", type=int, default=16000)
    ap.add_argument("--channels", type=int, default=1)
    args = ap.parse_args()

    if not os.path.isfile(args.inp):
        sys.exit(f"input not found: {args.inp}")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    cmd = [
        args.ffmpeg, "-y", "-loglevel", "error",
        "-i", args.inp,
        "-vn",                          # drop video
        "-ac", str(args.channels),      # mono
        "-ar", str(args.sample_rate),   # 16 kHz
        "-c:a", "pcm_s16le",            # 16-bit PCM
        "-f", "wav",
        args.out,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.exit(
            f"ffmpeg failed (code {proc.returncode}). "
            "Does the file contain an audio stream?"
        )

    # Read duration straight from the WAV header — no ffprobe needed.
    try:
        with wave.open(args.out, "rb") as w:
            frames, rate = w.getnframes(), w.getframerate()
            duration = round(frames / float(rate), 3) if rate else None
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"wrote {args.out} but could not read it back: {exc}")

    json.dump(
        {
            "audio": os.path.abspath(args.out),
            "duration_s": duration,
            "sample_rate": args.sample_rate,
            "channels": args.channels,
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
