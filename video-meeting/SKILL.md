---
name: video-meeting
description: Turn a meeting or presentation recording (mp4) into a complete knowledge pack — named transcript, summary, action items, slides, a PDF report, and a ready-to-send email — using a fully local AI stack (Ollama LLMs + Whisper + pyannote). Maintains a persistent global registry of participants and their voiceprints so returning people are recognized automatically across meetings. Use this skill whenever the user has a recorded meeting, call, standup, catch-up, backlog grooming, feature discussion, or presentation video and wants it transcribed, summarized, turned into tasks/minutes, or written up — even if they only say "process this recording", "what did we decide", "write up the meeting", or "extract the action items". Trigger for any .mp4/.mkv/.mov/.wav meeting recording, or any mention of meeting notes, minutes, diarization, speaker identification, or transcript-to-tasks.
compatibility: Linux with NVIDIA GPU. Requires a local Ollama server, plus ffmpeg, faster-whisper (or whisper.cpp), and pyannote.audio installed via the bundled install.sh. Composes with the xlsx, pptx, and pdf skills for rendering.
---

# Video Meeting → Knowledge Pack

Process a meeting recording end-to-end **locally**: transcribe it, figure out who
said what, summarize it, pull out action items, and render the deliverables — while
keeping a long-lived registry of participants so the same people are recognized in
future meetings.

Everything runs on the user's machine: **Ollama** serves the LLMs; **Whisper**
transcribes; **pyannote** does diarization and produces the voiceprints used to
recognize speakers. No content leaves the machine.

The full design rationale lives in `references/design.md`. Read it when you need
the "why" behind a decision; this file is the operational workflow.

## Inputs

1. **A recording** — `.mp4` (also `.mkv/.mov/.wav`). The only required input.
2. **The global participant registry** — at the path in config (`paths.global_dir`).
   Holds known people and their voiceprints. Created on first run if absent.
3. **A context object** (optional but recommended) — what kind of meeting this is
   and what the user wants out of it. Shapes the summary, the task extraction, and
   which artifacts are produced. If omitted, infer sensible defaults and tell the
   user what you assumed. See "The context object" below.

## Before you start: preflight

The non-LLM tools each live in their own virtualenv with their own model weights,
and need a visible GPU and (for pyannote) a Hugging Face token. **Always run the
preflight first** so a long job never dies halfway:

```bash
"$PY" scripts/preflight.py --config config.yaml
```

If preflight fails, the tools aren't installed/configured. Offer to run the
bundled installer rather than trying to limp along:

```bash
bash install.sh --all          # or --check to only re-validate
```

The installer is idempotent — safe to re-run; it only fills what's missing. Note
that three things need the user: `sudo` (apt/Ollama), a working NVIDIA driver, and
a one-time pyannote license acceptance on Hugging Face. See `references/install.md`.

## Configuration

Everything path- and model-related is declared in `config.yaml` (copy from
`config.example.yaml` on first setup). Paths use the **`${USER_HOME}`** token so the
skill is portable across users and machines: expand `${USER_HOME}` (and any other
`${ENV_VAR}`) when loading config — it defaults to the invoking user's `$HOME`
(e.g. `/home/xalperte`) and can be overridden via `export USER_HOME=...`. Never
assume a tool is on `PATH` or that a venv is "activated" — read the resolved
interpreter/binary/model paths from config and invoke tools by **absolute path**. Do not rely on `source activate`; in a
non-interactive context it's unreliable. Instead:

```bash
"$WHISPER_PY" scripts/transcribe.py ...     # WHISPER_PY from config
"$PYANNOTE_PY" scripts/diarize.py ...        # PYANNOTE_PY from config
```

## Running it

For a normal end-to-end run, use the orchestrator — it reads config, creates the
dated meeting folder, runs every stage in the right venv with the right VRAM
sequencing, and renders the requested artifacts:

