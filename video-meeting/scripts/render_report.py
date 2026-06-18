#!/usr/bin/env python3
"""
Renderer — report.pdf from meeting_record.json (runs in render-env: python-docx).

Same content as the slides, but laid out as a READ-AS-A-DOCUMENT report, not a
deck. We build a .docx (clean, styled, also kept as an editable artifact) and
convert it to PDF with LibreOffice headless.

Usage:
  $RENDER_PY render_report.py --record meeting_record.json \
     --out-pdf report.pdf --libreoffice /usr/bin/soffice
"""
import argparse
import json
import os
import subprocess
import sys

from docx import Document
from docx.shared import Pt


def fmt_duration(seconds):
    if not seconds:
        return ""
    s = int(round(seconds))
    h, m = s // 3600, (s % 3600) // 60
    return (f"{h}h {m}m" if h else f"{m}m")


def add_items_table(doc, items):
    if not items:
        doc.add_paragraph("(none)")
        return
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for c, head in enumerate(["Title", "Assignee", "Priority", "Source", "Conf."]):
        run = table.rows[0].cells[c].paragraphs[0].add_run(head)
        run.bold = True
    for t in items:
        cells = table.add_row().cells
        cells[0].text = t.get("title", "")
        cells[1].text = t.get("assignee", "") or "—"
        cells[2].text = t.get("priority", "")
        cells[3].text = ", ".join(t.get("source_ts", []) or [])
        cells[4].text = str(t.get("confidence", ""))


def build(doc, record):
    m = record.get("meeting", {})
    doc.add_heading(m.get("title", "Meeting") + " — Meeting Report", level=0)

    meta_bits = []
    if m.get("date"):
        meta_bits.append(m["date"])
    if m.get("type"):
        meta_bits.append(f"Type: {m['type']}")
    if m.get("language_out"):
        meta_bits.append(f"Language: {m['language_out']}")
    if m.get("duration_s"):
        meta_bits.append(f"Duration: {fmt_duration(m['duration_s'])}")
    if meta_bits:
        p = doc.add_paragraph(" · ".join(meta_bits))
        p.runs[0].italic = True

    # Participants
    parts = record.get("participants", [])
    if parts:
        doc.add_heading("Participants", level=1)
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        for c, head in enumerate(["Name", "Status", "Confidence"]):
            table.rows[0].cells[c].paragraphs[0].add_run(head).bold = True
        for p in parts:
            cells = table.add_row().cells
            cells[0].text = p.get("name", "") or "(unnamed)"
            cells[1].text = p.get("status", "")
            cells[2].text = str(round(p.get("match_confidence", 0.0), 2))

    # Executive summary
    tldr = record.get("summary", {}).get("tldr", "").strip()
    if tldr:
        doc.add_heading("Executive Summary", level=1)
        doc.add_paragraph(tldr)

    # Summary by category
    sections = record.get("summary", {}).get("sections", [])
    if sections:
        doc.add_heading("Summary", level=1)
        for sec in sections:
            doc.add_heading(sec.get("category", "Notes"), level=2)
            for pt in sec.get("points", []):
                doc.add_paragraph(pt, style="List Bullet")

    # Action items
    items = record.get("action_items", [])
    explicit = [t for t in items if t.get("type") == "explicit"]
    suggested = [t for t in items if t.get("type") == "ai_suggested"]
    doc.add_heading("Action Items", level=1)
    doc.add_heading("Agreed in the meeting", level=2)
    add_items_table(doc, explicit)
    doc.add_heading("Suggested (AI)", level=2)
    add_items_table(doc, suggested)

    # Decisions / open questions
    if record.get("decisions"):
        doc.add_heading("Decisions", level=1)
        for d in record["decisions"]:
            doc.add_paragraph(d, style="List Bullet")
    if record.get("open_questions"):
        doc.add_heading("Open Questions", level=1)
        for q in record["open_questions"]:
            doc.add_paragraph(q, style="List Bullet")


def main():
    ap = argparse.ArgumentParser(description="Render a PDF report from the meeting record.")
    ap.add_argument("--record", required=True)
    ap.add_argument("--out-pdf", required=True)
    ap.add_argument("--libreoffice", default="soffice")
    ap.add_argument("--no-keep-docx", dest="keep_docx", action="store_false")
    ap.set_defaults(keep_docx=True)
    args = ap.parse_args()

    if not os.path.isfile(args.record):
        sys.exit(f"record not found: {args.record}")
    with open(args.record, "r", encoding="utf-8") as fh:
        record = json.load(fh)

    outdir = os.path.dirname(os.path.abspath(args.out_pdf)) or "."
    os.makedirs(outdir, exist_ok=True)
    docx_path = os.path.splitext(os.path.abspath(args.out_pdf))[0] + ".docx"

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name, style.font.size = "Calibri", Pt(11)
    build(doc, record)
    doc.save(docx_path)
    sys.stderr.write(f"  report.docx -> {docx_path}\n")

    cmd = [args.libreoffice, "--headless", "--convert-to", "pdf",
           "--outdir", outdir, docx_path]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    pdf_out = os.path.splitext(docx_path)[0] + ".pdf"
    if p.returncode != 0 or not os.path.isfile(pdf_out):
        sys.stderr.write(f"  warn: PDF conversion failed: {p.stderr.strip()}\n")
        sys.stderr.write("  (the .docx is still available; install LibreOffice for PDF)\n")
    else:
        sys.stderr.write(f"  report.pdf -> {pdf_out}\n")

    if not args.keep_docx and os.path.isfile(pdf_out):
        os.remove(docx_path)


if __name__ == "__main__":
    main()
