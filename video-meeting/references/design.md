# Meeting Video → Knowledge Pack — Skill Design Doc

**Status:** Draft for discussion
**Owner:** Xavi
**Last updated:** 2026-06-08

A local-first skill that turns a meeting/presentation recording (mp4) into a
reusable knowledge pack: named transcript, summary, action items, slides, a PDF
report, and a ready-to-send email — while maintaining a persistent, global
registry of participants and their voiceprints so people are recognized across
future meetings.

---

## 1. Goals

- Given an **mp4**, a **global participant registry**, and a **context object**
  describing intent, produce a per-meeting set of artifacts.
- **Recognize** returning participants by voice; only register a new voiceprint
  when no match exists.
- Run **fully local** via an Ollama LLM server plus a local ASR + diarization
  stack. No cloud calls for content.
- Be **modular**: the context decides which artifacts are produced, in which
  language, at which level of detail.

## 2. Non-goals

- Real-time / live transcription.
- Voice *cloning* / TTS (out of scope unless explicitly added later).
- A general-purpose project management integration (tasks are exported as files;
  pushing to Jira/Asana/etc. is a possible future extension).

---

## 3. Key conceptual decisions

### 3.1 Voiceprints, not "synthesized voices"
Recognizing *who is speaking* requires speaker **embeddings** (voiceprints) —
numeric fingerprints produced by a speaker model (pyannote / SpeechBrain ECAPA /
Resemblyzer) and compared by cosine similarity. This is the opposite of voice
*synthesis* (TTS). The global store therefore persists, per participant:

- a voice **embedding** (the matchable fingerprint), and
- optionally a short **reference audio clip** so a human can verify a match.

TTS samples are only added if we later want to *reproduce* a voice — not needed
for recognition.

### 3.2 Whisper does not identify speakers
Whisper transcribes and detects language but does **not** do diarization. Speaker
attribution needs a separate **diarization** pass (pyannote.audio) that splits
audio into speaker turns; we then embed each turn and match it against the global
store. Three audio stages, not one.

### 3.3 "Local AI server" = a small stack, not just Ollama
Ollama runs **LLMs only** (summary + task extraction). Whisper and pyannote are
**not** Ollama models. The local stack is:

| Capability | Tool | Notes |
|---|---|---|
| Audio extraction | ffmpeg | mp4 → 16 kHz mono WAV |
| Transcription | faster-whisper / whisper.cpp | multilingual (EN, ZH, ES, PT) |
| Diarization + embeddings | pyannote.audio | who spoke when + voiceprints |
| Summary | gemma4:12b (via Ollama) | 256K context, multimodal, native system prompt; map-reduce for long inputs |
| Task extraction | qwen3.5:9b (via Ollama) | strong structured-JSON / function-calling output |

> Model choice: **gemma4:12b** for summarization and **qwen3.5:9b** for structured
> task extraction. Both are recent Ollama library models with large (256K) context
> windows and fit the 16 GB A5000 alongside sequential loading. Configurable in
> `config.yaml` (`ollama.summary_model` / `ollama.tasks_model`).

### 3.4 Single source of truth: `meeting_record.json`
Extraction and rendering are decoupled. The pipeline produces one structured
`meeting_record.json`; **every** downstream artifact (tasks Excel, slides, PDF,
email) renders from it. Benefits: consistent outputs, regenerate one artifact
without re-running Whisper, easy to verify.

### 3.5 SQLite/JSON is the participant database; Excel is an export
Excel corrupts under concurrent writes and is a poor key store. The canonical
participant DB is **SQLite (or JSON)**; the **Excel is generated as a view/export**.

---

## 4. Architecture / pipeline

```
mp4
 └─ ffmpeg ─────────────► wav (16 kHz mono)
       ├─ whisper ──────► segments (text + timestamps + language)
       └─ pyannote ─────► speaker turns + per-turn embeddings
                              │
                              ▼
                    speaker identification
            (match embeddings vs global voiceprints)
                              │
        ┌─────────────────────┼───────────────────────────┐
        ▼                     ▼                            ▼
 transcript.md       update global registry        meeting_record.json
 (named, timestamped) (only if new participant)     (single source of truth)
                                                          │
                 ┌──────────────┬──────────────┬──────────┴───────┐
                 ▼              ▼              ▼                   ▼
            tasks.xlsx     slides.pptx/odp   report.pdf        email.md
            (xlsx skill)   (pptx skill)      (pdf skill)
```

