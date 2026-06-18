# Installation & Setup

How `install.sh` provisions the local AI stack for the **video-meeting** skill, what
it does automatically, what needs you, and how to fix common failures.

There is no "run on skill install" hook — system setup needs `sudo`, a working GPU
driver, and a one-time license acceptance, none of which can run silently. So the
model is: a bundled **idempotent installer** that you run once (or that the skill
offers to run when preflight fails). Re-running is always safe — each phase checks
"already done?" and only fills what's missing.

## Target machine

Designed and tested for:

- Ubuntu (24.04 / 26.04), single **NVIDIA A5000, 16 GB VRAM**, 128 GB RAM.
- A working NVIDIA driver (`nvidia-smi` returns a table).
- A local **Ollama** service (the installer can set this up).

Other Linux + NVIDIA setups should work; the 16 GB VRAM figure drives model sizing
and the "load models sequentially" rule (see `design.md` §11.4).

## Portability: `${USER_HOME}`

The config and docs never hardcode a home directory. Paths use the `${USER_HOME}`
token, which `install.sh` and the config loader expand at runtime:

- `${USER_HOME}` defaults to the invoking user's `$HOME` — e.g. `/home/xalperte`
  on this laptop, `/home/alice` on someone else's machine. The same skill installs
  cleanly for any user on any Linux box without editing paths.
- To base everything somewhere other than `$HOME` (a shared models partition, a
  service account), export an override before running:
  ```bash
  export USER_HOME=/data/video-meeting
  bash install.sh --all
  ```
- Any other `${ENV_VAR}` in `config.yaml` is expanded the same way, so you can
  parameterize further if needed.

## Quick start

```bash
# from the skill directory
cp config.example.yaml config.yaml      # paths use ${USER_HOME}; edit only if needed
bash install.sh --all                   # provision everything (expands ${USER_HOME})
bash install.sh --check                 # validate only (runs preflight)
```

If `--all` reports a missing GPU or pyannote token, fix those (below) and re-run.

## What the installer does (phases)

Each phase is idempotent and prints a clear pass/skip summary.

1. **System packages** (`sudo apt`): `ffmpeg`, plus pyenv build deps
   (`build-essential`, `libssl-dev`, `libffi-dev`, `zlib1g-dev`, `libbz2-dev`,
   `libreadline-dev`, `libsqlite3-dev`, `libsndfile1`, `liblzma-dev`). Skipped if
   already present. Also installs LibreOffice if `.odp` export is enabled and
   `soffice` is missing.
2. **pyenv + pyenv-virtualenv**: installed under `install.pyenv_root` if absent;
   creates the two environments named in config (`whisper-env`, `pyannote-env`).
3. **Python dependencies** (pinned):
   - `whisper-env` → `faster-whisper`, `ctranslate2`, `av`.
   - `pyannote-env` → `pyannote.audio`, a CUDA build of `torch`/`torchaudio`
     matched to your driver, `speechbrain`, `numpy`, `soundfile`.
   - `render-env` → `openpyxl`, `python-pptx`, `python-docx` (document renderers,
     no GPU).
4. **Models**:
   - Pre-pull Whisper weights into `env.whisper.model_dir`.
   - Cache pyannote diarization + embedding models into `env.pyannote.model_dir`
     (needs the HF token — see "Manual steps").
5. **Ollama** (when `install.manage_ollama: true`): installs the service if
   missing and `ollama pull`s each model in `install.ollama_models`. Also writes a
   systemd drop-in (`/etc/systemd/system/ollama.service.d/video-meeting.conf`) with
   `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE` matching `ollama.kv_cache_type`
   in config (default `q8_0`), so the chosen `num_ctx` (default 64K) fits in 16 GB,
   then restarts the service.
6. **Config**: if `config.yaml` is absent, generate it from the example and fill in
   the interpreter/binary/model paths the installer just created.
7. **Preflight**: run `scripts/preflight.py` and report each check.

## Flags

```
install.sh --all            # everything (default; sudo for apt + Ollama service)
install.sh --user-space     # NO SUDO: venvs + pip deps + models + ollama model pulls
install.sh --no-ollama      # skip the Ollama service + model pulls
install.sh --models-only    # just (re)download model weights
install.sh --check          # run preflight only; change nothing
install.sh --install-cuda   # attempt NVIDIA driver/CUDA (OFF by default)
install.sh --uninstall      # remove venvs + cached models
install.sh --uninstall --purge   # also remove the global participant registry
```

`--user-space` is the no-sudo path: it creates the venvs, installs the Python deps,
downloads the models, and `ollama pull`s the LLMs, but **assumes** the apt packages,
GPU driver, and the Ollama service were already installed (the sudo/one-time steps).
It's the part you can safely ask Claude to run inside a session.

`--uninstall` (without `--purge`) leaves system ffmpeg, the global registry, and
your processed meetings untouched.

## Manual steps the installer cannot do for you

These need a human and are detected with clear, actionable messages:

1. **`sudo`** — apt and the Ollama install require privilege. Run the installer as
   a user with sudo, or pre-install ffmpeg/Ollama yourself.
2. **NVIDIA driver / CUDA** — driver installs are host-specific and risky, so they
   are **off by default**. The installer verifies the GPU with `nvidia-smi` and
   fails fast if it's not visible. Install the driver via your distro's tooling
   (e.g. `ubuntu-drivers`), reboot, confirm `nvidia-smi`, then re-run. Only use
   `--install-cuda` if you accept the installer attempting it.
3. **pyannote license (one-time)** — the diarization/embedding models are **gated**
   on Hugging Face. You must:
   - Create a free HF account and a read token.
   - Visit the model pages and **accept the user conditions** for
     `pyannote/speaker-diarization-3.1` and `pyannote/embedding`.
   - Save the token to the path in `env.pyannote.hf_token_file`:
     ```bash
     mkdir -p "$(dirname ${USER_HOME}/.config/video-meeting/hf_token)"
     printf '%s' 'hf_xxx_your_token' > ${USER_HOME}/.config/video-meeting/hf_token
     chmod 600 ${USER_HOME}/.config/video-meeting/hf_token
     ```
   Without an accepted license the model download 401s even with a valid token.

## Preflight checks

`scripts/preflight.py` validates, and fails fast with the offending item, that:

- `ffmpeg_bin` and (if used) the whisper.cpp binary exist and run.
- Both venv interpreters exist and import their key packages
  (`faster_whisper`, `pyannote.audio`).
- Whisper and pyannote model directories contain the expected weights.
- The HF token file exists and is non-empty.
- The GPU is visible from inside `pyannote-env` (`torch.cuda.is_available()`),
  and reports the expected device.
- Ollama answers at `ollama.host` and has the `summary_model` and `tasks_model`
  pulled.
- Writable: `paths.global_dir`, `paths.meetings_dir`, `paths.work_dir`.

Run it any time: `bash install.sh --check`.

## Troubleshooting

**`torch.cuda.is_available()` is False inside pyannote-env.** The installed torch
is a CPU build, or the driver/CUDA runtime mismatch the wheel. Reinstall torch with
the CUDA index matching your driver, confirm `nvidia-smi` works first.

**pyannote download fails with 401/403.** License not accepted, or token missing/
wrong. Re-check both model pages and the token file (steps above).

**Out-of-memory during a run on the 16 GB GPU.** Confirm stages run sequentially
(they should — the orchestrator never loads two model families at once) and that
`ollama.keep_alive` is short so the LLM unloads. If Whisper still OOMs, drop
`env.whisper.compute_type` to `int8_float16` or use `large-v3-turbo`.

**LLM is slow / spills to CPU at 64K context.** The KV cache isn't quantized.
Verify the Ollama service has `OLLAMA_FLASH_ATTENTION=1` and
`OLLAMA_KV_CACHE_TYPE=q8_0` (`systemctl show ollama -p Environment`), and that
`ollama.kv_cache_type: q8_0` matches in config. If you can't enable KV
quantization, lower `ollama.num_ctx` to 32768 (safe at fp16). Never set 256K — it
will not fit and will offload to CPU.

**`soffice` not found when exporting `.odp`.** Install LibreOffice
(`sudo apt install libreoffice-impress`) or set `rendering.slides.formats: ["pptx"]`
to skip the conversion.

**Ollama model not found.** `ollama pull gemma4:12b` / `ollama pull qwen3.5:9b`, or
re-run `install.sh` (with `manage_ollama: true`).

**`pyenv: command not found` after install.** The installer invokes venvs by
absolute interpreter path and doesn't need `pyenv` on your interactive PATH. If you
want `pyenv` in your shell, add the standard init lines to `~/.bashrc`.

## After install

Process a recording by pointing the skill at an mp4. The first time a new person
speaks, the skill registers their voiceprint; subsequent meetings recognize them
automatically. See `design.md` for the full pipeline and data model.

## Upgrading an existing install

Dropping in a new skill bundle preserves your state: `package.sh` excludes
`config.yaml`, `hf_token`, and `*.token`, so your config and the global
participant registry are never overwritten — only code (scripts, templates,
`config.example.yaml`, SKILL.md) is replaced.

New config keys never break an old `config.yaml`: every setting is read with a
built-in default equal to the example, so the skill keeps working untouched.
To pick up new keys and the vision model used by `--frames`:

```bash
bash install.sh --check            # reports config drift + what's missing
bash install.sh --migrate-config   # appends missing keys to config.yaml
                                   #   (your values kept; writes config.yaml.bak)
bash install.sh --all              # idempotent: pulls the vision model, fills gaps
```

`--migrate-config` only ever *appends* — it never edits or reorders existing
lines, so customized values (e.g. a raised `summary_max_chunk_chars`, machine
paths) are preserved. A `config.yaml.bak` backup is written before any change.
