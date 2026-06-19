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

- `executive` — navy (`1A2238`) + gold (`B08D57`), Cambria headings, with logo
  and the corporate report header/footer (leadership readouts)
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