```bash
python3 scripts/run.py --video meeting.mp4 --title "Sprint grooming" \
    --meeting-type grooming --participants "Alice Ng" "Bob Li"
```

Useful flags: `--output-language` (default `auto` = dominant spoken language),
`--artifacts transcript summary tasks slides report email` (subset to produce),
`--num-speakers N` (if known), `--interactive` (prompt to confirm gray-zone
speakers). Anything omitted falls back to `context_defaults` in config.

**Processing shared slides/screens (optional).** When the user names specific
moments — e.g. *"process the following frames at [10:20, 15:10, 32:30, 46:00,
01:10:23]"* — pass them to `--frames`:

```bash
python3 scripts/run.py --video meeting.mp4 --title "Demo" \
    --frames 10:20 15:10 32:30 46:00 01:10:23
```

Timestamps are `mm:ss` (one colon) or `hh:mm:ss` (two colons). This grabs each
frame (ffmpeg), describes it with the local Ollama vision model
(`ollama.vision_model`), and writes a standalone pack — it does **not** alter the
transcript/summary/tasks artifacts:

- `frames/slide-0001.png …` — the captured frames (1-indexed, in the given order)
- `video-frames-details.json` — per slide: timestamp, image link, description
- `video-frames-summary.md` — a summary of the shared presentation

Omit `--frames` and nothing changes. The vision model is pulled by `install.sh`;
if it is missing the step stops up front with the exact `ollama pull` command.

**Speaker confirmation.** After identification, if any speakers fall in the gray
zone, `run.py` writes them to `mapping.json` under `pending_confirmation` and (when
not `--interactive`) continues with them labeled `(?)`. To resolve them, present
the pending speakers to the user, then apply their choices:

```bash
"$PYANNOTE_PY" scripts/identify_speakers.py confirm \
    --decisions decisions.json --embeddings voiceprints.npz \
    --global-dir <global_dir> --mapping mapping.json --out mapping.json
```

then re-run `build_record.py` and the renderers to refresh the artifacts.

The stages below are what `run.py` orchestrates; run them individually only for
debugging or partial re-runs.

## The pipelinepython3 video-meeting/scripts/run.py

Run these as **separate, sequential subprocesses**. On a 16 GB GPU, Whisper,
pyannote, and the LLM cannot co-reside — each must release its VRAM before the next
loads. Each stage writes a typed JSON/markdown artifact the next stage consumes; no
stage depends on another's in-memory state.

1. **Extract audio** — `scripts/extract_audio.py` (ffmpeg) → 16 kHz mono WAV.
2. **Transcribe** — `scripts/transcribe.py` (Whisper) → segments with text,
   timestamps, and per-segment language. Whisper auto-detects language; capture it.
3. **Diarize + embed** — `scripts/diarize.py` (pyannote) → speaker turns plus an
   embedding (voiceprint) per speaker. *Whisper does not do this; pyannote does.*
4. **Identify speakers** — `scripts/identify_speakers.py`. Match each speaker's
   embedding against the global registry (see "Speaker identification" below).
   Replace `SPEAKER_00` labels with real names; flag unknown / unconfirmed.
5. **Assemble transcript** — merge segments + speaker labels → `transcript.md`
   (named, timestamped).
6. **Summarize** — `scripts/summarize.py` via Ollama. Use the meeting-type prompt
   template; map-reduce over chunks for long meetings; write in the **output
   language** (default: the dominant spoken language).
7. **Extract action items** — `scripts/extract_tasks.py` via Ollama, returning
   **structured JSON** (use a JSON-strong model, e.g. qwen). Each item: title,
   `type` (`explicit` | `ai_suggested`), assignee, priority, source timestamp(s),
   confidence.
8. **Build the record** — `scripts/build_record.py` → `meeting_record.json`, the
   single source of truth for all artifacts.
9. **Render artifacts** — from `meeting_record.json` only (see "Outputs").

## Speaker identification (the recognition logic)

