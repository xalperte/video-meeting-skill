#!/usr/bin/env python3
"""Presentation template discovery, resolution, and styling helpers.

A template is a folder under templates/presentation/<name>/ with base Office
files (slides.pptx, report.docx), an optional logo.png, and a template.yaml
(metadata + slide-layout contract + xlsx style block). These helpers are pure
(no Office libraries) so they are testable on their own; PyYAML is imported
lazily only when template.yaml is read.
"""
import os

# Defaults match the previous hardcoded look so a minimal or drop-in corporate
# template still renders sensibly when template.yaml (or a key) is absent.
DEFAULT_XLSX = {
    "header_fill": "1F4E78",
    "header_font_color": "FFFFFF",
    "explicit_fill": "E2EFDA",
    "suggested_fill": "FFF2CC",
    "font_name": "Calibri",
    "banner": False,
}
DEFAULT_SLIDES = {
    "title_layout": "Title Slide",
    "content_layout": "Title and Content",
}


def templates_root(skill_root):
    """Absolute path to the presentation-templates directory."""
    return os.path.join(skill_root, "templates", "presentation")


def discover_templates(root):
    """Sorted names of template subfolders under root ([] if root missing)."""
    if not os.path.isdir(root):
        return []
    return sorted(
        name for name in os.listdir(root)
        if os.path.isdir(os.path.join(root, name))
    )


def load_template_yaml(folder):
    """Parse <folder>/template.yaml -> dict, or {} if the file is absent."""
    path = os.path.join(folder, "template.yaml")
    if not os.path.isfile(path):
        return {}
    try:
        import yaml
    except ImportError:
        raise SystemExit(
            "PyYAML is required to read template.yaml.\n"
            "Install it in render-env:  python3 -m pip install pyyaml"
        )
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_template(root, name):
    """Return (folder_path, data). Raise SystemExit listing options if unknown."""
    folder = os.path.join(root, name)
    if not os.path.isdir(folder):
        avail = ", ".join(discover_templates(root)) or "(none)"
        raise SystemExit("unknown template %r; available: %s" % (name, avail))
    return folder, load_template_yaml(folder)


def xlsx_style(data):
    """DEFAULT_XLSX overlaid with data['xlsx'] (data may be {} or None)."""
    merged = dict(DEFAULT_XLSX)
    merged.update(((data or {}).get("xlsx") or {}))
    return merged


def slides_layouts(data):
    """DEFAULT_SLIDES overlaid with data['slides']."""
    merged = dict(DEFAULT_SLIDES)
    merged.update(((data or {}).get("slides") or {}))
    return merged


def find_layout_by_name(layouts, name, fallback_idx=0):
    """Pick a slide layout from `layouts` (objects with a `.name`).

    Returns (layout, used_fallback). Matches `name` case-insensitively; else
    layouts[fallback_idx]; else layouts[0].
    """
    if name:
        target = name.strip().lower()
        for lay in layouts:
            if (getattr(lay, "name", "") or "").strip().lower() == target:
                return lay, False
    if 0 <= fallback_idx < len(layouts):
        return layouts[fallback_idx], True
    return layouts[0], True
