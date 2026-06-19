# Executive Template from Corporate Brand + Renderer Hardening — Design

**Date:** 2026-06-18
**Status:** Approved (design), pending implementation plan

## Purpose

Two related goals:

1. **Harden the slides and report renderers** so they tolerate *any* drop-in
   base Office file — including real corporate templates that contain example
   content and lack the exact layouts/styles the renderers assume. Today
   `render_report.py` crashes on a base `.docx` missing `Table Grid`/`List
   Bullet`, and `render_slides.py` crashes on a deck whose layout lacks
   title/body placeholders. This closes the "fall back, never crash" gap the
   templates spec promised but `build()` did not deliver.

2. **Build a real `executive` template from the user's corporate brand.** The
   user supplied `Executive_Template.{docx,pptx,xlsx}`. Their visual identity is
   navy `1A2238` + gold `B08D57`, Cambria headings / Calibri body. Their DOCX
   carries a usable header/footer; their PPTX carries a logo. Their PPTX design,
   however, lives in hand-built example slides (single placeholder-less `DEFAULT`
   layout, default Office theme), which cannot be reliably transplanted into a
   reusable master via python-pptx.

## Decisions (from brainstorming)

- Templates remain **visual-only**; content unchanged.
- Drop-in base files: **clear pre-existing body content, keep branding.** Remove
  pre-existing slides (pptx) / body paragraphs + tables (docx); preserve theme,
  slide master/layouts, Word styles, and headers/footers.
- Executive **PPTX** = a **generated branded master** (navy/gold/Cambria, proper
  layouts) with the user's **extracted logo** — not a copy of their example-slide
  artwork.
- Executive **DOCX** = **converted from the user's actual file** (keep header/
  footer; add missing styles; brand headings; clear example body).
- Executive **XLSX** = themed via `template.yaml` (navy header, gold accent).
- Executive XLSX header fill = **navy `1A2238`** with white font.

## Source inspection (facts the design relies on)

- PPTX: 7 example slides; one layout `DEFAULT` with **zero placeholders**; theme
  = default Office palette. Logo = `ppt/media/image-1-1.png` (title-slide mark,
  repeated on the closing slide).
- DOCX: 28 example paragraphs; styles present include `Title`, `Heading 1/2`,
  `List Paragraph`; **missing** `Table Grid` and `List Bullet`; header =
  `COMPANY NAME\tExecutive Brief`, footer = `Confidential\tPage`.
- XLSX: brand colors navy `1A2238`, gold `B08D57`, body grey `242832`; fonts
  Cambria (headings) / Calibri (body). Not used as a base file (xlsx is themed
  from `template.yaml`).

## Component 1 — Renderer hardening

### `render_slides.py`

- `clear_slides(prs)` — remove every `sldId` from the presentation's slide list
  (XML: drop children of `prs.slides._sldIdLst`), leaving masters/layouts/theme
  intact. Called right after opening a base deck, before `build()`.
- Placeholder-safe content placement:
  - `pick_layout(prs, name, fallback_idx, need_body)` — prefer the named layout;
    if `need_body`, prefer one that has both a title (idx 0) and body (idx 1)
    placeholder; else fall back by index, then first. (Generalizes the existing
    `find_layout_by_name`.)
  - `add_title_slide` / `add_bullets_slide` — if the chosen slide has no title
    placeholder, add a title textbox; if no body placeholder (idx 1), add a body
    textbox and write bullets there. So a `DEFAULT`-only deck renders without
    crashing.
- A single warning per fallback on stderr (no spam).

### `render_report.py`

- `clear_body(doc)` — remove existing body paragraphs and tables (iterate
  `doc.element.body`, drop `w:p`/`w:tbl`, keep the final `w:sectPr`). Headers/
  footers live outside the body and are preserved. Called after opening a base.
