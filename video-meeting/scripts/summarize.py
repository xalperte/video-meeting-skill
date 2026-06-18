#!/usr/bin/env python3
"""
Stage 6 — Summarize the (named) transcript via an Ollama LLM.

Stdlib only; talks to Ollama over HTTP. Meeting-type and language aware. Long
transcripts are handled with map-reduce: each chunk is condensed to notes (map),
then the notes are summarized into the final structured JSON (reduce). This keeps
us within the context window regardless of meeting length.

Outputs:
  summary.json  -> {"tldr": "...", "sections": [{"category","points"}], ...}
  summary.md    -> human-readable rendering (also handy as a slide/report source)

Use --dry-run to print the assembled prompt(s) without calling Ollama.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ollama_client import generate, parse_json_loose  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATES = os.path.normpath(os.path.join(HERE, "..", "templates"))
MEETING_TYPES = {"feature", "grooming", "catchup", "presentation", "other"}


def load_template(templates_dir, *parts):
    path = os.path.join(templates_dir, *parts)
    if not os.path.isfile(path):
        sys.exit(f"template not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def fill(template, mapping):
    out = template
    for token, value in mapping.items():
        out = out.replace(token, str(value))
    return out


def chunk_text(text, max_chars):
    """Split on line boundaries into chunks of at most ~max_chars."""
    if len(text) <= max_chars:
        return [text]
    chunks, cur, size = [], [], 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > max_chars and cur:
            chunks.append("".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line)
    if cur:
        chunks.append("".join(cur))
    return chunks


def language_phrase(lang):
    if not lang or lang.lower() == "auto":
        return "the same language spoken in the transcript"
    return lang


def render_markdown(summary, title="Meeting Summary"):
    lines = [f"# {title}", ""]
    tldr = summary.get("tldr", "").strip()
    if tldr:
        lines += [f"**TL;DR:** {tldr}", ""]
    for sec in summary.get("sections", []):
        cat = sec.get("category", "").strip() or "Notes"
        lines.append(f"## {cat}")
        for pt in sec.get("points", []):
            lines.append(f"- {pt}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="Summarize a transcript via Ollama.")
    ap.add_argument("--transcript", required=True, help="named transcript (.md/.txt)")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="gemma4:12b")
    ap.add_argument("--meeting-type", default="other")
    ap.add_argument("--output-language", default="auto")
    ap.add_argument("--audience", default="team")
    ap.add_argument("--tone", default="neutral")
    ap.add_argument("--detail-level", default="standard")
    ap.add_argument("--num-ctx", type=int, default=65536)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--max-chunk-chars", type=int, default=24000,
                    help="map-reduce threshold; chunks larger than this are split")
    ap.add_argument("--templates-dir", default=DEFAULT_TEMPLATES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mtype = args.meeting_type if args.meeting_type in MEETING_TYPES else "other"
    if not os.path.isfile(args.transcript):
        sys.exit(f"transcript not found: {args.transcript}")
    with open(args.transcript, "r", encoding="utf-8") as fh:
        transcript = fh.read()

    sdir = (args.templates_dir, "summary_prompts")
    base_tpl = load_template(*sdir, "base.md")
    map_tpl = load_template(*sdir, "map.md")
    guidance = load_template(*sdir, f"{mtype}.md")
    options = {"num_ctx": args.num_ctx, "temperature": args.temperature}
    lang = language_phrase(args.output_language)

    chunks = chunk_text(transcript, args.max_chunk_chars)

    # ---- map: condense each chunk (skipped when a single chunk fits) -------- #
    if len(chunks) > 1:
        sys.stderr.write(f"  map-reduce: {len(chunks)} chunks\n")
        notes = []
        for i, ch in enumerate(chunks, 1):
            prompt = fill(map_tpl, {"__TRANSCRIPT__": ch})
            if args.dry_run:
                if i == 1:
                    print("===== MAP PROMPT (chunk 1) =====\n" + prompt)
                continue
            sys.stderr.write(f"  mapping chunk {i}/{len(chunks)}…\n")
            notes.append(generate(args.host, args.model, prompt, options=options))
        condensed = "\n".join(notes) if not args.dry_run else \
            f"[map notes for {len(chunks)} chunks]"
    else:
        condensed = transcript

    # ---- reduce: produce the final structured summary ---------------------- #
    reduce_prompt = fill(base_tpl, {
        "__MEETING_TYPE__": mtype,
        "__GUIDANCE__": guidance.strip(),
        "__AUDIENCE__": args.audience,
        "__TONE__": args.tone,
        "__DETAIL__": args.detail_level,
        "__LANGUAGE__": lang,
        "__TRANSCRIPT__": condensed,
    })

    if args.dry_run:
        print("===== REDUCE PROMPT =====\n" + reduce_prompt)
        return

    sys.stderr.write("  summarizing…\n")
    raw = generate(args.host, args.model, reduce_prompt, options=options, fmt="json")
    try:
        summary = parse_json_loose(raw)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"could not parse summary JSON: {exc}\n---\n{raw[:500]}")
    summary.setdefault("tldr", "")
    summary.setdefault("sections", [])

    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    with open(args.out_md, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(summary))
    sys.stderr.write(f"  done -> {args.out_json}, {args.out_md}\n")


if __name__ == "__main__":
    main()