Recognition uses **voiceprints** (speaker embeddings), not synthesized voices.
Each participant stores **multiple** embedding samples; a new turn is scored
against the whole set (best/mean similarity).

- `similarity >= thresholds.high` → confident match; assign the participant.
- `similarity < thresholds.low` → no match; treat as a new participant.
- **in between** → `unconfirmed`: pause and ask the user to confirm "is this
  <name>?" rather than guessing. This is the agreed hybrid behaviour.
- **Register a new voiceprint only when there is no match.** Append the new
  sample to that participant's set (respect `voiceprints.max_samples_per_person`,
  dropping the oldest/weakest when over the cap). Writes to the global registry
  must be atomic (temp-file + rename, with a lock).
- **Reconcile with any provided participant list**: more speakers than listed →
  unknown guests (offer to register); fewer → someone was silent. Never invent an
  assignment you're not confident about — mark it and ask.

After updating the registry, regenerate the `participants.xlsx` export (the Excel
is a *view*; the DB/JSON is the source of truth).

## The context object

```yaml
meeting_type: feature | grooming | catchup | presentation | other
output_language: auto | en | zh | es | pt    # auto = dominant spoken language
audience: team | leadership | client
tone: neutral | concise | formal
detail_level: brief | standard | deep
artifacts: [transcript, summary, tasks, slides, report, email]   # toggle outputs
suggest_tasks: true
```

`meeting_type` selects the summary structure and what gets extracted. Generalize
"tasks" into **action items, decisions, and open questions** as fits the type:

- **presentation** → summary + key points by category; few/no tasks.
- **catchup** → per-person "what was done" + PM comments/decisions + action items.
- **grooming** → prioritized backlog changes (re-estimates, re-orders), not generic
  todos.
- **feature** → decisions + scope (now / later / changed) + open questions.

Only produce the artifacts listed in `artifacts`; not every meeting needs slides.

## Outputs

All written into `paths.meetings_dir/<YYYY-MM-DD>-<slug>/`. Every artifact renders
from `meeting_record.json` so they never diverge in content.

| Artifact | How | Notes |
|---|---|---|
| `transcript.md` | internal | Named speakers + timestamps |
| `summary.md` | summarize.py | TL;DR + categorized sections |
| `tasks.xlsx` | **xlsx skill** | title, type (explicit/suggested), assignee, priority, source ts, confidence |
| `slides.pptx` + `slides.odp` | **pptx skill** + LibreOffice convert | Intro → categorized summary (multi-slide ok) → tasks in two groups (explicit / suggested) |
| `report.pdf` | **pdf skill** | Same record, **report layout** (not slides) |
| `email.md` | render_email.py | Cover note to send the pack to all attendees, in the output language |
| `video-frames-details.json` | describe_frames.py | Per-slide timestamp + image + description (only with `--frames`) |
| `video-frames-summary.md` | describe_frames.py | Summary of the shared slides (only with `--frames`) |

When you reach the rendering steps, **read the relevant skill** (xlsx, pptx, pdf)
and pass it the structured record plus a layout flag — slides use a
`presentation` layout, the report uses a `report` layout, same content underneath.
For `.odp`, convert the generated `.pptx` with LibreOffice headless
(`soffice --headless --convert-to odp`).

## Quality / verification

- Keep timestamps on summary points and tasks so claims are traceable to the
  recording — useful for the user to verify, and for spotting hallucinated tasks.
- Clearly distinguish **explicit** (someone actually said it) from **ai_suggested**
  items. Never present a suggested task as if it was decided in the meeting.
- After building everything, sanity-check: do the assignees exist in the registry?
  Are unconfirmed speakers flagged? Is the output language correct?

## Reference files

- `references/design.md` — full architecture, data model, and the rationale behind
  every decision. Read for the "why".
- `references/install.md` — installer phases, what needs the user, troubleshooting.
- `config.example.yaml` — annotated configuration template.
