#!/usr/bin/env python3
"""
Renderer — slides.pptx (+ optional .odp) from meeting_record.json.

Runs in render-env (python-pptx). The deck is a presentation VIEW of the record:
title -> overview (TL;DR) -> categorized summary -> action items split into two
groups (explicit vs AI-suggested). The .odp copy is produced by converting the
.pptx with LibreOffice headless.

Usage:
  $RENDER_PY render_slides.py --record meeting_record.json \
     --out-pptx slides.pptx --formats pptx odp --libreoffice /usr/bin/soffice
"""
import argparse
import json
import os
import subprocess
import sys

from pptx import Presentation
from pptx.util import Pt

MAX_BULLETS = 7  # split a section across slides beyond this many points


def add_title_slide(prs, title, subtitle):
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = title
    if slide.placeholders and len(slide.placeholders) > 1:
        slide.placeholders[1].text = subtitle


def add_bullets_slide(prs, title, bullets):
    """bullets: list of (text, level)."""
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    body = slide.placeholders[1].text_frame
    body.clear()
    if not bullets:
        body.paragraphs[0].text = "(none)"
        return
    for i, (text, level) in enumerate(bullets):
        p = body.paragraphs[0] if i == 0 else body.add_paragraph()
        p.text = text
        p.level = min(level, 4)
        p.font.size = Pt(18)


def chunked(title, bullets):
    """Yield (slide_title, bullets) splitting long lists across slides."""
    if len(bullets) <= MAX_BULLETS:
        yield title, bullets
        return
    n = 0
    for i in range(0, len(bullets), MAX_BULLETS):
        n += 1
        suffix = "" if i == 0 else f" (cont. {n})"
        yield title + suffix, bullets[i:i + MAX_BULLETS]


def item_line(t):
    who = t.get("assignee") or "unassigned"
    pri = t.get("priority", "")
    return f"{t.get('title','').strip()} — {who}" + (f"  [{pri}]" if pri else "")


def build(prs, record):
    m = record.get("meeting", {})
    title = m.get("title", "Meeting")
    sub_bits = [b for b in (m.get("date"), (m.get("type") or "").title()) if b]
    add_title_slide(prs, title, "  ·  ".join(sub_bits))

    tldr = record.get("summary", {}).get("tldr", "").strip()
    if tldr:
        add_bullets_slide(prs, "Overview", [(tldr, 0)])

    for sec in record.get("summary", {}).get("sections", []):
        cat = sec.get("category", "Notes")
        bullets = [(p, 0) for p in sec.get("points", [])]
        for stitle, sb in chunked(cat, bullets):
            add_bullets_slide(prs, stitle, sb)

    items = record.get("action_items", [])
    explicit = [item_line(t) for t in items if t.get("type") == "explicit"]
    suggested = [item_line(t) for t in items if t.get("type") == "ai_suggested"]
    for stitle, sb in chunked("Action Items", [(x, 0) for x in explicit]):
        add_bullets_slide(prs, stitle, sb or [("(none)", 0)])
    for stitle, sb in chunked("Suggested (AI)", [(x, 0) for x in suggested]):
        add_bullets_slide(prs, stitle, sb or [("(none)", 0)])


def convert_to(soffice, fmt, src, outdir):
    cmd = [soffice, "--headless", "--convert-to", fmt, "--outdir", outdir, src]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        sys.stderr.write(f"  warn: {fmt} conversion failed: {p.stderr.strip()}\n")
        return None
    out = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + f".{fmt}")
    return out if os.path.isfile(out) else None


def main():
    ap = argparse.ArgumentParser(description="Render slides from the meeting record.")
    ap.add_argument("--record", required=True)
    ap.add_argument("--out-pptx", required=True)
    ap.add_argument("--formats", nargs="*", default=["pptx", "odp"])
    ap.add_argument("--libreoffice", default="soffice")
    args = ap.parse_args()

    if not os.path.isfile(args.record):
        sys.exit(f"record not found: {args.record}")
    with open(args.record, "r", encoding="utf-8") as fh:
        record = json.load(fh)

    prs = Presentation()
    build(prs, record)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_pptx)) or ".", exist_ok=True)
    prs.save(args.out_pptx)
    sys.stderr.write(f"  slides.pptx: {len(prs.slides._sldIdLst)} slides -> {args.out_pptx}\n")

    if "odp" in args.formats:
        outdir = os.path.dirname(os.path.abspath(args.out_pptx)) or "."
        odp = convert_to(args.libreoffice, "odp", args.out_pptx, outdir)
        if odp:
            sys.stderr.write(f"  slides.odp -> {odp}\n")


if __name__ == "__main__":
    main()