### Stage detail
1. **Preprocess** — ffmpeg extracts normalized 16 kHz mono WAV; optional VAD to
   drop silence on long recordings.
2. **Transcribe** — Whisper produces timestamped segments and per-segment language.
3. **Diarize + embed** — pyannote yields speaker turns (`SPEAKER_00`, …) and an
   embedding per speaker.
4. **Identify** — match each speaker embedding against the global store
   (see §6). Replace labels with real names; flag unknowns / low-confidence.
5. **Assemble transcript** — named, timestamped `transcript.md`.
6. **Summarize** — context-conditioned, map-reduce over chunks for long meetings.
7. **Extract action items** — structured JSON: explicit vs AI-suggested, assignee,
   priority, source timestamp(s).
8. **Render artifacts** — from `meeting_record.json` via the xlsx / pptx / pdf
   sub-skills + the email writer.

---

## 5. Data model

### 5.1 Global registry folder
```
/global/
  participants.db            # source of truth (SQLite) or participants.json
  participants.xlsx          # generated export (name, last name, description,
                             #   contact data, voiceprint ref, last seen)
  voiceprints/
    <participant_id>.npy     # embedding vector
    <participant_id>.wav     # optional reference clip
```

### 5.2 Participant record
```
participant_id, first_name, last_name, description, email, contact,
voiceprint_path, sample_clip_path, embedding_version,
first_seen, last_seen, meetings_count
```

### 5.3 Per-meeting folder
```
/meetings/<YYYY-MM-DD>-<slug>/
  audio.wav
  transcript.md
  summary.md
  meeting_record.json        # single source of truth
  tasks.xlsx
  slides.pptx (or .odp)
  report.pdf
  email.md
```

### 5.4 `meeting_record.json` (sketch)
```json
{
  "meeting": { "title": "", "date": "", "type": "feature|grooming|catchup|presentation",
                "language_out": "en", "duration_s": 0 },
  "participants": [ { "participant_id": "", "name": "", "match_confidence": 0.0,
                       "status": "known|new|unconfirmed" } ],
  "summary": { "tldr": "", "sections": [ { "category": "", "points": [] } ] },
  "action_items": [ { "title": "", "type": "explicit|ai_suggested",
                       "assignee": "", "priority": "", "source_ts": ["00:12:30"],
                       "confidence": 0.0 } ],
  "decisions": [], "open_questions": [],
  "transcript_ref": "transcript.md"
}
```

---

## 6. Speaker identification & idempotency (needs precise rules)

- **Thresholds:** `>= T_high` → match an existing participant; `< T_low` → new
  participant; **between** → mark `unconfirmed` and request human confirmation
  rather than guessing.
- **Register new only when no match** — atomic, file-locked write to the global
  DB so concurrent runs don't clobber it.
- **Reconcile with the provided list** — the given participant list may not match
  the diarized speaker count. More speakers than listed → unknown guests; fewer →
  someone silent. Define behavior for each.
- **Incremental vs fresh** — decide whether to update a participant's embedding
  over time (running average → better recognition, needs `embedding_version`) or
  keep the first capture.
- **Biometric governance** — voiceprints are biometric data: define retention,
  consent (especially external guests), and deletion.

---

## 7. Context object (the control knob)

The context conditions prompts and selects outputs. Proposed fields:

```yaml
meeting_type: feature | grooming | catchup | presentation | other
output_language: auto | en | zh | es | pt  # auto = dominant spoken language (default)
audience: team | leadership | client
tone: neutral | concise | formal
detail_level: brief | standard | deep
artifacts: [transcript, summary, tasks, slides, report, email]   # toggleable
suggest_tasks: true
slides_format: pptx | odp
```

### Meeting-type templates
Different scenarios extract different things, so `meeting_type` drives the prompt
template and output structure:

- **Recorded presentation** → summary + key points; few/no tasks.
- **Catch-up** → per-person "what was done" + PM comments/decisions + action items.
- **Backlog grooming** → prioritized backlog changes (re-estimates, re-orders),
  not generic tasks.
