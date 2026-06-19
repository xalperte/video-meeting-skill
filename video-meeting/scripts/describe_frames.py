#!/usr/bin/env python3
"""
Optional stage — OCR extracted frames with a local Ollama OCR/vision model,
then summarize all the OCR'd text into a markdown digest.

Stdlib only; reuses ollama_client (HTTP) and summarize helpers. Runs with the
system python3. Reads the manifest written by extract_frames.py; never calls
ffmpeg itself. OCR and text-summary models never co-reside — Ollama's
keep_alive=0s unloads one before the next loads.

Outputs (into the meeting folder):
  video-frames-details.json  -> {video, vision_model, output_language, frames:[
                                  {slide, timestamp, timestamp_s, image, text}]}
  video-frames-summary.md    -> markdown summary of the shared presentation
"""
import argparse
import base64
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ollama_client import generate  # noqa: E402
from summarize import chunk_text, fill, language_phrase, load_template  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATES = os.path.normpath(os.path.join(HERE, "..", "templates"))


def truncate(text, max_chars):
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def build_details(manifest, descriptions, vision_model, output_language):
    """Combine the manifest with {slide: text} into the details document."""
    frames = []
    for fr in manifest.get("frames", []):
        frames.append({
            "slide": fr["slide"],
            "timestamp": fr["timestamp"],
            "timestamp_s": fr["timestamp_s"],
            "image": fr["image"],
            "text": (descriptions.get(fr["slide"], "") or "").strip(),
        })
    return {
        "video": os.path.basename(manifest.get("video", "")),
        "vision_model": vision_model,
        "output_language": output_language,
        "frames": frames,
    }


def render_digest_md(details):
    """Markdown of per-slide OCR text, fed to the summary model."""
    lines = []
    for fr in details["frames"]:
        lines.append(f"## {fr['slide']} [{fr['timestamp']}]")
        lines.append(fr["text"] or "(no readable content)")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def encode_image(path):
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def ensure_model(host, model):
    """Fail fast (with the pull command) if the OCR/vision model isn't present."""
    url = host.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            names = {m.get("name", "") for m in json.loads(resp.read()).get("models", [])}
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Ollama unreachable at {host}: {exc}")
    base = model.split(":")[0]
    if not any(n == model or n.split(":")[0] == base for n in names):
        sys.exit(f"OCR/vision model not pulled: {model}\n  run: ollama pull {model}")


def summarize_digest(host, model, digest, lang, options, max_chunk_chars, templates_dir):
    tpl = load_template(templates_dir, "frame_prompts", "summary.md")
    chunks = chunk_text(digest, max_chunk_chars)
    parts = [generate(host, model, fill(tpl, {"__LANGUAGE__": lang, "__CONTENT__": ch}),
                      options=options) for ch in chunks]
    if len(parts) > 1:
        combined = "\n\n".join(parts)
        return generate(host, model,
                        fill(tpl, {"__LANGUAGE__": lang, "__CONTENT__": combined}),
                        options=options)
    return parts[0]


def main():
    ap = argparse.ArgumentParser(description="OCR + summarize frames via Ollama.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--base-dir", default=None,
                    help="folder image paths are relative to (default: manifest dir)")
    ap.add_argument("--out-details", required=True)
    ap.add_argument("--out-summary", required=True)
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--vision-model", default="chandra-ocr-2")
    ap.add_argument("--summary-model", default="gemma4:12b")
    ap.add_argument("--output-language", default="auto")
    ap.add_argument("--num-ctx", type=int, default=65536)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--describe-max-chars", type=int, default=4000)
    ap.add_argument("--max-chunk-chars", type=int, default=24000)
    ap.add_argument("--templates-dir", default=DEFAULT_TEMPLATES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.manifest):
        sys.exit(f"manifest not found: {args.manifest}")
    with open(args.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    base_dir = args.base_dir or os.path.dirname(os.path.abspath(args.manifest))
    lang = language_phrase(args.output_language)
    options = {"num_ctx": args.num_ctx, "temperature": args.temperature}
    describe_tpl = load_template(args.templates_dir, "frame_prompts", "describe.md")

    if args.dry_run:
        frames = manifest.get("frames", [])
        print(f"(frames: {len(frames)})")
        if frames:
            print("===== OCR PROMPT (slide-0001) =====")
            print(fill(describe_tpl, {"__TIMESTAMP__": frames[0]["timestamp"],
                                      "__LANGUAGE__": lang}))
        return

    ensure_model(args.host, args.vision_model)
    ensure_model(args.host, args.summary_model)

    descriptions = {}
    for fr in manifest.get("frames", []):
        img_path = os.path.join(base_dir, fr["image"])
        if not os.path.isfile(img_path):
            sys.exit(f"frame image missing: {img_path}")
        sys.stderr.write(f"  OCR {fr['slide']} @ {fr['timestamp']}…\n")
        prompt = fill(describe_tpl, {"__TIMESTAMP__": fr["timestamp"], "__LANGUAGE__": lang})
        raw = generate(args.host, args.vision_model, prompt, options=options,
                       images=[encode_image(img_path)])
        descriptions[fr["slide"]] = truncate(raw, args.describe_max_chars)

    details = build_details(manifest, descriptions, args.vision_model, args.output_language)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_details)) or ".", exist_ok=True)
    with open(args.out_details, "w", encoding="utf-8") as fh:
        json.dump(details, fh, ensure_ascii=False, indent=2)

    sys.stderr.write("  summarizing frames…\n")
    summary_md = summarize_digest(args.host, args.summary_model, render_digest_md(details),
                                  lang, options, args.max_chunk_chars, args.templates_dir)
    with open(args.out_summary, "w", encoding="utf-8") as fh:
        fh.write(summary_md.rstrip() + "\n")
    sys.stderr.write(f"  done -> {args.out_details}, {args.out_summary}\n")


if __name__ == "__main__":
    main()
