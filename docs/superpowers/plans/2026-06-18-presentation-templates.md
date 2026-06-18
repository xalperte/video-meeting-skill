# Selectable Presentation Templates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the slides, report, and xlsx renderers themeable via selectable, drop-in presentation templates chosen per audience.

**Architecture:** A template is a folder `templates/presentation/<name>/` with base `slides.pptx` + `report.docx` (opened and filled by the renderers), an optional `logo.png`, and a `template.yaml` (metadata + slide-layout contract + `xlsx:` style block). A new pure helper module `scripts/templates.py` discovers/resolves templates and applies defaults. `run.py` selects a template (`--template` / `rendering.template`) and passes `--template-dir` to the three renderers. `preflight.py` validates the selection. A re-runnable generator ships clean starters (`executive`, `client`, `internal`).

**Tech Stack:** Python 3 (system python3 for `run.py`/`preflight.py`/`templates.py`), render-env (python-pptx, python-docx, openpyxl, **+ pyyaml**), LibreOffice for conversion, stdlib `unittest`.

**Conventions (from the repo):**
- Scripts are stdlib-first, invoked by absolute interpreter path; renderers run in render-env.
- Tests are stdlib `unittest` under `video-meeting/tests/`, run with `bash video-meeting/tests/run_tests.sh` or `cd video-meeting && python3 -m unittest discover -s tests -p 'test_*.py'`.
- Renderer tests need render libs; use `VM_TEST_PYTHON` to point at a venv with them, and **skip gracefully** when a lib is missing (existing pattern).
- `ROOT` = `video-meeting/` (parent of `scripts/`); templates live at `ROOT/templates/presentation`.
- Commit locally only; never push/PR/touch remotes. Work on branch `feature/presentation-templates` (already created).

All paths below are relative to repo root unless absolute. Source dir is `video-meeting/scripts/`, tests dir is `video-meeting/tests/`.

---

## Task 1: `scripts/templates.py` — discovery/resolution/style helpers (TDD)

**Files:**
- Test: `video-meeting/tests/test_templates.py`
- Create: `video-meeting/scripts/templates.py`

- [ ] **Step 1: Write the failing tests**

File: `video-meeting/tests/test_templates.py`

```python
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from templates import (  # noqa: E402
    DEFAULT_XLSX,
    discover_templates,
    find_layout_by_name,
    resolve_template,
    slides_layouts,
    xlsx_style,
)


class _Layout:
    def __init__(self, name):
        self.name = name


class Discover(unittest.TestCase):
    def test_lists_dirs_sorted_ignores_files(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "client"))
            os.mkdir(os.path.join(d, "executive"))
            open(os.path.join(d, "notes.txt"), "w").close()
            self.assertEqual(discover_templates(d), ["client", "executive"])

    def test_missing_root_is_empty(self):
        self.assertEqual(discover_templates("/no/such/dir/xyz"), [])


class FindLayout(unittest.TestCase):
    def setUp(self):
        self.layouts = [_Layout("Title Slide"), _Layout("Title and Content"),
                        _Layout("Blank")]

    def test_match_by_name_case_insensitive(self):
        lay, fell = find_layout_by_name(self.layouts, "title and content", 0)
        self.assertEqual(lay.name, "Title and Content")
        self.assertFalse(fell)

    def test_fallback_to_index_when_no_name_match(self):
        lay, fell = find_layout_by_name(self.layouts, "Nonexistent", 2)
        self.assertEqual(lay.name, "Blank")
        self.assertTrue(fell)

    def test_fallback_to_first_when_index_out_of_range(self):
        lay, fell = find_layout_by_name(self.layouts, "Nonexistent", 99)
        self.assertEqual(lay.name, "Title Slide")
        self.assertTrue(fell)


class Style(unittest.TestCase):
    def test_xlsx_defaults_when_absent(self):
        self.assertEqual(xlsx_style({}), DEFAULT_XLSX)

    def test_xlsx_override_merges(self):
        merged = xlsx_style({"xlsx": {"header_fill": "000000"}})
        self.assertEqual(merged["header_fill"], "000000")
        self.assertEqual(merged["explicit_fill"], DEFAULT_XLSX["explicit_fill"])

    def test_slides_defaults(self):
        self.assertEqual(slides_layouts({})["title_layout"], "Title Slide")


class Resolve(unittest.TestCase):
    def test_unknown_raises_with_available(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "internal"))
            with self.assertRaises(SystemExit) as ctx:
                resolve_template(d, "nope")
            self.assertIn("internal", str(ctx.exception))

    def test_known_returns_folder_and_data(self):
        with tempfile.TemporaryDirectory() as d:
            folder = os.path.join(d, "internal")
            os.mkdir(folder)
            path, data = resolve_template(d, "internal")
            self.assertEqual(path, folder)
            self.assertIsInstance(data, dict)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd video-meeting && python3 -m unittest tests.test_templates -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'templates'`.