- **Feature meeting** → decisions + scope (now / later / changed) + open questions.

> Generalization: model the extraction as **action items + decisions + open
> questions**, each flagged `explicit` or `ai_suggested`, rather than only "tasks."
> The two-group split (explicit vs suggested) is preserved in the tasks Excel and
> slides.

---

## 8. Outputs spec

| Artifact | Renderer | Notes |
|---|---|---|
| `transcript.md` | internal | Named speakers + timestamps |
| `summary.md` | LLM | TL;DR + categorized sections; multi-slide-friendly |
| `tasks.xlsx` | xlsx skill | Columns: title, type (explicit/suggested), assignee, priority, source timestamp, confidence |
| `slides.pptx/odp` | pptx skill | Intro → summary (categorized, multi-slide) → tasks in 2 groups |
| `report.pdf` | pdf skill | **Same `meeting_record.json`**, report layout (not slides) |
| `email.md` | internal | Cover note to send the pack to all attendees |

The PDF "report version" and the slides consume the **same** structured record
with a different layout flag — they should never diverge in content.

---

## 9. Sub-skill composition

The skill is an **orchestrator**; it owns audio processing, extraction, and the
global registry, and delegates rendering:

- `xlsx` skill → tasks export + participants export
- `pptx` skill → slides (accepts `meeting_record.json` + layout = `presentation`)
- `pdf` skill → report (accepts the same JSON + layout = `report`)

Clean interface: sub-skills take the structured record and a layout flag, return
a file. No business logic in the renderers.

---

## 10. Cross-cutting requirements

- **Multilingual:** Whisper detects per-segment language (meetings can be mixed);
  the *output* language comes from context, not the spoken language.
- **Traceability:** every summary point and task references the **timestamp(s)**
  it derives from — critical for verification and trust.
- **Confidence & provenance:** AI-suggested tasks and low-confidence speaker
  matches are clearly flagged; never present a guessed assignee as fact.
- **Long videos:** VAD + chunked / map-reduce summarization to respect context
  windows.
- **Robustness:** handle low-quality audio, overlapping speech, single-speaker
  recordings, and speakers not in the provided list.
- **Atomic global writes:** lock + temp-file-rename when updating the registry.

---

## 11. Execution environment for the non-LLM tools

The non-LLM tools are **not** a single managed service like Ollama — each is a
binary or a Python package with its own dependencies, weights, and CUDA needs. The
skill must not assume any of them is "just on PATH"; every path and environment
detail is **declared in config** and the scripts invoke tools explicitly. This is
what makes the skill reproducible when run non-interactively.

### 11.1 One virtualenv per tool, invoked by absolute interpreter path
Whisper and pyannote often pull **conflicting** PyTorch / CUDA dependency
versions, so they get **separate** environments rather than one shared venv.
Using pyenv-virtualenv is fine, but the skill should **not** rely on
`source .../activate` — shell activation is fragile in a non-interactive
context (no login shell, no `pyenv init`). Instead, call the venv's interpreter
**by absolute path**:

```bash
# Don't:  pyenv activate whisper-env && python transcribe.py
# Do:
"$WHISPER_PY" scripts/transcribe.py --in audio.wav --out segments.json
```

where `WHISPER_PY=${USER_HOME}/.pyenv/versions/whisper-env/bin/python`. This is
self-contained, order-independent, and needs no `pyenv init` in the environment.

> **Portability — `${USER_HOME}`.** No path is hardcoded to a specific home. The
> config loader and `install.sh` expand `${USER_HOME}` (and any other `${ENV_VAR}`)
> at runtime; `USER_HOME` defaults to the invoking user's `$HOME` (e.g.
> `/home/xalperte`) and can be overridden with `export USER_HOME=...`. This keeps
> the skill installable for any user on any Linux machine.