- Style-safe helpers used by `build()`:
  - `add_bullet(doc, text)` → try `List Bullet`; except, try `List Paragraph`;
    except, plain paragraph with a literal `• ` prefix.
  - `styled_table(doc, rows, cols)` → create table; try `style = "Table Grid"`;
    on failure, apply simple cell borders via XML and continue.
- `build()` switches its `add_paragraph(style="List Bullet")` and
  `table.style = "Table Grid"` calls to these helpers. One warning per missing
  style.

Both `clear_*` run only when a template base file is actually opened (the
no-template default path is unchanged).

## Component 2 — Executive assets (reproducible)

Commit the user's source + extracted logo so the starter is regenerable:

```
templates/presentation/executive/
  source/Executive_Template.docx   # the user's file (conversion input)
  logo.png                         # extracted ppt/media/image-1-1.png
  slides.pptx                      # generated (committed output)
  report.docx                      # converted from source (committed output)
  template.yaml                    # navy/gold, Cambria
```

`scripts/build_starter_templates.py` is extended:

- `STARTERS["executive"]` palette → `accent: "1A2238"`, `accent2: "B08D57"`,
  `heading_font: "Cambria"`, `body_font: "Calibri"`, plus `logo:
  "source"/extracted` and `report_source: "source/Executive_Template.docx"`.
- `build_slides` for executive:
  - start from default `Presentation()` (its template already provides
    `Title Slide` + `Title and Content` layouts with placeholders),
  - edit the master's **theme part XML**: set the dark/accent scheme to navy +
    gold and the major (heading) font to Cambria,
  - add a navy **title band** rectangle and the **logo** picture to the slide
    master,
  - keep 0 slides; save.
- `build_report` for executive:
  - open `report_source` (the user's docx),
  - `clear_body` it,
  - ensure `Table Grid` + `List Bullet` styles exist (add from python-docx's
    builtin defaults if missing),
  - brand `Title`/`Heading 1/2` (navy color, Cambria font, gold accent),
  - keep header/footer,
  - save as `report.docx`.
  - If `report_source` is absent, fall back to generating a clean branded docx
    (so the generator still works in a bare checkout without the source).
- `build_template_yaml` for executive writes navy header (`1F` → `1A2238`),
  `header_font_color: FFFFFF`, gold `accent`, Cambria/Calibri.

`client` and `internal` starters are unchanged.

## Error handling

- Missing `report_source` → generator logs a note and produces a clean branded
  executive docx (no crash).
- Missing/oversized logo → generator skips the logo placement with a warning.
- Renderer fallbacks (above) never crash on missing layouts/placeholders/styles;
  each emits one stderr warning.
- Theme-XML edit failures (unexpected master structure) → log a warning and keep
  the default theme rather than aborting.

## Testing (stdlib unittest, render-env)

- `render_slides`:
  - base deck seeded with N example slides → after render, output deck contains
    only the generated slides (example slides cleared), no crash.
  - base deck whose only layout has no placeholders → renders (textbox fallback),
    title + a bullet are present.
- `render_report`:
  - base docx missing `Table Grid` and `List Bullet`, with example paragraphs and
    a header → renders without crash; example paragraphs gone; header preserved;
    action-items table and bullets present.
- `build_starter_templates`:
  - executive `template.yaml` → navy `1A2238` header, gold accent, Cambria.
  - executive `report.docx` (built from a tiny fixture source docx) → contains
    `Table Grid` + `List Bullet` styles and preserves the fixture's header text.
  - executive `slides.pptx` → 0 slides; has `Title Slide` + `Title and Content`
    layouts; opens without error.
- All renderer/generator tests skip when python-pptx/python-docx/openpyxl are
  absent (existing convention).

## Scope

- Slides + report hardening; executive assets. `email.md` untouched; xlsx themed
  via `template.yaml` only.
- No change to content, meeting types, or the selection mechanism.
- The user's `.xlsx`/`.pptx` files are a brand/logo source, not shipped as base
  files (only the docx source + extracted logo are committed).