- [ ] **Step 3: Write `scripts/templates.py`**

File: `video-meeting/scripts/templates.py`

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd video-meeting && python3 -m unittest tests.test_templates -v`
Expected: PASS (all tests OK). `load_template_yaml`/`resolve_template` data-parsing paths that need PyYAML are not exercised here (folders have no template.yaml), so this passes without PyYAML installed.

- [ ] **Step 5: Commit**

```bash
git add video-meeting/scripts/templates.py video-meeting/tests/test_templates.py
git commit -m "feat: add presentation template discovery/resolution/style helpers"
```

---

## Task 2: Theme the xlsx renderer (TDD)

**Files:**
- Modify: `video-meeting/scripts/render_tasks_xlsx.py`
- Test: `video-meeting/tests/test_render_tasks_xlsx.py`

- [ ] **Step 1: Write the failing test**

File: `video-meeting/tests/test_render_tasks_xlsx.py`

```python
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

try:
    import openpyxl  # noqa: F401
    import yaml  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "openpyxl + pyyaml required")
class XlsxTheming(unittest.TestCase):
    def _record(self):
        return {
            "action_items": [
                {"title": "Do X", "type": "explicit", "priority": "high"},
                {"title": "Maybe Y", "type": "ai_suggested", "priority": "low"},
            ],
            "decisions": ["Decided A"],
            "open_questions": ["What about B?"],
        }

    def _write(self, d, record, template_dir=None):
        import json
        from render_tasks_xlsx import render
        rec = os.path.join(d, "rec.json")
        with open(rec, "w") as fh:
            json.dump(record, fh)
        out = os.path.join(d, "tasks.xlsx")
        render(rec, out, template_dir)
        return out

    def test_defaults_when_no_template(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as d:
            out = self._write(d, self._record(), None)
            wb = load_workbook(out)
            ws = wb["Action Items"]
            # header fill uses the default 1F4E78 (openpyxl stores ARGB)
            self.assertIn("1F4E78", ws.cell(row=1, column=1).fill.fgColor.rgb)

    def test_template_yaml_overrides_header_fill(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as d:
            tdir = os.path.join(d, "tpl")
            os.mkdir(tdir)
            with open(os.path.join(tdir, "template.yaml"), "w") as fh:
                fh.write("xlsx:\n  header_fill: '00AA00'\n")
            out = self._write(d, self._record(), tdir)
            wb = load_workbook(out)
            ws = wb["Action Items"]
            self.assertIn("00AA00", ws.cell(row=1, column=1).fill.fgColor.rgb)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd video-meeting && VM_TEST_PYTHON=${VM_TEST_PYTHON:-python3} ${VM_TEST_PYTHON:-python3} -m unittest tests.test_render_tasks_xlsx -v`
Expected: FAIL — `ImportError: cannot import name 'render'` (the renderer has no `render()` yet and no `--template-dir`). If render libs are absent the test SKIPS — in that case run with `VM_TEST_PYTHON=~/.pyenv/versions/render-env/bin/python` once render-env has pyyaml (Task 7 adds it; for now install with `~/.pyenv/versions/render-env/bin/python -m pip install pyyaml`).

- [ ] **Step 3: Refactor `render_tasks_xlsx.py` to be style-driven and expose `render()`**

Replace the module-level style constants and the three builder functions, add a `--template-dir` arg, and add a `render()` entry. Concretely:

Replace this block near the top:

```python
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
EXPLICIT_FILL = PatternFill("solid", fgColor="E2EFDA")   # light green
SUGGEST_FILL = PatternFill("solid", fgColor="FFF2CC")    # light amber
WRAP = Alignment(vertical="top", wrap_text=True)
```

with:

```python
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from templates import load_template_yaml, xlsx_style  # noqa: E402

WRAP = Alignment(vertical="top", wrap_text=True)


def build_styles(style):
    """Build openpyxl style objects from an xlsx_style() dict."""
    return {
        "header_fill": PatternFill("solid", fgColor=style["header_fill"]),
        "header_font": Font(bold=True, color=style["header_font_color"],
                            name=style["font_name"]),
        "explicit_fill": PatternFill("solid", fgColor=style["explicit_fill"]),
        "suggested_fill": PatternFill("solid", fgColor=style["suggested_fill"]),
        "body_font": Font(name=style["font_name"]),
    }
```

Change `style_header`, `add_items_sheet`, and `add_list_sheet` to take a `styles` dict. New versions:

```python
def style_header(ws, ncols, styles):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = styles["header_fill"]
        cell.font = styles["header_font"]
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(ncols)}1"


def add_items_sheet(wb, items, styles):
    ws = wb.active
    ws.title = "Action Items"
    for i, (name, width) in enumerate(COLS, 1):
        ws.cell(row=1, column=1 + (i - 1), value=name)
        ws.column_dimensions[get_column_letter(i)].width = width
    style_header(ws, len(COLS), styles)

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
        fill = styles["explicit_fill"] if t.get("type") == "explicit" else styles["suggested_fill"]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=row, column=c, value=v)
            cell.fill = fill
            cell.alignment = WRAP
            cell.font = styles["body_font"]
        row += 1
    if row == 2:
        ws.cell(row=2, column=1, value="(no action items)")