### 11.2 What config must declare
```yaml
# config.example.yaml — environment section
env:
  ollama_host: "http://127.0.0.1:11434"     # running service (systemd)

  ffmpeg_bin: "/usr/bin/ffmpeg"

  whisper:
    python: "${USER_HOME}/.pyenv/versions/whisper-env/bin/python"
    impl: "faster-whisper"                  # or whisper.cpp
    binary: ""                               # set if using whisper.cpp build
    model_dir: "${USER_HOME}/models/whisper"   # where large-v3 weights live
    model: "large-v3"
    compute_type: "float16"                  # fits A5000 16 GB
    workdir: "${USER_HOME}/.cache/video-skill/whisper"

  pyannote:
    python: "${USER_HOME}/.pyenv/versions/pyannote-env/bin/python"
    model_dir: "${USER_HOME}/models/pyannote"
    hf_token_file: "${USER_HOME}/.config/video-skill/hf_token"  # gated models
    workdir: "${USER_HOME}/.cache/video-skill/pyannote"

  cuda:
    visible_devices: "0"                     # the A5000
    extra_ld_library_path: ""                # only if a tool needs it
    hf_home: "${USER_HOME}/.cache/huggingface" # caches model downloads
```

### 11.3 Invocation conventions
Each wrapper script:
1. Loads `config.yaml`, resolves the tool's `python`/`binary` and `workdir`.
2. Builds the environment explicitly — sets `CUDA_VISIBLE_DEVICES`, `HF_HOME`,
   `HF_TOKEN` (read from `hf_token_file`), and any `LD_LIBRARY_PATH` — rather than
   inheriting an interactive shell's env.
3. `cd`s into the tool's `workdir` (or passes absolute paths) so relative model
   lookups and temp files are predictable.
4. Runs the tool as a subprocess and writes a typed JSON artifact for the next
   stage. No stage depends on another stage's in-memory state.

Example shape:
```bash
CUDA_VISIBLE_DEVICES="$CUDA_DEV" HF_HOME="$HF_HOME" \
  "$PYANNOTE_PY" scripts/diarize.py \
    --in "$AUDIO" --model-dir "$PYANNOTE_MODEL_DIR" \
    --hf-token-file "$HF_TOKEN_FILE" --out turns.json
```

### 11.4 VRAM & sequencing on the 16 GB A5000
Whisper large-v3, pyannote, and a 7–9B LLM do not co-reside in 16 GB. The
orchestrator runs them as **separate, sequential subprocesses** so each frees its
VRAM on exit before the next loads. For the LLM, keep Ollama from holding the
model resident across the whole run (`keep_alive` tuned, or unload) so the audio
stages get the full GPU.

**Context window vs VRAM.** gemma4/qwen3.5 advertise a 256K architectural context,
but on 16 GB the binding constraint is the **KV cache**, not the weights. The
models are Q4_K_M (gemma4:12b ~7.6 GB, qwen3.5:9b ~6 GB), so weights are small and
most VRAM is free for KV; gemma4's sliding-window attention also keeps the cache
smaller than a naive full-attention estimate. **Chosen default: 64K (`num_ctx
65536`) with `q8_0` KV-cache quantization + flash attention**, which fits safely.
Ceilings: ~32K at fp16, ~64K at q8_0 (default), ~128K only at q4_0 (quality cost);
256K does **not** fit and must not be configured. Because long transcripts are
map-reduce chunked, 64K is ample. KV quantization is enforced on the Ollama
**service** env (`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`) — the
installer writes these into the systemd drop-in — with `num_ctx` and
`kv_cache_type` set to match in `config.yaml`.

### 11.5 Setup notes
- **Ollama** runs as a background service (e.g. systemd); reached over HTTP at
  `ollama_host`, not by spawning a binary.
- **pyannote** models are **gated** on Hugging Face — the user must accept the
  license once and provide a token (`hf_token_file`). Document this in setup.
- A **preflight check** script should validate every declared path (interpreters,
  binaries, model dirs, token, GPU visibility) and fail fast with a clear message
  before any long job starts.

---

## 12. Installation & bootstrap

### 12.1 What's realistic
A skill is markdown + scripts loaded into a session. There is **no install-time
hook** that automatically runs system-level setup the moment the skill is added —
and that's intentional: the setup needs `sudo`/apt, a working NVIDIA/CUDA stack,
and a one-time Hugging Face license acceptance, none of which can (or should) run
silently. So the model is:

> Ship an **idempotent installer** with the skill; run it **on first use** (the
> skill detects a failing preflight and offers to bootstrap) or let the user run
> it once explicitly. Re-running is safe and only fills what's missing.

