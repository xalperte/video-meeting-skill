#!/usr/bin/env python3
"""
Stage 9 — Draft the attendee email (Markdown) from meeting_record.json.

By default the LLM writes it, so it is naturally phrased and in the meeting's
output language. `--no-llm` produces a deterministic English template instead
(useful for offline runs or when Ollama is unavailable).

Output: email.md  (first line is "Subject: ...").
Use --dry-run to print the assembled prompt without calling Ollama.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ollama_client import generate  # noqa: E402
from summarize import fill, language_phrase, load_template  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATES = os.path.normpath(os.path.join(HERE, "..", "templates"))


def collect_points(record, limit=6):
    pts = []
    for sec in record.get("summary", {}).get("sections", []):
        for p in sec.get("points", []):
            pts.append(p)
            if len(pts) >= limit:
                return pts
    return pts


def collect_actions(record):
    lines = []
    for it in record.get("action_items", []):
        who = it.get("assignee") or "unassigned"
        tag = "" if it.get("type") == "explicit" else " (suggested)"
        lines.append(f"- {it.get('title','').strip()} — {who}{tag}")
    return lines


def fallback_email(record, attachments):
    m = record.get("meeting", {})
    title = m.get("title", "Meeting")
    tldr = record.get("summary", {}).get("tldr", "").strip()
    out = [f"Subject: {title} — summary & action items", "",
           "Hi all,", "",
           f"Sharing the outputs from {title}"
           + (f" ({m.get('date')})" if m.get("date") else "") + ".", ""]
    if tldr:
        out += [tldr, ""]
    points = collect_points(record)
    if points:
        out.append("Key points:")
        out += [f"- {p}" for p in points]
        out.append("")
    actions = collect_actions(record)
    if actions:
        out.append("Action items:")
        out += actions
        out.append("")
    if attachments:
        out.append("Attached: " + ", ".join(attachments) + ".")
        out.append("")
    out += ["Thanks,", "[Your name]", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Draft the attendee email from the record.")
    ap.add_argument("--record", required=True, help="meeting_record.json")
    ap.add_argument("--out", required=True, help="output email.md")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="gemma4:12b")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--attachments", nargs="*",
                    default=["summary", "slides", "report", "tasks spreadsheet"])
    ap.add_argument("--templates-dir", default=DEFAULT_TEMPLATES)
    ap.add_argument("--no-llm", action="store_true",
                    help="use the deterministic English template instead of the LLM")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.record):
        sys.exit(f"record not found: {args.record}")
    with open(args.record, "r", encoding="utf-8") as fh:
        record = json.load(fh)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    if args.no_llm:
        email = fallback_email(record, args.attachments)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(email if email.endswith("\n") else email + "\n")
        sys.stderr.write(f"  email (template) -> {args.out}\n")
        return

    m = record.get("meeting", {})
    tpl = load_template(args.templates_dir, "email_prompt.md")
    prompt = fill(tpl, {
        "__LANGUAGE__": language_phrase(m.get("language_out", "auto")),
        "__TITLE__": m.get("title", "Meeting"),
        "__DATE__": m.get("date", ""),
        "__TLDR__": record.get("summary", {}).get("tldr", ""),
        "__POINTS__": "\n".join(f"- {p}" for p in collect_points(record)) or "(none)",
        "__ACTIONS__": "\n".join(collect_actions(record)) or "(none)",
        "__ATTACHMENTS__": ", ".join(args.attachments),
    })

    if args.dry_run:
        print("===== EMAIL PROMPT =====\n" + prompt)
        return

    options = {"num_ctx": args.num_ctx, "temperature": args.temperature}
    email = generate(args.host, args.model, prompt, options=options).strip()
    if not email:
        email = fallback_email(record, args.attachments)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(email + "\n")
    sys.stderr.write(f"  email -> {args.out}\n")


if __name__ == "__main__":
    main()
