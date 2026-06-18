#!/usr/bin/env python3
"""
Renderer — tasks.xlsx from meeting_record.json (runs in render-env: openpyxl).

The Excel is a VIEW of the record (the single source of truth), never authored by
hand. Action items are split visually into explicit (stated/agreed) vs ai_suggested
(inferred), with decisions and open questions on their own sheets.

Usage:
  $RENDER_PY render_tasks_xlsx.py --record meeting_record.json --out tasks.xlsx
"""
import argparse
import json
import os
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
EXPLICIT_FILL = PatternFill("solid", fgColor="E2EFDA")   # light green
SUGGEST_FILL = PatternFill("solid", fgColor="FFF2CC")    # light amber
WRAP = Alignment(vertical="top", wrap_text=True)

COLS = [("Title", 50), ("Type", 14), ("Assignee", 20),
        ("Priority", 12), ("Source TS", 16), ("Confidence", 12)]


def style_header(ws, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(ncols)}1"


def add_items_sheet(wb, items):
    ws = wb.active
    ws.title = "Action Items"
    for i, (name, width) in enumerate(COLS, 1):
        ws.cell(row=1, column=1 + (i - 1), value=name)
        ws.column_dimensions[get_column_letter(i)].width = width
    style_header(ws, len(COLS))

    # explicit first, then suggested; stable within each by priority
    order = {"high": 0, "medium": 1, "low": 2}
    explicit = [t for t in items if t.get("type") == "explicit"]
    suggested = [t for t in items if t.get("type") == "ai_suggested"]
    for group in (explicit, suggested):
        group.sort(key=lambda t: order.get(t.get("priority"), 1))

    row = 2
    for t in explicit + suggested:
        ts = ", ".join(t.get("source_ts", []) or [])
        vals = [t.get("title", ""), t.get("type", ""), t.get("assignee", ""),
                t.get("priority", ""), ts, t.get("confidence", "")]
        fill = EXPLICIT_FILL if t.get("type") == "explicit" else SUGGEST_FILL
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=row, column=c, value=v)
            cell.fill = fill
            cell.alignment = WRAP
        row += 1
    if row == 2:
        ws.cell(row=2, column=1, value="(no action items)")


def add_list_sheet(wb, title, values):
    ws = wb.create_sheet(title)
    ws.cell(row=1, column=1, value=title)
    ws.column_dimensions["A"].width = 90
    style_header(ws, 1)
    if values:
        for i, v in enumerate(values, start=2):
            ws.cell(row=i, column=1, value=v).alignment = WRAP
    else:
        ws.cell(row=2, column=1, value=f"(no {title.lower()})")


def main():
    ap = argparse.ArgumentParser(description="Render tasks.xlsx from the meeting record.")
    ap.add_argument("--record", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.record):
        sys.exit(f"record not found: {args.record}")
    with open(args.record, "r", encoding="utf-8") as fh:
        record = json.load(fh)

    wb = Workbook()
    add_items_sheet(wb, record.get("action_items", []))
    add_list_sheet(wb, "Decisions", record.get("decisions", []))
    add_list_sheet(wb, "Open Questions", record.get("open_questions", []))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    wb.save(args.out)
    n = len(record.get("action_items", []))
    sys.stderr.write(f"  tasks.xlsx: {n} action items -> {args.out}\n")


if __name__ == "__main__":
    main()
