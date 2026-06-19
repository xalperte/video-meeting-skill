# Frame-description step + upgrade-safe configuration — design

Date: 2026-06-18
Skill: `video-meeting`

## Summary

Add an **opt-in** pipeline step that extracts video frames at user-supplied
timestamps, describes each frame's meaning with a **local Ollama vision model**,
and writes a standalone knowledge pack about the shared visuals:

```
<meeting>/
  frames/slide-0001.png, slide-0002.png, ...
  video-frames-details.json
  video-frames-summary.md
```

The step runs only when the user supplies timestamps (e.g. *"process the
following frames at [10:20, 15:10, 32:30, 46:00, 01:10:23]"*). When absent, the
existing pipeline is completely unchanged.

This work also makes configuration **upgrade-safe**: new keys never break old
`config.yaml` files, a few realistically-tweaked tunables are externalized into
config so upgrades don't clobber them, and there is a non-destructive way to
reconcile an existing config against a newer `config.example.yaml`.

## Goals

- Extract frames at precise timestamps (`mm:ss` and `hh:mm:ss`).
- Describe each frame's content/meaning locally (no data leaves the machine),
  reusing the existing Ollama HTTP client and VRAM-sequencing discipline.
- Produce `video-frames-details.json` (per-slide: timestamp, image link, text)
  and a summarized `video-frames-summary.md`.
- Keep the feature fully isolated/standalone — `meeting_record.json` and all
  existing artifacts are untouched.
- Make upgrades of an already-installed, possibly-customized skill safe:
  preserve `config.yaml` and the registry, surface new keys, and never clobber
  user values.

## Non-goals (YAGNI)

- No folding of frame descriptions into `meeting_record.json`, the PDF report,
  slides, or email (explicitly chosen: standalone only).
- No OCR engine — semantic description via the vision model only.
- No automatic editing/reordering of existing `config.yaml` lines (append-only).
- No new virtualenv — frame extraction is ffmpeg-only; description reuses the
  Ollama HTTP path with the system `python3`.

---

## 1. Trigger and CLI

`run.py` gains a flag:

```
--frames "10:20" "15:10" "32:30" "46:00" "01:10:23"
```

The skill (SKILL.md) documents that when the user names moments in natural
language, Claude maps them to `--frames`. If `--frames` is omitted, the entire
frames block is skipped — no new behavior, no new outputs.

**Timestamp parsing (count the colons):**

- one colon → `mm:ss` → `10:20` = 620 s
- two colons → `hh:mm:ss` → `01:10:23` = 4223 s
- a bare integer → seconds (defensive; not required by the spec)
- more than two colons, non-numeric parts, or negative → hard error with the
  offending token named.

Order is **preserved as given**: the i-th timestamp becomes `slide-000i`
(1-indexed, zero-padded to 4 digits). Timestamps are **not** re-sorted.

---

## 2. New components

Two small, stdlib-first scripts, one tool each (matches existing conventions):

### `scripts/extract_frames.py` (system `python3` + ffmpeg, no GPU)

Like `extract_audio.py`. For each `(slide_id, seconds)`:

```
ffmpeg -y -loglevel error -ss <seconds> -i <video> -frames:v 1 \
       -q:v <quality> frames/slide-NNNN.<ext>
```

- Uses input seeking (`-ss` before `-i`) for speed on long videos.
- `-ss` accepts fractional seconds; we pass the parsed integer/float seconds.
- Output dir `frames/` created if absent.
- Emits a manifest to stdout (JSON), consumed by `describe_frames.py`:

```json
{
  "video": "/abs/path/meeting.mp4",
  "image_format": "png",
  "frames": [
    {"slide": "slide-0001", "timestamp": "10:20", "timestamp_s": 620,
     "image": "frames/slide-0001.png"}
  ]
}
```

`image` paths are stored **relative to the meeting folder** so the JSON/folder
is portable. Internally the script resolves absolute paths for ffmpeg.

Timestamp parsing lives in a tiny pure helper (`parse_timestamp(s) -> float`)
that is unit-tested directly.

### `scripts/describe_frames.py` (system `python3`, stdlib + `ollama_client`)

1. Reads the manifest written by `extract_frames.py` (`--manifest <path>`).
   `run.py` always runs the two scripts as separate stages; `describe_frames.py`
   does not invoke ffmpeg itself.
2. For each frame: base64-encode the image and POST to Ollama `/api/generate`
   with `images:[<b64>]` using the **vision model**; prompt from
   `templates/frame_prompts/describe.md`. Truncate the returned text to
   `frames.describe_max_chars`.
3. Write **`video-frames-details.json`** (schema in §3).
4. Build a markdown digest of all descriptions and run a **second** Ollama call
   with the **text summary model** (prompt `templates/frame_prompts/summary.md`,
   map-reduce reusing `summarize.py`'s chunking helper) → **`video-frames-summary.md`**.

Vision and summary models never co-reside: Ollama `keep_alive: 0s` unloads the
vision model before the summary model loads, so only one model is resident on
the 16 GB GPU at a time.

### `ollama_client.py` — additive change

`build_payload(...)` gains an optional `images=None` parameter; when provided it
sets `payload["images"]`. `generate(...)` forwards an `images` kwarg. Existing
callers (`summarize.py`, `extract_tasks.py`) are unaffected — the parameter
defaults to `None` and the key is omitted when empty.

### Prompt templates (new, isolated from meeting prompts)

- `templates/frame_prompts/describe.md` — per-frame: describe what the slide/
  screen shows and what it means; capture visible text, diagrams, charts; output
  in the meeting output language; no preamble.
- `templates/frame_prompts/summary.md` — overall: synthesize the per-frame
  descriptions into a coherent markdown summary of the shared presentation.

Kept under `frame_prompts/` (not `summary_prompts/`) so slide-description logic
stays separate from meeting summarization, and so `summarize.py`'s
`MEETING_TYPES` set is not touched.

---

## 3. Output schema

`video-frames-details.json` — ordered list of slide records plus light metadata:

```json
{
  "video": "meeting.mp4",
  "vision_model": "chandra-ocr-2",
  "output_language": "English",
  "frames": [
    {
      "slide": "slide-0001",
      "timestamp": "10:20",
      "timestamp_s": 620,
      "image": "frames/slide-0001.png",
      "text": "The slide presents the Q3 architecture migration plan: three
               phases shown as a left-to-right flow ..."
    }
  ]
}
```

- `frames` is a **list** (ordered, renderer-friendly), not a dict keyed by slide.
- `image` is relative to the meeting folder.
- `text` is the truncated vision-model description.

`video-frames-summary.md` — a plain markdown digest (title + synthesized prose/
bullets), suitable to read on its own or drop into other docs.

---

## 4. Pipeline placement & VRAM

The gated frames block runs in the **LLM phase**, after diarization has freed
GPU VRAM, alongside summarize/extract-tasks. Sequence inside the block:

1. `extract_frames.py` (ffmpeg, negligible VRAM)
2. `describe_frames.py` → vision captioning, then text summary

The main numbered stages (audio → record → render) keep their numbering and
ordering; the frames block is inserted as an additional, independent sub-stage
that cannot disturb the existing flow. It is only entered when `--frames` is set.

---

## 5. Config additions

```yaml
ollama:
  summary_max_chunk_chars: 24000          # externalized from summarize.py default
  vision_model: "chandra-ocr-2"            # frame description (vision)

frames:
  image_format: "png"                     # png | jpg
  jpeg_quality: 2                          # ffmpeg -q:v when image_format == jpg
  describe_max_chars: 4000                 # cap per-frame description length
  frames_summary_max_chunk_chars: 24000    # map-reduce threshold for the digest

install:
  # vision model pulled for the optional frame-description step
  ollama_models: ["gemma4:12b", "qwen3.5:9b", "chandra-ocr-2"]
```

All read via `get(cfg, "<path>", DEFAULT)` with the DEFAULT equal to the value
above, so an older `config.yaml` lacking these keys runs on built-in defaults.

`run.py` reads `ollama.summary_max_chunk_chars` and passes it to `summarize.py`
via the existing `--max-chunk-chars` flag (whose script default stays 24000, so
no regression if `run.py` is bypassed).

---

## 6. Upgrade-safe configuration

**Bundle drop-in preserves user state.** `package.sh` already excludes
`config.yaml`, `hf_token`, `*.token`, `__pycache__`, `.DS_Store`. Re-installing
replaces only code (scripts, templates, `config.example.yaml`, SKILL.md). The
user's `config.yaml` and the global registry are never in the bundle, so they
survive.

**New keys never break old configs.** Every new setting is read with a default
equal to its `config.example.yaml` value. Missing-key → built-in default. The
frames feature therefore works on a pre-existing config with zero edits.

**Externalized tunables are now upgrade-safe.** Values users realistically tweak
— `summary_max_chunk_chars` (the `--max-chunk-chars` case) and the new `frames.*`
knobs — live in `config.yaml`, which survives upgrades, instead of being script
defaults that a new bundle would silently revert.

### Config-drift detection + opt-in append

- **`preflight.py`** gains a drift check: walk leaf keys of
  `config.example.yaml`; report any missing from `config.yaml`. Example:

  ```
  ! config.yaml is missing 2 keys added in a newer version:
        ollama.vision_model
        frames.describe_max_chars
    Built-in defaults are in effect. Run: bash install.sh --migrate-config
  ```

  Drift is a **warning**, not a failure — the run proceeds on defaults.

- **`scripts/migrate_config.py`** (called by `install.sh --migrate-config`):
  loads both files, computes leaf keys present in the example but absent in the
  user config, and **appends** them — with their example values and the relevant
  comment lines — to the **end** of `config.yaml` under a dated block:

  ```yaml
  # ----------------------------------------------------------------------------
  # --- added by migrate-config 2026-06-18 (new keys from config.example.yaml) ---
  # ----------------------------------------------------------------------------
  ollama:
    vision_model: "chandra-ocr-2"
  frames:
    image_format: "png"
    ...
  ```

  It **only appends**. It never edits, reorders, or deletes existing lines, so
  customized values (`max_chunk_chars: 100000`, machine paths) are preserved.
  Write is atomic (temp-file + `os.replace`), matching the registry's discipline.
  A backup `config.yaml.bak-<date>` is written before the append.

  Note: appending a top-level key (e.g. `frames:`) is safe (new mapping).
  Appending a nested key under an existing top-level key (e.g. a new
  `ollama.vision_model` when `ollama:` already exists) is emitted as a small
  re-stated block (`ollama:\n  vision_model: ...`). YAML merges duplicate
  top-level mapping keys by last-wins per key, and the loader (`config_get.py`)
  tolerates this; the migrate script documents the appended duplicate-parent
  block so it is human-obvious. If `config_get.py`'s loader does not merge
  duplicate top-level keys, `migrate_config.py` instead performs a structured
  insert under the existing parent (see Risks). The implementation plan will
  verify loader behavior first and choose the safe path.

- **Vision model pull.** `install.sh --all` ensures the vision model is present
  via idempotent `ollama pull`, using the config value if set, else the built-in
  default — so it works even when the user's `install.ollama_models` predates the
  key. The frames stage additionally checks Ollama `/api/tags` up front and, if
  the model is absent, prints the exact `ollama pull <model>` command and exits
  before doing any heavy work (so an opt-in run never dies mid-way).

### Documented upgrade procedure (`references/install.md`)

```bash
# 1. Drop in the new bundle — config.yaml and the registry are preserved.
# 2. Reconcile config and pull the new model:
bash install.sh --check            # reports config drift + what's missing
bash install.sh --migrate-config   # appends new keys (your values kept; .bak made)
bash install.sh --all              # idempotent: pulls vision model, fills gaps
```

---

## 7. Testing (`tests/test_frames.py`, stdlib unittest)

- `parse_timestamp`: `mm:ss`, `hh:mm:ss`, bare seconds, and rejection of bad
  tokens (named in the error).
- slide-id formatting: 1-indexed, zero-padded to 4 digits; order preserved.
- manifest shape from `extract_frames.py` (paths relative; metadata present) —
  skips gracefully if ffmpeg is absent (mirrors existing test philosophy).
- `video-frames-details.json` schema validation from a synthetic manifest +
  stubbed description (no Ollama call needed).
- `ollama_client.build_payload` includes `images` only when provided, and omits
  it otherwise (guards the additive change).

Config-migration tests (can live in `test_frames.py` or a small
`test_migrate_config.py`):

- drift detection finds a key removed from a sample user config.
- `migrate_config.py` append preserves a customized value and existing lines
  byte-for-byte, adds only the missing keys, and writes a `.bak`.

Vision/summary Ollama integration is **not** unit-tested (consistent with the
repo: validate with a real `run.py --frames ...` invocation).

---

## 8. Files touched

New:
- `scripts/extract_frames.py`
- `scripts/describe_frames.py`
- `scripts/migrate_config.py`
- `templates/frame_prompts/describe.md`
- `templates/frame_prompts/summary.md`
- `tests/test_frames.py`

Modified:
- `scripts/run.py` — `--frames` flag, timestamp wiring, gated frames block,
  pass `summary_max_chunk_chars` to `summarize.py`.
- `scripts/ollama_client.py` — optional `images` support (additive).
- `scripts/preflight.py` — config-drift check + vision-model presence note.
- `install.sh` — `--migrate-config` action; ensure vision model pulled.
- `config.example.yaml` — new `ollama.*`, `frames.*`, `install.ollama_models`.
- `SKILL.md` — document the `--frames` trigger, outputs, and upgrade procedure.
- `references/install.md` — upgrade procedure + migrate-config.
- `references/design.md` — rationale for the frames step + upgrade strategy.

Re-run `bash package.sh video-meeting` after edits to refresh the bundle.

---

## Risks / open implementation questions

- **YAML duplicate-parent append.** Whether appending `ollama:\n  vision_model:`
  when `ollama:` already exists is safe depends on `config_get.py`'s loader. The
  plan's first step verifies loader behavior and, if duplicate top-level keys are
  not merged, switches `migrate_config.py` to a structured in-place insert under
  the existing parent (still append-only in spirit: existing values untouched,
  backup written). Either way, no existing user value is modified.
- **Vision model choice/size.** `chandra-ocr-2` is the default; configurable. If a
  user's GPU/model set differs, the `/api/tags` preflight names the exact pull.
- **Frame at/after EOF.** A timestamp past the video duration yields no frame;
  `extract_frames.py` detects the missing output file and errors with the slide
  id and timestamp rather than producing a silent gap.
