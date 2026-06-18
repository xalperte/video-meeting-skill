# Selectable Presentation Templates — Design

**Date:** 2026-06-18
**Status:** Approved (design), pending implementation plan

## Purpose

The generated slides (`slides.pptx`/`.odp`), report (`report.pdf`/`.docx`), and
task sheet (`tasks.xlsx`) currently use library defaults (`Presentation()`,
`Document()`, hardcoded openpyxl colors), so they look generic. This adds
**selectable visual templates** so the same meeting can be rendered in a look
appropriate to its audience (e.g. leadership, client, internal team), including
the ability to drop in an organization's **official PowerPoint/Word template**.

Templates are **visual-only**: they change branding/look, never the content.
What gets extracted and shown is already governed by `meeting_type` and the
prompt templates; templates must not duplicate that.

## Scope

In scope:
- Theming for **slides**, **report**, and **xlsx**.
- A named-template registry, selection via CLI flag + config default, and
  preflight validation.
- Shipped starter templates plus documented drop-in replacement.

Out of scope (YAGNI):
- `email.md` (plain markdown) — unchanged.
- Any content/section changes per template (visual-only, per decision).
- A template authoring GUI.

## A template is one folder per audience

```
templates/presentation/<name>/
  slides.pptx     # base deck — opened and filled in
  report.docx     # base document — opened and filled in
  template.yaml   # metadata + contract + xlsx style block
  logo.png        # optional; used by the xlsx title banner
```

`<name>` is the selector (kebab/lower-case folder name). The look for slides and
report lives **inside** the base Office files (theme, slide master, named styles,
header/footer, embedded logo). This is what lets a real corporate `.pptx`/`.docx`
be dropped in unchanged.

### template.yaml

```yaml
name: "Executive"                 # display name
description: "Navy, serif headings — leadership readouts"
accent: "1F3864"                  # hex (no #); used only for elements we DRAW
slides:
  title_layout: "Title Slide"     # resolved by name; falls back to index then first
  content_layout: "Title and Content"
xlsx:
  header_fill: "1F3864"
  header_font_color: "FFFFFF"
  explicit_fill: "E2EFDA"
  suggested_fill: "FFF2CC"
  font_name: "Calibri"
  banner: true                    # draw a title row with logo.png if present
```

All `template.yaml` fields are optional; missing fields fall back to current
hardcoded defaults so a minimal/corporate folder still renders.

## Per-artifact theming mechanism

### Slides (`render_slides.py`, python-pptx)
- Open `Presentation(<dir>/slides.pptx)` instead of `Presentation()`.
- Resolve layouts **by name** from `template.yaml.slides` (`title_layout`,
  `content_layout`), searching `prs.slide_layouts` case-insensitively. Fallback
  order: configured name → index 0/1 → first available layout. Emit a warning
  when falling back.
- Theme fonts/colors are inherited from the base deck's master; the renderer
  does not re-apply fonts. `accent` is used only for elements the renderer draws
  itself (none required for slides initially; reserved).
- `.odp` conversion via LibreOffice is unchanged (preserves theme).

### Report (`render_report.py`, python-docx)
- Open `Document(<dir>/report.docx)` instead of `Document()`.
- Use Word **built-in style names** that exist in every template: `Title`,
  `Heading 1`, `Heading 2`, `Normal`, and a grid table style (`Table Grid`).
  When applying a style, if it's absent, fall back to default formatting +
  warning.
- Header/footer and logo come from the base document; the renderer does not add
  them. `.pdf` conversion via LibreOffice is unchanged.

### Excel (`render_tasks_xlsx.py`, openpyxl)
- Still built dynamically (sheets per category, rows injected).
- The hardcoded constants (`HEADER_FILL`, `HEADER_FONT`, `EXPLICIT_FILL`,
  `SUGGEST_FILL`, font) are replaced by values read from `template.yaml.xlsx`,
  with the current values as defaults.
- If `xlsx.banner` is true and `logo.png` exists, insert a title banner row with
  the logo at the top of the first sheet; otherwise omit (no layout shift).

## Selection (mirrors `--meeting-type`)