def add_list_sheet(wb, title, values, styles):
    ws = wb.create_sheet(title)
    ws.cell(row=1, column=1, value=title)
    ws.column_dimensions["A"].width = 90
    style_header(ws, 1, styles)
    if values:
        for i, v in enumerate(values, start=2):
            cell = ws.cell(row=i, column=1, value=v)
            cell.alignment = WRAP
            cell.font = styles["body_font"]
    else:
        ws.cell(row=2, column=1, value=f"(no {title.lower()})")
```

Add a `render()` helper and rewrite `main()` to use it:

```python
def render(record_path, out_path, template_dir=None):
    with open(record_path, "r", encoding="utf-8") as fh:
        record = json.load(fh)
    data = load_template_yaml(template_dir) if template_dir else {}
    styles = build_styles(xlsx_style(data))

    wb = Workbook()
    add_items_sheet(wb, record.get("action_items", []), styles)
    add_list_sheet(wb, "Decisions", record.get("decisions", []), styles)
    add_list_sheet(wb, "Open Questions", record.get("open_questions", []), styles)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    wb.save(out_path)
    return len(record.get("action_items", []))


def main():
    ap = argparse.ArgumentParser(description="Render tasks.xlsx from the meeting record.")
    ap.add_argument("--record", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--template-dir", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.record):
        sys.exit(f"record not found: {args.record}")
    n = render(args.record, args.out, args.template_dir)
    sys.stderr.write(f"  tasks.xlsx: {n} action items -> {args.out}\n")


if __name__ == "__main__":
    main()
```

Keep the existing `COLS` constant as-is. Ensure `import os`, `import sys`, `import json`, `import argparse` remain at the top (they already exist).

- [ ] **Step 4: Run the test to verify it passes**

Run (with a render-env that has pyyaml — see Step 2 note):
`cd video-meeting && VM_TEST_PYTHON=~/.pyenv/versions/render-env/bin/python ~/.pyenv/versions/render-env/bin/python -m unittest tests.test_render_tasks_xlsx -v`
Expected: PASS (2 tests). Without render libs it SKIPS — acceptable, but verify on a render-env before committing.

- [ ] **Step 5: Commit**

```bash
git add video-meeting/scripts/render_tasks_xlsx.py video-meeting/tests/test_render_tasks_xlsx.py
git commit -m "feat: theme tasks.xlsx from template.yaml xlsx style block"
```

---

## Task 3: Theme the slides renderer (TDD)

**Files:**
- Modify: `video-meeting/scripts/render_slides.py`
- Test: `video-meeting/tests/test_render_slides.py`

- [ ] **Step 1: Write the failing test**

File: `video-meeting/tests/test_render_slides.py`

```python
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

try:
    from pptx import Presentation
    HAVE_PPTX = True
except ImportError:
    HAVE_PPTX = False


@unittest.skipUnless(HAVE_PPTX, "python-pptx required")
class SlidesTemplate(unittest.TestCase):
    def _record(self):
        return {
            "meeting": {"title": "Sprint", "date": "2026-06-18", "type": "grooming"},
            "summary": {"tldr": "All good", "sections": [
                {"category": "Notes", "points": ["a", "b"]}]},
            "action_items": [{"title": "Do X", "type": "explicit", "assignee": "Al"}],
        }

    def _make_base_template(self, d):
        """A template dir whose slides.pptx is the default python-pptx deck
        (which DOES contain 'Title Slide' and 'Title and Content' layouts)."""
        tdir = os.path.join(d, "tpl")
        os.mkdir(tdir)
        Presentation().save(os.path.join(tdir, "slides.pptx"))
        return tdir

    def test_renders_from_base_template(self):
        import json
        from render_slides import render
        with tempfile.TemporaryDirectory() as d:
            tdir = self._make_base_template(d)
            rec = os.path.join(d, "rec.json")
            with open(rec, "w") as fh:
                json.dump(self._record(), fh)
            out = os.path.join(d, "slides.pptx")
            render(rec, out, ["pptx"], "soffice", tdir)
            self.assertTrue(os.path.isfile(out))
            self.assertGreater(len(Presentation(out).slides._sldIdLst), 0)

    def test_no_template_dir_uses_default_deck(self):
        import json
        from render_slides import render
        with tempfile.TemporaryDirectory() as d:
            rec = os.path.join(d, "rec.json")
            with open(rec, "w") as fh:
                json.dump(self._record(), fh)
            out = os.path.join(d, "slides.pptx")
            render(rec, out, ["pptx"], "soffice", None)
            self.assertTrue(os.path.isfile(out))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd video-meeting && ~/.pyenv/versions/render-env/bin/python -m unittest tests.test_render_slides -v`
Expected: FAIL — `ImportError: cannot import name 'render'`.

- [ ] **Step 3: Update `render_slides.py`**

Add the import and template-aware layout resolution, and expose `render()`.

After `from pptx.util import Pt`, add:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from templates import find_layout_by_name, load_template_yaml, slides_layouts  # noqa: E402
```

Change `add_title_slide` and `add_bullets_slide` to take an explicit layout:

```python
def add_title_slide(prs, layout, title, subtitle):
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = title
    if slide.placeholders and len(slide.placeholders) > 1:
        slide.placeholders[1].text = subtitle


def add_bullets_slide(prs, layout, title, bullets):
    """bullets: list of (text, level)."""
    slide = prs.slides.add_slide(layout)
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
```

Change `build()` to resolve layouts once from the template and pass them down:

```python
def build(prs, record, layout_cfg):
    title_layout, _ = find_layout_by_name(
        prs.slide_layouts, layout_cfg["title_layout"], 0)
    content_layout, _ = find_layout_by_name(
        prs.slide_layouts, layout_cfg["content_layout"], 1)

    m = record.get("meeting", {})
    title = m.get("title", "Meeting")
    sub_bits = [b for b in (m.get("date"), (m.get("type") or "").title()) if b]
    add_title_slide(prs, title_layout, title, "  ·  ".join(sub_bits))

    tldr = record.get("summary", {}).get("tldr", "").strip()
    if tldr:
        add_bullets_slide(prs, content_layout, "Overview", [(tldr, 0)])

    for sec in record.get("summary", {}).get("sections", []):
        cat = sec.get("category", "Notes")
        bullets = [(p, 0) for p in sec.get("points", [])]
        for stitle, sb in chunked(cat, bullets):
            add_bullets_slide(prs, content_layout, stitle, sb)

    items = record.get("action_items", [])
    explicit = [item_line(t) for t in items if t.get("type") == "explicit"]
    suggested = [item_line(t) for t in items if t.get("type") == "ai_suggested"]
    for stitle, sb in chunked("Action Items", [(x, 0) for x in explicit]):
        add_bullets_slide(prs, content_layout, stitle, sb or [("(none)", 0)])
    for stitle, sb in chunked("Suggested (AI)", [(x, 0) for x in suggested]):
        add_bullets_slide(prs, content_layout, stitle, sb or [("(none)", 0)])
```

Add a `render()` and rewrite `main()` to use it and accept `--template-dir`:

```python
def render(record_path, out_pptx, formats, libreoffice, template_dir=None):
    with open(record_path, "r", encoding="utf-8") as fh:
        record = json.load(fh)

    data = load_template_yaml(template_dir) if template_dir else {}
    base = os.path.join(template_dir, "slides.pptx") if template_dir else None
    prs = Presentation(base) if base and os.path.isfile(base) else Presentation()

    build(prs, record, slides_layouts(data))
    os.makedirs(os.path.dirname(os.path.abspath(out_pptx)) or ".", exist_ok=True)
    prs.save(out_pptx)
    sys.stderr.write(f"  slides.pptx: {len(prs.slides._sldIdLst)} slides -> {out_pptx}\n")

    if "odp" in formats:
        outdir = os.path.dirname(os.path.abspath(out_pptx)) or "."
        odp = convert_to(libreoffice, "odp", out_pptx, outdir)
        if odp:
            sys.stderr.write(f"  slides.odp -> {odp}\n")


def main():
    ap = argparse.ArgumentParser(description="Render slides from the meeting record.")
    ap.add_argument("--record", required=True)
    ap.add_argument("--out-pptx", required=True)
    ap.add_argument("--formats", nargs="*", default=["pptx", "odp"])
    ap.add_argument("--libreoffice", default="soffice")
    ap.add_argument("--template-dir", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.record):
        sys.exit(f"record not found: {args.record}")
    render(args.record, args.out_pptx, args.formats, args.libreoffice, args.template_dir)


if __name__ == "__main__":
    main()
```

Keep `chunked`, `item_line`, `convert_to`, `MAX_BULLETS` unchanged.

- [ ] **Step 4: Run to verify it passes**

Run: `cd video-meeting && ~/.pyenv/versions/render-env/bin/python -m unittest tests.test_render_slides -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add video-meeting/scripts/render_slides.py video-meeting/tests/test_render_slides.py
git commit -m "feat: render slides from a base template deck with layout-by-name"
```

---

## Task 4: Theme the report renderer (TDD)

**Files:**
- Modify: `video-meeting/scripts/render_report.py`
- Test: `video-meeting/tests/test_render_report.py`

- [ ] **Step 1: Write the failing test**

File: `video-meeting/tests/test_render_report.py`

```python
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

try:
    from docx import Document
    HAVE_DOCX = True
except ImportError:
    HAVE_DOCX = False


@unittest.skipUnless(HAVE_DOCX, "python-docx required")
class ReportTemplate(unittest.TestCase):
    def _record(self):
        return {
            "meeting": {"title": "Sprint", "date": "2026-06-18", "type": "grooming"},
            "summary": {"tldr": "All good", "sections": [
                {"category": "Notes", "points": ["a"]}]},
            "action_items": [{"title": "Do X", "type": "explicit"}],
            "decisions": ["Decided A"],
        }

    def _render(self, d, template_dir):
        import json
        from render_report import render
        rec = os.path.join(d, "rec.json")
        with open(rec, "w") as fh:
            json.dump(self._record(), fh)
        out_pdf = os.path.join(d, "report.pdf")
        # keep_docx=True, libreoffice may be absent -> PDF step warns, docx stays
        render(rec, out_pdf, "soffice", True, template_dir)
        return os.path.splitext(out_pdf)[0] + ".docx"

    def test_renders_from_base_template(self):
        with tempfile.TemporaryDirectory() as d:
            tdir = os.path.join(d, "tpl")
            os.mkdir(tdir)
            Document().save(os.path.join(tdir, "report.docx"))
            docx = self._render(d, tdir)
            self.assertTrue(os.path.isfile(docx))
            text = "\n".join(p.text for p in Document(docx).paragraphs)
            self.assertIn("Sprint", text)

    def test_no_template_dir_uses_default_doc(self):
        with tempfile.TemporaryDirectory() as d:
            docx = self._render(d, None)
            self.assertTrue(os.path.isfile(docx))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd video-meeting && ~/.pyenv/versions/render-env/bin/python -m unittest tests.test_render_report -v`
Expected: FAIL — `ImportError: cannot import name 'render'`.

- [ ] **Step 3: Update `render_report.py`**

After `from docx.shared import Pt`, add:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from templates import load_template_yaml  # noqa: E402
```

Add a small style-safe helper and a `render()`; rewrite `main()` to use `render()` and accept `--template-dir`. The `build()` function is unchanged (it already uses built-in style names `Heading`, `List Bullet`, `Table Grid`, which exist in default and corporate templates). Replace the document-creation portion of `main()`:

```python
def render(record_path, out_pdf, libreoffice, keep_docx=True, template_dir=None):
    with open(record_path, "r", encoding="utf-8") as fh:
        record = json.load(fh)

    base = os.path.join(template_dir, "report.docx") if template_dir else None
    if base and os.path.isfile(base):
        doc = Document(base)
        _load_template_yaml_warn_if_missing_styles(doc, template_dir)
    else:
        doc = Document()
        style = doc.styles["Normal"]
        style.font.name, style.font.size = "Calibri", Pt(11)

    build(doc, record)

    outdir = os.path.dirname(os.path.abspath(out_pdf)) or "."
    os.makedirs(outdir, exist_ok=True)
    docx_path = os.path.splitext(os.path.abspath(out_pdf))[0] + ".docx"
    doc.save(docx_path)
    sys.stderr.write(f"  report.docx -> {docx_path}\n")

    cmd = [libreoffice, "--headless", "--convert-to", "pdf",
           "--outdir", outdir, docx_path]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    pdf_out = os.path.splitext(docx_path)[0] + ".pdf"
    if p.returncode != 0 or not os.path.isfile(pdf_out):
        sys.stderr.write(f"  warn: PDF conversion failed: {p.stderr.strip()}\n")
        sys.stderr.write("  (the .docx is still available; install LibreOffice for PDF)\n")
    else:
        sys.stderr.write(f"  report.pdf -> {pdf_out}\n")

    if not keep_docx and os.path.isfile(pdf_out):
        os.remove(docx_path)


def _load_template_yaml_warn_if_missing_styles(doc, template_dir):
    """Reserved hook: read template.yaml (for future report options) and warn if
    expected built-in styles are absent from a drop-in document."""
    load_template_yaml(template_dir)  # currently no report-specific keys
    have = {s.name for s in doc.styles}
    for needed in ("Heading 1", "Heading 2", "List Bullet", "Table Grid"):
        if needed not in have:
            sys.stderr.write(
                f"  warn: template report.docx lacks style {needed!r}; "
                "falling back to defaults\n")


def main():
    ap = argparse.ArgumentParser(description="Render a PDF report from the meeting record.")
    ap.add_argument("--record", required=True)
    ap.add_argument("--out-pdf", required=True)
    ap.add_argument("--libreoffice", default="soffice")
    ap.add_argument("--template-dir", default=None)
    ap.add_argument("--no-keep-docx", dest="keep_docx", action="store_false")
    ap.set_defaults(keep_docx=True)
    args = ap.parse_args()

    if not os.path.isfile(args.record):
        sys.exit(f"record not found: {args.record}")
    render(args.record, args.out_pdf, args.libreoffice, args.keep_docx, args.template_dir)


if __name__ == "__main__":
    main()
```

Keep `fmt_duration`, `add_items_table`, and `build` unchanged.

Note on `build()` and missing styles: `doc.add_heading`/`doc.add_paragraph(style=...)` raise `KeyError` only if the style is truly absent. Default and the generated starters include them; `_load_template_yaml_warn_if_missing_styles` warns up front for drop-ins. Making `build` itself fully style-tolerant is out of scope for the starters; the warning gives a clear signal.

- [ ] **Step 4: Run to verify it passes**

Run: `cd video-meeting && ~/.pyenv/versions/render-env/bin/python -m unittest tests.test_render_report -v`
Expected: PASS (2 tests). (PDF conversion may warn if LibreOffice is absent; the test only checks the `.docx`.)

- [ ] **Step 5: Commit**

```bash
git add video-meeting/scripts/render_report.py video-meeting/tests/test_render_report.py
git commit -m "feat: render report from a base template document"
```

---

## Task 5: Starter-template generator + generated starters

**Files:**
- Create: `video-meeting/scripts/build_starter_templates.py`
- Test: `video-meeting/tests/test_build_starter_templates.py`
- Generated (committed): `video-meeting/templates/presentation/{executive,client,internal}/{slides.pptx,report.docx,template.yaml,logo.png}`

- [ ] **Step 1: Write the generator**

File: `video-meeting/scripts/build_starter_templates.py`

```python
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
```

- [ ] **Step 2: Write a smoke test**

File: `video-meeting/tests/test_build_starter_templates.py`

```python
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

try:
    import pptx  # noqa: F401
    import docx  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "python-pptx + python-docx required")