### 12.2 `scripts/install.sh` — responsibilities (idempotent, phased)
Each phase checks "already done?" and skips if so; it prints a clear summary and a
final preflight result.

1. **System packages** (`sudo apt`): `ffmpeg`, build deps for pyenv
   (`build-essential`, `libssl-dev`, `libffi-dev`, `libsndfile1`, etc.). Skipped
   if binaries already resolve.
2. **pyenv + pyenv-virtualenv**: install if absent; create the two envs
   (`whisper-env`, `pyannote-env`) at known versions.
3. **Python deps**: `whisper-env` → `faster-whisper` (+ `ctranslate2`);
   `pyannote-env` → `pyannote.audio`, `torch` (CUDA build matched to the driver).
   Pinned versions for reproducibility.
4. **Models**: pre-pull Whisper weights into `whisper.model_dir`; cache pyannote
   models into `pyannote.model_dir` (requires token — see 12.3).
5. **Ollama (optional, toggle)**: install the service if missing and
   `ollama pull` the chosen LLMs (e.g. `qwen3.5:9b`, `gemma4:12b`). Default ON.
6. **Config**: generate `config.yaml` from `config.example.yaml`, filling in
   resolved interpreter/binary/model paths it just created.
7. **Preflight**: run `scripts/preflight.py`; report pass/fail per item.

### 12.3 What needs the user (can't be fully automated)
- **`sudo`** for apt and the Ollama/driver install — the installer must be run
  with privilege or will prompt.
- **NVIDIA driver + CUDA runtime** for the A5000: detected and *verified*
  (`nvidia-smi`), but not auto-installed by default — driver installs are
  risky/host-specific. The installer fails fast with guidance if the GPU isn't
  visible. (Optional `--install-cuda` flag could attempt it, off by default.)
- **pyannote license**: its models are **gated**. The user accepts the license
  once on Hugging Face and provides a token; the installer stores it at
  `hf_token_file`. The installer detects a missing/declined token and explains the
  exact page to accept.

### 12.4 Flags & modes
```
install.sh --all                # everything (default)
install.sh --no-ollama          # skip LLM service/model pulls
install.sh --models-only        # just (re)download weights
install.sh --check              # run preflight only, change nothing
install.sh --install-cuda       # attempt driver/CUDA (off by default)
```

### 12.5 First-run bootstrap flow
On a real invocation the orchestrator runs `preflight.py`; if anything is missing
it stops before any long job and offers to run `install.sh` (or the relevant
phase). This keeps "install" and "use" cleanly separated while still feeling
automatic to the user.

### 12.6 Uninstall / reset
Provide `install.sh --uninstall` to remove the venvs and cached models (leaving
system ffmpeg and the global participant registry untouched unless `--purge`).

---

## 13. Proposed skill layout (for the build phase)

```
video-meeting/
  SKILL.md                 # description + when-to-use + workflow
  install.sh               # idempotent installer (see §12); --check/--no-ollama/...
  scripts/
    run.py                 # ORCHESTRATOR: end-to-end, VRAM-sequential stages
    config_get.py          # shared config reader; expands ${USER_HOME}/${ENV}
    set_hf_token.sh        # securely store the HF token at the configured path
    preflight.py           # validate paths, venvs, models, token, GPU; fail fast
    extract_audio.py       # ffmpeg
    transcribe.py          # faster-whisper (whisper-env)
    diarize.py             # pyannote turns + embeddings (pyannote-env)
    registry.py            # global participant store: atomic JSON, voiceprints, matching
    identify_speakers.py   # match vs /global (hybrid), update registry; match/confirm
    ollama_client.py       # minimal Ollama HTTP client (stdlib); JSON-mode helper
    summarize.py           # Ollama (gemma4): map-reduce summary -> json + md
    extract_tasks.py       # Ollama (qwen3.5): structured action items (JSON)
    build_record.py        # assemble transcript.md + meeting_record.json (stdlib)
    render_email.py        # attendee email (LLM, localized; --no-llm fallback)
    render_tasks_xlsx.py   # tasks.xlsx from the record (render-env: openpyxl)
    render_slides.py       # slides.pptx + .odp from the record (render-env: python-pptx)
    render_report.py       # report.pdf via .docx from the record (render-env: python-docx)
  templates/
    summary_prompts/       # base + map + one per meeting_type
    task_prompts/          # base + one per meeting_type
    email_prompt.md        # email drafting prompt
  tests/                   # stdlib unittest suite (run_tests.sh); skips on missing deps
  config.example.yaml      # Ollama host, model names, thresholds, paths, venvs
```

