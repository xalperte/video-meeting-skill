#!/usr/bin/env python3
"""Generate the starter presentation templates (run in render-env).

Produces clean, editable base files for each starter palette:
  templates/presentation/<name>/slides.pptx
  templates/presentation/<name>/report.docx
  templates/presentation/<name>/template.yaml
  templates/presentation/<name>/logo.png   (1x1 transparent placeholder)

Re-runnable and idempotent. Output is committed so a bare checkout has working
templates. Replace slides.pptx/report.docx with a corporate file to rebrand.

Usage:
  $RENDER_PY build_starter_templates.py [--root <skill_root>]
"""
import argparse
import base64
import os
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor as PRGB
from pptx.util import Pt as PPt
from docx import Document
from docx.shared import Pt as DPt, RGBColor as DRGB

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.normpath(os.path.join(HERE, ".."))

# 1x1 transparent PNG (placeholder logo).
_LOGO_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    b"+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

STARTERS = {
    "executive": {"name": "Executive", "accent": "1F3864",
                  "desc": "Navy, serif headings — leadership readouts",
                  "heading_font": "Georgia", "body_font": "Calibri"},
    "client": {"name": "Client", "accent": "117A65",
               "desc": "Teal, sans — client-facing, logo-forward",
               "heading_font": "Calibri", "body_font": "Calibri"},
    "internal": {"name": "Internal", "accent": "595959",
                 "desc": "Minimal grey — internal team default",
                 "heading_font": "Calibri", "body_font": "Calibri"},
}


def _style_slide_master(prs, cfg):
    """Color the title placeholders on each layout with the accent."""
    accent = PRGB.from_string(cfg["accent"])
    for layout in prs.slide_layouts:
        for ph in layout.placeholders:
            if ph.placeholder_format.idx == 0 and ph.has_text_frame:  # title
                for para in ph.text_frame.paragraphs:
                    para.font.color.rgb = accent
                    para.font.name = cfg["heading_font"]
                    para.font.size = PPt(32)


def build_slides(folder, cfg):
    prs = Presentation()
    _style_slide_master(prs, cfg)
    prs.save(os.path.join(folder, "slides.pptx"))


def build_report(folder, cfg):
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = cfg["body_font"], DPt(11)
    accent = DRGB.from_string(cfg["accent"])
    for level in ("Title", "Heading 1", "Heading 2"):
        if level in {s.name for s in doc.styles}:
            st = doc.styles[level]
            st.font.name = cfg["heading_font"]
            st.font.color.rgb = accent
    doc.save(os.path.join(folder, "report.docx"))


def build_template_yaml(folder, cfg):
    accent = cfg["accent"]
    text = (
        f'name: "{cfg["name"]}"\n'
        f'description: "{cfg["desc"]}"\n'
        f'accent: "{accent}"\n'
        "slides:\n"
        '  title_layout: "Title Slide"\n'
        '  content_layout: "Title and Content"\n'
        "xlsx:\n"
        f'  header_fill: "{accent}"\n'
        '  header_font_color: "FFFFFF"\n'
        '  explicit_fill: "E2EFDA"\n'
        '  suggested_fill: "FFF2CC"\n'
        f'  font_name: "{cfg["body_font"]}"\n'
        "  banner: false\n"
    )
    with open(os.path.join(folder, "template.yaml"), "w", encoding="utf-8") as fh:
        fh.write(text)


def build_all(root):
    base = os.path.join(root, "templates", "presentation")
    for key, cfg in STARTERS.items():
        folder = os.path.join(base, key)
        os.makedirs(folder, exist_ok=True)
        build_slides(folder, cfg)
        build_report(folder, cfg)
        build_template_yaml(folder, cfg)
        with open(os.path.join(folder, "logo.png"), "wb") as fh:
            fh.write(_LOGO_PNG)
        sys.stderr.write(f"  built template: {key} -> {folder}\n")


def main():
    ap = argparse.ArgumentParser(description="Generate starter presentation templates.")
    ap.add_argument("--root", default=DEFAULT_ROOT)
    args = ap.parse_args()
    build_all(args.root)


if __name__ == "__main__":
    main()