class BuildStarters(unittest.TestCase):
    def test_builds_three_templates(self):
        from build_starter_templates import build_all, STARTERS
        with tempfile.TemporaryDirectory() as d:
            build_all(d)
            base = os.path.join(d, "templates", "presentation")
            for key in STARTERS:
                folder = os.path.join(base, key)
                for f in ("slides.pptx", "report.docx", "template.yaml", "logo.png"):
                    self.assertTrue(os.path.isfile(os.path.join(folder, f)),
                                    f"{key}/{f} missing")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the smoke test**

Run: `cd video-meeting && ~/.pyenv/versions/render-env/bin/python -m unittest tests.test_build_starter_templates -v`
Expected: PASS (1 test).

- [ ] **Step 4: Generate the committed starters**

Run: `~/.pyenv/versions/render-env/bin/python video-meeting/scripts/build_starter_templates.py`
Expected: prints "built template: executive/client/internal"; creates the nine asset files under `video-meeting/templates/presentation/`.

- [ ] **Step 5: Commit**

```bash
git add video-meeting/scripts/build_starter_templates.py \
        video-meeting/tests/test_build_starter_templates.py \
        video-meeting/templates/presentation
git commit -m "feat: starter-template generator and generated executive/client/internal templates"
```

---

## Task 6: Wire selection into run.py + config