---

## 14. Resolved decisions

| # | Question | Decision | Implication |
|---|---|---|---|
| 1 | Runtime | **Native, on the laptop** — Ubuntu 26.04, NVIDIA A5000 (16 GB VRAM), 128 GB RAM | Direct access to localhost Ollama + GPU; no container networking needed. **16 GB VRAM is the real constraint** — load models *sequentially* (Whisper → pyannote → LLM), not concurrently. |
| 2 | Ambiguous speaker matches | **Hybrid** — auto-assign confident matches, pause for human confirmation only in the gray zone | Needs both thresholds (`T_high`, `T_low`) and a confirmation prompt step. |
| 3 | Output language | **Match the dominant spoken language** of the meeting | Detect language from Whisper, pick the dominant one, render all artifacts in it. `output_language` becomes `auto` by default (still overridable). |
| 4 | Voiceprint maintenance | **Keep multiple samples per participant**; match against any | Store a *set* of embeddings per person; add a new sample per meeting (cap N, e.g. keep best/most-recent). More robust to varying audio conditions. |
| 5 | Task delivery | **Files only for now** (Excel) | Keep the extraction → render boundary clean so a tracker push can be added later. |
| 6 | Slides format | **Both** — `.pptx` and `.odp` | pptx skill builds `.pptx`; export an `.odp` copy (e.g. via LibreOffice `--convert-to`). |

### Decision-driven spec changes
- **§3.1 / §5.2 / §6** — voiceprint store holds *multiple* embeddings per
  participant (`voiceprints/<id>/*.npy`), not a single vector. Matching scores
  against the set; registration appends a new sample (with an N-cap policy)
  instead of averaging.
- **§7** — `output_language` defaults to `auto` (dominant spoken language).
- **§8 / §9** — slides renderer emits `.pptx` then converts to `.odp`; both are
  delivered in the meeting folder.
- **§11** — sized for a single 16 GB GPU: prefer `whisper large-v3` or
  `large-v3-turbo`, with `gemma4:12b` (summary) and `qwen3.5:9b` (tasks) plus
  **sequential model loading / unloading** to stay within VRAM. Drop Whisper to
  `int8_float16` if memory is tight.

### Still to pin down during build
- Exact threshold values (`T_high`, `T_low`) — tune empirically on real samples.
- N-cap and selection policy for per-participant voiceprint samples.
- Confirmation UX for the gray-zone speaker step.

---

## Frame description (optional shared-slide capture)

When a meeting shares slides/screens, the user can pass `--frames` with
timestamps. `extract_frames.py` (ffmpeg) grabs one frame per timestamp into
`frames/slide-NNNN.<ext>`; `describe_frames.py` describes each with a local
Ollama **vision** model (`ollama.vision_model`) and summarizes them with the
text model. Output is standalone (`video-frames-details.json`,
`video-frames-summary.md`) — deliberately *not* merged into
`meeting_record.json`, so the main pipeline and its artifacts are unaffected and
the feature stays fully optional. It runs in the LLM phase (after diarization
frees VRAM); Ollama `keep_alive=0s` keeps vision and text models from
co-residing on the 16 GB GPU.

### Upgrade-safe configuration

New config keys are always read with built-in defaults (`get(cfg, key,
DEFAULT)`), so a pre-existing `config.yaml` keeps working. A few realistically
tweaked tunables (`ollama.summary_max_chunk_chars`, the `frames.*` knobs) live in
config so upgrades don't clobber them. `migrate_config.py` reconciles an old
config against `config.example.yaml` by appending only the missing keys —
inserting new leaves into existing parent blocks in the raw text rather than
appending a duplicate top-level key (which `yaml.safe_load` would treat as
last-wins, wiping siblings). `preflight.py` warns on drift; `install.sh
--migrate-config` applies it (backup + atomic write).
