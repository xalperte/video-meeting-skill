# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **Claude skill** (`video-meeting/`) plus its packaging tooling. The skill turns a meeting recording (mp4) into a knowledge pack — named transcript, summary, action items, slides, PDF report, email — running fully locally (Whisper + pyannote + Ollama on a Linux/NVIDIA machine), with a persistent global registry of participants recognized by voiceprint across meetings.

This is **not** a Python package: no setup.py/pyproject, no pip-installable module. Scripts are standalone, stdlib-first, and invoked by absolute interpreter paths resolved from config.

## Commands

```bash
# Run the test suite (stdlib unittest — no pytest)
bash video-meeting/tests/run_tests.sh
# or directly:
cd video-meeting && python3 -m unittest discover -s tests -p 'test_*.py' -v

# Run a single test module / case
cd video-meeting && python3 -m unittest tests.test_offline -v
cd video-meeting && python3 -m unittest tests.test_offline.SomeClass.test_case -v

# Exercise renderer tests too (needs openpyxl/python-pptx/python-docx):
VM_TEST_PYTHON=~/.pyenv/versions/render-env/bin/python bash video-meeting/tests/run_tests.sh

# Rebuild the installable bundle after editing the skill
bash package.sh video-meeting        # -> video-meeting.skill

# Validate the GPU environment (preflight only, changes nothing)
bash video-meeting/install.sh --check

# End-to-end pipeline run on a recording
python3 video-meeting/scripts/run.py --video meeting.mp4 \
    --title "Sprint grooming" --meeting-type grooming
```

Tests skip gracefully when optional deps (numpy, openpyxl, python-pptx, python-docx, ffmpeg, LibreOffice) or services (Ollama, GPU) are absent — they are meaningful in a bare checkout. Whisper/pyannote/Ollama integration is *not* covered by tests; validate with a real `run.py` invocation.

## Architecture

Canonical design doc: `video-meeting/references/design.md` (the "why" behind every decision). Operational workflow: `video-meeting/SKILL.md`.

### Pipeline (orchestrated by `scripts/run.py`)

Stages run as **separate, sequential subprocesses** — on a 16 GB GPU, Whisper, pyannote, and the LLM cannot co-reside; each must release VRAM before the next loads. Each stage writes a typed JSON/markdown artifact the next consumes; no shared in-memory state.

1. `extract_audio.py` (ffmpeg) → 16 kHz mono WAV
2. `transcribe.py` (faster-whisper, **whisper-env**) → segments + per-segment language
3. `diarize.py` (pyannote, **pyannote-env**) → speaker turns + voiceprint embeddings
4. `identify_speakers.py` → match embeddings vs global registry (hybrid: auto-assign above `T_high`, new below `T_low`, ask the user in between)
5. `build_record.py` → `transcript.md` + **`meeting_record.json`** — the single source of truth
6. `summarize.py` / `extract_tasks.py` (Ollama HTTP via `ollama_client.py`; map-reduce for long inputs; tasks are structured JSON with explicit vs ai_suggested split)
7. Renderers (`render_tasks_xlsx.py`, `render_slides.py`, `render_report.py`, `render_email.py`, **render-env**) — render from `meeting_record.json` *only*, never from upstream stages, so artifacts can't diverge and one artifact can be regenerated without re-running Whisper

### Key conventions

- **One virtualenv per tool** (whisper-env, pyannote-env, render-env) because Whisper and pyannote pull conflicting torch/CUDA versions. Scripts invoke the venv's interpreter **by absolute path from config** — never `source activate`, never assume anything is on PATH.
- **Config**: `config.yaml` (copied from `config.example.yaml`, never shipped in the bundle). All paths use the `${USER_HOME}` token, expanded at load time by `config_get.py` and `install.sh`; defaults to `$HOME`, overridable via `export USER_HOME=...`. Don't hardcode home directories anywhere.
- **Global participant registry** (`registry.py`): `participants.json` is the source of truth; CSV/xlsx are generated exports. Multiple voiceprint samples per person (capped). Writes must be atomic (temp-file + rename, with a lock). Register a new voiceprint only when there is no match.
- **`preflight.py`** validates all declared paths/venvs/models/token/GPU before any long job; the skill workflow always runs it first and offers `install.sh` (idempotent, phased) on failure.

### Packaging

`package.sh` zips the skill folder into `video-meeting.skill`. It validates SKILL.md frontmatter (kebab-case name, description limits, allowed keys only) and **excludes** `config.yaml`, `hf_token`, `*.token`, `__pycache__`, `.DS_Store`, and a root `evals/` dir. Re-run it after any edit to `video-meeting/` to refresh the bundle. Exactly one SKILL.md may exist in the packaged tree.

### Prompt templates

`templates/summary_prompts/` and `templates/task_prompts/` hold one prompt per `meeting_type` (feature, grooming, catchup, presentation, other) plus `base.md` (and `map.md` for the map-reduce stage). Meeting type changes what gets extracted — e.g. grooming yields backlog changes, not generic todos. Adding a meeting type means adding a template in both directories.