**Files:**
- Modify: `video-meeting/scripts/run.py`
- Modify: `video-meeting/config.example.yaml`

- [ ] **Step 1: Add the config default**

In `video-meeting/config.example.yaml`, under the `rendering:` block, add a `template` key. Find:

```yaml
rendering:
  slides:
```

and insert immediately after the `rendering:` line:

```yaml
  # Which presentation template to use (folder under templates/presentation/).
  # Pick per audience: executive | client | internal (or your own folder).
  template: "internal"
```

- [ ] **Step 2: Add the `--template` flag and thread `--template-dir`**

In `video-meeting/scripts/run.py`:

a) Near the other imports (after `from config_get import load_config, get`), add:

```python
from templates import templates_root, resolve_template  # noqa: E402
```

b) Add the CLI flag next to `--meeting-type`:

```python
    ap.add_argument("--template", default=None)
```

c) After `mtype` is resolved (the lines that compute `mtype`), resolve the template once:

```python
    tname = args.template or get(cfg, "rendering.template", "internal")
    template_dir, _ = resolve_template(templates_root(ROOT), tname)
```

(`resolve_template` raises `SystemExit` with the available list if the name is unknown — fail fast before any long stage.)

d) In the "9/9 Render artifacts" section, add `"--template-dir", template_dir` to each of the three render stages. The xlsx stage becomes:

```python
        run_stage([rpy, script("render_tasks_xlsx.py"),
                   "--record", P("meeting_record.json"), "--out", P("tasks.xlsx"),
                   "--template-dir", template_dir])
```

the slides stage:

```python
        run_stage([rpy, script("render_slides.py"),
                   "--record", P("meeting_record.json"), "--out-pptx", P("slides.pptx"),
                   "--formats", *formats, "--libreoffice", soffice,
                   "--template-dir", template_dir])
```

the report stage:

```python
        run_stage([rpy, script("render_report.py"),
                   "--record", P("meeting_record.json"), "--out-pdf", P("report.pdf"),
                   "--libreoffice", soffice, "--template-dir", template_dir])
```

(`render_email.py` is unchanged — no `--template-dir`.)

- [ ] **Step 3: Verify run.py parses and resolves a template**

Run:
```bash
cd video-meeting && python3 -c "
import sys; sys.path.insert(0, 'scripts')
from templates import templates_root, resolve_template
root = templates_root('.')
print('available:', __import__('templates').discover_templates(root))
folder, data = resolve_template(root, 'internal')
print('resolved internal ->', folder)
"
```
Expected: lists `['client', 'executive', 'internal']` and prints the resolved `internal` path. (This exercises the exact resolution code path run.py uses; a full `run.py` invocation needs a video + GPU and is covered by manual E2E.)

