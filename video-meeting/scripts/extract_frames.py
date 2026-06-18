#!/usr/bin/env python3
"""
Optional stage — grab single video frames at given timestamps (ffmpeg).

Pure stdlib + ffmpeg, so it runs with the system python3 (no venv). Used only
when the user asks to process specific moments (e.g. a shared presentation).
Writes frames/slide-NNNN.<ext> into the meeting folder and a manifest the
describe step consumes. The vision description happens in describe_frames.py.

Timestamps: "mm:ss" (one colon) or "hh:mm:ss" (two colons); a bare number is
seconds. Order is preserved — the i-th timestamp becomes slide-000i.

Usage:
  extract_frames.py --video meeting.mp4 --out-dir <meeting_dir> \
      --manifest <meeting_dir>/frames_manifest.json [--image-format png] \
      10:20 15:10 32:30 46:00 01:10:23
"""
import argparse
import json
import os
import subprocess
import sys


def parse_timestamp(value):
    """'mm:ss' | 'hh:mm:ss' | bare seconds -> int/float seconds. Raises ValueError."""
    s = str(value).strip()
    if not s:
        raise ValueError("empty timestamp")
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(f"too many ':' in timestamp: {value!r}")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"non-numeric timestamp: {value!r}")
    if any(n < 0 for n in nums):
        raise ValueError(f"negative timestamp: {value!r}")
    if len(parts) == 1:
        secs = nums[0]
    elif len(parts) == 2:
        secs = nums[0] * 60 + nums[1]
    else:
        secs = nums[0] * 3600 + nums[1] * 60 + nums[2]
    return int(secs) if float(secs).is_integer() else secs


def slide_id(index):
    """1-based index -> 'slide-0001'."""
    return f"slide-{index:04d}"


def build_manifest(video, timestamps, image_format="png"):
    """Build the (pure, no-ffmpeg) manifest. Image paths are relative to the
    meeting folder so the JSON stays portable."""
    frames = []
    for i, ts in enumerate(timestamps, 1):
        sid = slide_id(i)
        frames.append({
            "slide": sid,
            "timestamp": str(ts).strip(),
            "timestamp_s": parse_timestamp(ts),
            "image": f"frames/{sid}.{image_format}",
        })
    return {
        "video": os.path.abspath(video),
        "image_format": image_format,
        "frames": frames,
    }


def extract_one(ffmpeg, video, seconds, out_path, image_format, jpeg_quality):
    """Grab a single frame at `seconds` into out_path (ffmpeg); exit on failure."""
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-ss", str(seconds), "-i", video,
           "-frames:v", "1"]
    if image_format in ("jpg", "jpeg"):
        cmd += ["-q:v", str(jpeg_quality)]
    cmd += [out_path]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0 or not os.path.isfile(out_path):
        sys.stderr.write(p.stderr)
        sys.exit(f"ffmpeg failed to extract a frame at {seconds}s "
                 f"(past end of video?) -> {out_path}")


def main():
    ap = argparse.ArgumentParser(description="Grab video frames at timestamps (ffmpeg).")
    ap.add_argument("--video", required=True)
    ap.add_argument("--out-dir", required=True, help="meeting folder; frames/ created inside")
    ap.add_argument("--manifest", required=True, help="output manifest JSON path")
    ap.add_argument("--image-format", default="png", choices=["png", "jpg", "jpeg"])
    ap.add_argument("--jpeg-quality", type=int, default=2)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("timestamps", nargs="+", help="mm:ss or hh:mm:ss, in order")
    args = ap.parse_args()

    if not os.path.isfile(args.video):
        sys.exit(f"video not found: {args.video}")

    try:
        manifest = build_manifest(args.video, args.timestamps, args.image_format)
    except ValueError as exc:
        sys.exit(f"invalid timestamp: {exc}")
    frames_dir = os.path.join(args.out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    for fr in manifest["frames"]:
        out_path = os.path.join(args.out_dir, fr["image"])
        extract_one(args.ffmpeg, args.video, fr["timestamp_s"], out_path,
                    args.image_format, args.jpeg_quality)
        sys.stderr.write(f"  {fr['slide']} @ {fr['timestamp']} -> {fr['image']}\n")

    os.makedirs(os.path.dirname(os.path.abspath(args.manifest)) or ".", exist_ok=True)
    with open(args.manifest, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    sys.stderr.write(f"  wrote manifest ({len(manifest['frames'])} frames) -> {args.manifest}\n")


if __name__ == "__main__":
    main()
