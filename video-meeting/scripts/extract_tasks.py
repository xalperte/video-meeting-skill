#!/usr/bin/env python3
"""
Stage 7 — Extract structured action items from the (named) transcript via Ollama.

Stdlib only; talks to Ollama over HTTP and asks for JSON output. Produces:
  tasks.json -> {
    "action_items": [{title, type, assignee, priority, source_ts, confidence}],
    "decisions": [...], "open_questions": [...]
  }

`type` is "explicit" (actually stated/agreed) or "ai_suggested" (inferred follow-up).
Assignees are chosen from the known participant names when the transcript supports it.
Long transcripts are extracted per chunk and merged (deduped by title).

Use --dry-run to print the assembled prompt without calling Ollama.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ollama_client import generate, parse_json_loose  # noqa: E402
from summarize import chunk_text, fill, language_phrase, load_template  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATES = os.path.normpath(os.path.join(HERE, "..", "templates"))
MEETING_TYPES = {"feature", "grooming", "catchup", "presentation", "other"}
PRIORITIES = {"high", "medium", "low"}


def normalize(doc, suggest_tasks):
    items = []
    for it in doc.get("action_items", []) or []:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        typ = it.get("type", "explicit")
        typ = typ if typ in ("explicit", "ai_suggested") else "explicit"
        if typ == "ai_suggested" and not suggest_tasks:
            continue
        pri = it.get("priority", "medium")
        pri = pri if pri in PRIORITIES else "medium"
        ts = it.get("source_ts", [])
        ts = ts if isinstance(ts, list) else ([ts] if ts else [])
        try:
            conf = float(it.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        items.append({
            "title": str(it["title"]).strip(),
            "type": typ,
            "assignee": str(it.get("assignee", "") or "").strip(),
            "priority": pri,
            "source_ts": [str(x) for x in ts],
            "confidence": round(conf, 3),
        })
    return {
        "action_items": items,
        "decisions": [str(x) for x in (doc.get("decisions") or []) if x],
        "open_questions": [str(x) for x in (doc.get("open_questions") or []) if x],
    }


def merge(docs):
    """Merge per-chunk extractions, deduping by normalized title / text."""
    out = {"action_items": [], "decisions": [], "open_questions": []}
    seen_items, seen_dec, seen_q = set(), set(), set()
    for d in docs:
        for it in d["action_items"]:
            key = it["title"].lower()
            if key not in seen_items:
                seen_items.add(key)
                out["action_items"].append(it)
        for x in d["decisions"]:
            if x.lower() not in seen_dec:
                seen_dec.add(x.lower())
                out["decisions"].append(x)
        for x in d["open_questions"]:
            if x.lower() not in seen_q:
                seen_q.add(x.lower())
                out["open_questions"].append(x)
    return out


def main():
    ap = argparse.ArgumentParser(description="Extract action items via Ollama.")
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--out", required=True, help="output tasks.json")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--meeting-type", default="other")
    ap.add_argument("--output-language", default="auto")
    ap.add_argument("--participants", nargs="*", default=None,
                    help="known attendee names, for assignee selection")
    ap.add_argument("--suggest-tasks", dest="suggest_tasks", action="store_true")
    ap.add_argument("--no-suggest-tasks", dest="suggest_tasks", action="store_false")
    ap.set_defaults(suggest_tasks=True)
    ap.add_argument("--num-ctx", type=int, default=65536)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--max-chunk-chars", type=int, default=24000)
    ap.add_argument("--templates-dir", default=DEFAULT_TEMPLATES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mtype = args.meeting_type if args.meeting_type in MEETING_TYPES else "other"
    if not os.path.isfile(args.transcript):
        sys.exit(f"transcript not found: {args.transcript}")
    with open(args.transcript, "r", encoding="utf-8") as fh:
        transcript = fh.read()

    base_tpl = load_template(args.templates_dir, "task_prompts", "base.md")
    guidance = load_template(args.templates_dir, "task_prompts", f"{mtype}.md")
    participants = ", ".join(args.participants) if args.participants else "(none provided)"
    suggest_note = ("Include ai_suggested items where genuinely useful."
                    if args.suggest_tasks else
                    "Do NOT include any ai_suggested items in this run; only explicit ones.")
    options = {"num_ctx": args.num_ctx, "temperature": args.temperature}
    lang = language_phrase(args.output_language)

    def build(chunk):
        return fill(base_tpl, {
            "__MEETING_TYPE__": mtype,
            "__GUIDANCE__": guidance.strip(),
            "__PARTICIPANTS__": participants,
            "__LANGUAGE__": lang,
            "__SUGGEST_TASKS__": suggest_note,
            "__TRANSCRIPT__": chunk,
        })

    chunks = chunk_text(transcript, args.max_chunk_chars)

    if args.dry_run:
        print(f"(chunks: {len(chunks)})")
        print("===== TASK PROMPT (chunk 1) =====\n" + build(chunks[0]))
        return

    docs = []
    for i, ch in enumerate(chunks, 1):
        sys.stderr.write(f"  extracting tasks {i}/{len(chunks)}…\n")
        raw = generate(args.host, args.model, build(ch), options=options, fmt="json")
        try:
            docs.append(normalize(parse_json_loose(raw), args.suggest_tasks))
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"could not parse tasks JSON: {exc}\n---\n{raw[:500]}")

    result = merge(docs) if len(docs) > 1 else docs[0]
    n_exp = sum(1 for t in result["action_items"] if t["type"] == "explicit")
    n_sug = sum(1 for t in result["action_items"] if t["type"] == "ai_suggested")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    sys.stderr.write(
        f"  done: {n_exp} explicit + {n_sug} suggested, "
        f"{len(result['decisions'])} decisions -> {args.out}\n"
    )


if __name__ == "__main__":
    main()