Also verify the flag exists: `cd video-meeting && python3 scripts/run.py --help | grep -- --template`
Expected: shows `--template`.

- [ ] **Step 4: Commit**

```bash
git add video-meeting/scripts/run.py video-meeting/config.example.yaml
git commit -m "feat: select presentation template via --template / rendering.template"
```

---

## Task 7: render-env dependency (pyyaml) + preflight validation

**Files:**
- Modify: `video-meeting/install.sh`
- Modify: `video-meeting/scripts/preflight.py`
- Modify: `video-meeting/config.example.yaml` (render-env deps comment)
- Test: `video-meeting/tests/test_preflight_template.py`

- [ ] **Step 1: Add pyyaml to the render-env install**

In `video-meeting/install.sh`, the render-env install block (around line 187-190) reads:

```bash
  log "render-env deps (document renderers)"
  "$rpy" -m pip install -q --upgrade pip
  "$rpy" -m pip install -q openpyxl python-pptx python-docx
  ok "openpyxl + python-pptx + python-docx installed"
```

Change the two affected lines to add `pyyaml`:

```bash
  "$rpy" -m pip install -q openpyxl python-pptx python-docx pyyaml
  ok "openpyxl + python-pptx + python-docx + pyyaml installed"
```

Also update the comment in `config.example.yaml` near line 65-66 that lists render deps to include `pyyaml`:

```yaml
  # Lightweight venv for the document renderers (no GPU): openpyxl, python-pptx,
  # python-docx, pyyaml. Kept separate so heavy audio deps and render deps don't mix.
```

- [ ] **Step 2: Add yaml to the render-env preflight module check**

In `video-meeting/scripts/preflight.py`, `check_render` (lines 94-100) currently reads:

```python
def check_render(cfg):
    py = get(cfg, "env.render.python")
    if not py or not os.path.isfile(py):
        return record(FAIL, "render-env", f"interpreter missing: {py}")
    for mod in ("openpyxl", "pptx", "docx"):
        ok, detail = venv_import(py, mod)
        record(OK if ok else FAIL, f"render-env: {mod}", detail if not ok else py)
```

Change only the module tuple to add `"yaml"`:

```python
    for mod in ("openpyxl", "pptx", "docx", "yaml"):
```

- [ ] **Step 3: Write the failing preflight test**

File: `video-meeting/tests/test_preflight_template.py`