- New `--template <name>` flag on `run.py`.
- Default from a new `rendering.template` key in `config.yaml` (falls back to
  `"internal"` if unset).
- Discovery: scan `templates/presentation/` for subfolders. An unknown name is a
  hard error that lists the available templates.
- `run.py` resolves the chosen folder to an absolute path and passes
  `--template-dir <path>` to `render_slides.py`, `render_report.py`, and
  `render_tasks_xlsx.py`.
- `preflight.py` validates that the selected template folder exists (and that
  `slides.pptx`/`report.docx` are present) before any long job, and offers a
  clear message otherwise.
- SKILL.md workflow gains a step: ask which audience/template to use, defaulting
  to `rendering.template`.

## Starter templates (shipped, replaceable)

`scripts/build_starter_templates.py` (run in render-env) generates the starter
folders from a shared palette table, producing real, editable `.pptx`/`.docx`
base files plus their `template.yaml` and copying a placeholder `logo.png`. It is
idempotent and re-runnable; its output is committed so a bare checkout has
working templates.

Starters:
- **executive** — navy (`1F3864`), serif headings, formal.
- **client** — teal (`117A65`), sans, logo-forward.
- **internal** — minimal grey, compact (the default).

README documents: "to use your organization's template, replace `slides.pptx`
and `report.docx` in a template folder (or add a new folder) and adjust
`template.yaml`."

Note: programmatically generated starters are clean and professional but not
designer-bespoke; the drop-in mechanism is the path to fully branded output.

## Module structure

- New `scripts/templates.py` — pure helpers: `discover_templates(root)`,
  `resolve_template(root, name)` (returns folder path + parsed `template.yaml`),
  `load_template_yaml(path)`, and `find_layout_by_name(prs, name, fallback_idx)`.
  `load_template_yaml` parses with **PyYAML via a lazy import**, mirroring the
  pattern in `config_get.py` (clear error if missing) and applying the documented
  defaults for absent keys. `discover_templates`/`find_layout_by_name` are pure
  stdlib and unit-testable without Office libs or PyYAML.

### Dependency note

The renderers run in **render-env**, which currently has openpyxl/python-pptx/
python-docx but not PyYAML. Because the renderers now read `template.yaml`,
**add `pyyaml` to render-env** (in `install.sh`'s render-env install step and in
the render-env dependency list in `config.example.yaml`'s comments). PyYAML is a
pure-Python wheel, so this does not affect the GPU/audio envs. `templates.py`
lazy-imports it and emits the same install hint `config_get.py` uses if absent.
- `render_slides.py`, `render_report.py`, `render_tasks_xlsx.py` gain a
  `--template-dir` argument and delegate look decisions to `scripts/templates.py`
  + `template.yaml`.
- `run.py` resolves the template and threads `--template-dir` through; reads
  `rendering.template`.
- `preflight.py` adds a template-existence check.

## Error handling

- Unknown `--template` → exit with the list of available templates.
- Missing `slides.pptx`/`report.docx` in the chosen folder → preflight error
  (caught early), with guidance to run `build_starter_templates.py`.
- Missing layout/style/`template.yaml` key at render time → fall back to defaults
  and warn on stderr; never crash a render.
- Missing/instructed `logo.png` absent → skip the banner silently.

## Testing

Stdlib `unittest` (matches the repo; renderers skip when their Office lib is
absent):
- `tests/test_templates.py` — `discover_templates` lists folders; `resolve_template`
  returns path + parsed yaml; unknown name raises with available list;
  `load_template_yaml` applies defaults for missing keys; `find_layout_by_name`
  returns by name, then index, then first (using a stub layout list).
- `render_slides`/`render_report` tests — given a generated starter folder as a
  fixture, produce a non-empty deck/doc; assert no crash when a configured layout
  name is absent (fallback path). Skip if python-pptx/python-docx missing.
- `render_tasks_xlsx` test — header/row fills reflect `template.yaml.xlsx`
  values; defaults used when the block is absent. Skip if openpyxl missing.
- A `build_starter_templates.py` smoke test (skipped without render libs) that it
  emits the three folders with the expected files.