```python
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import preflight  # noqa: E402


class TemplateCheck(unittest.TestCase):
    def test_ok_when_template_exists(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "templates", "presentation", "internal")
            os.makedirs(folder)
            open(os.path.join(folder, "slides.pptx"), "w").close()
            open(os.path.join(folder, "report.docx"), "w").close()
            self.assertTrue(preflight.check_template(root, "internal"))

    def test_fail_when_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "templates", "presentation", "internal"))
            self.assertFalse(preflight.check_template(root, "missing"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run to verify it fails**

Run: `cd video-meeting && python3 -m unittest tests.test_preflight_template -v`
Expected: FAIL — `AttributeError: module 'preflight' has no attribute 'check_template'`.

- [ ] **Step 5: Add `check_template` to preflight.py and call it from `main`**

Add this function (near the other `check_*` functions), using the existing `record`, `OK`, `FAIL` helpers and `templates.py`:

```python
def check_template(skill_root, name):
    """Validate the selected presentation template exists with its base files."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from templates import discover_templates, templates_root
    root = templates_root(skill_root)
    folder = os.path.join(root, name)
    if not os.path.isdir(folder):
        avail = ", ".join(discover_templates(root)) or "(none)"
        record(FAIL, "template", f"unknown {name!r}; available: {avail}")
        return False
    missing = [f for f in ("slides.pptx", "report.docx")
               if not os.path.isfile(os.path.join(folder, f))]
    if missing:
        record(FAIL, "template",
               f"{name}: missing {', '.join(missing)} (run build_starter_templates.py)")
        return False
    record(OK, "template", folder)
    return True
```

In preflight's `main()` (lines 252-257), the checks run as:

```python
    check_ffmpeg(cfg)
    check_whisper(cfg)
    check_pyannote(cfg)
    check_render(cfg)
    check_libreoffice(cfg)
```

Add the template check immediately after `check_render(cfg)`:

```python
    check_render(cfg)
    skill_root = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    check_template(skill_root, get(cfg, "rendering.template", "internal"))
    check_libreoffice(cfg)
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd video-meeting && python3 -m unittest tests.test_preflight_template -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add video-meeting/install.sh video-meeting/scripts/preflight.py \
        video-meeting/config.example.yaml video-meeting/tests/test_preflight_template.py
git commit -m "feat: add pyyaml to render-env and validate template in preflight"
```

---

## Task 8: Documentation (SKILL.md, templates README)

**Files:**
- Modify: `video-meeting/SKILL.md`
- Create: `video-meeting/templates/presentation/README.md`

- [ ] **Step 1: Document templates in SKILL.md**

In `video-meeting/SKILL.md`, locate the workflow section that mentions choosing a meeting type / rendering artifacts. Add a short step describing template selection. Insert this paragraph where the rendering step is described (search for "render" or "slides" in SKILL.md and add nearby):

```markdown
### Choosing a presentation template

Artifacts (slides, report, tasks.xlsx) are themed by a **template** chosen for
the audience. Pass `--template <name>` to `run.py`, or set `rendering.template`
in `config.yaml`. Built-in templates: `executive` (leadership), `client`
(client-facing), `internal` (default). List options by looking under
`templates/presentation/`. To use an organization's own branding, replace
`slides.pptx`/`report.docx` in a template folder (or add a new folder) — see
`templates/presentation/README.md`.
```

- [ ] **Step 2: Write the templates README**

File: `video-meeting/templates/presentation/README.md`

```markdown
# Presentation templates

Each subfolder is a **template** selecting the visual look of the generated
slides, report, and tasks spreadsheet for a given audience. Content is identical
across templates — only branding/design changes.

## Layout

```
<name>/
  slides.pptx     # base deck the slide renderer opens and fills in
  report.docx     # base document the report renderer opens and fills in
  template.yaml   # metadata + slide-layout names + xlsx style block
  logo.png        # optional; used by the xlsx title banner
```

## Selecting one

- Per run: `run.py --template <name>`
- Default: `rendering.template` in `config.yaml`

## Built-in starters

- `executive` — navy, serif headings (leadership readouts)
- `client` — teal, sans (client-facing)
- `internal` — minimal grey (default)

Regenerate them with:

```
$RENDER_PY scripts/build_starter_templates.py
```

## Using your organization's template

Drop your official PowerPoint/Word file in as `slides.pptx` / `report.docx`
inside a template folder (existing or new). The renderers reuse the file's
theme, master slides, fonts, header/footer, and embedded logo. They place
content using the standard "Title Slide" / "Title and Content" slide layouts and
the built-in Word styles (`Title`, `Heading 1/2`, `Normal`, `Table Grid`); if a
layout or style is missing, they fall back and print a warning. Adjust
`template.yaml` (especially the `xlsx:` colors and `accent`) to match.
```

- [ ] **Step 3: Commit**

```bash
git add video-meeting/SKILL.md video-meeting/templates/presentation/README.md
git commit -m "docs: document presentation template selection and authoring"
```

---

## Task 9: Repackage the skill bundle + full test run

**Files:**
- Regenerate: `video-meeting.skill`

- [ ] **Step 1: Run the full test suite**

Run with a render-env that has the render libs + pyyaml:
```bash
cd video-meeting && VM_TEST_PYTHON=~/.pyenv/versions/render-env/bin/python bash tests/run_tests.sh
```
Expected: all tests pass; renderer/template tests run (not skipped) under render-env. Also run the stdlib-only pass: `cd video-meeting && python3 -m unittest discover -s tests -p 'test_*.py' -v` (renderer tests skip if libs absent, template/preflight tests run).

- [ ] **Step 2: Rebuild the bundle**

Run: `bash package.sh video-meeting`
Expected: produces `video-meeting.skill` including `templates/presentation/` (starters) and the new scripts; excludes `config.yaml`, tokens, `__pycache__`. Confirm exactly one SKILL.md in the tree (package.sh validates this).

- [ ] **Step 3: Commit**

```bash
git add video-meeting.skill
git commit -m "chore: repackage skill bundle with presentation templates"
```

---

## Manual verification (after merge, needs a real meeting + render-env)

Not automatable here; do once before relying on it:
- `python3 video-meeting/scripts/run.py --video <meeting.mp4> --title T --meeting-type catchup --template executive` → open `slides.pptx`, `report.pdf`, `tasks.xlsx`; confirm the navy/serif executive look and that content is intact.
- Repeat with `--template client` and `--template internal`; confirm the look changes and nothing breaks.
- Drop a real corporate `.pptx`/`.docx` into a new folder under `templates/presentation/mycorp/`, run `--template mycorp`, and confirm branding is inherited (and any missing-style warnings are benign).
