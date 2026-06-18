# Installing & Preparing the `video-meeting` Skill

This guide explains how to (A) install the skill into a Claude environment and
(B) prepare the local AI stack it depends on. It clearly marks which steps you
must do **yourself, outside a Claude session** (they need `sudo` or a web login),
and which you can **delegate to Claude inside a running session** (no `sudo`).

---

## 0. Before you start: the two-machine reality

The skill runs a local AI pipeline (Whisper + pyannote + Ollama) that needs an
**NVIDIA GPU (16 GB+) on Linux**. Two roles are involved, and they may be the same
or different computers:

- **The Claude environment** — where you talk to Claude (the desktop app / Cowork,
  Claude Code, or claude.ai). This is where the *skill* is installed.
- **The GPU machine** — the Linux box with the GPU, Ollama, and the model stack.
  This is where the *pipeline actually runs*.

For Claude to run the pipeline for you, your Claude session must have shell access
to the GPU machine (e.g. you run Claude Code on that machine, or Cowork has access
to it). The **skill folder must physically exist on the GPU machine** because that
is where `install.sh` and `run.py` execute.

Reference machine: Ubuntu, NVIDIA A5000 (16 GB), 128 GB RAM.

---

## A. Install the skill into a Claude environment

You have the distributable bundle `video-meeting.skill` (regenerate it any time
with `bash package.sh video-meeting`). Pick the path that matches your setup:

### A1. Claude desktop app / Cowork
Open `video-meeting.skill` and use **Save skill**, or go to
**Settings → Capabilities → Skills** and add it. Once saved it is available to your
sessions.

### A2. Claude Code (per project)
Unzip the bundle into the project's skills folder so Claude Code discovers it:

```bash
mkdir -p <your-project>/.claude/skills
unzip video-meeting.skill -d <your-project>/.claude/skills/
# results in <your-project>/.claude/skills/video-meeting/SKILL.md
```

Use `~/.claude/skills/` instead of the project path to make it available to all
your projects.

### A3. claude.ai
**Settings → Capabilities → Skills → Upload** and select `video-meeting.skill`.

> If a menu name differs in your version, check the current docs at
> https://docs.claude.com — the skill-install UI evolves.

After install, Claude will trigger the skill when you ask it to process a meeting
recording. But it can only *run* the pipeline once the environment below is ready.

---

## B. Prepare the environment (on the GPU machine)

There are two groups of steps. The simplest route is to run `install.sh --all`
yourself once (it does the `sudo` parts and tells you about the web parts), then
let Claude handle the rest. If you prefer a strict split, follow B1 then B2.

### B1. Do these yourself — outside any Claude session

These need `sudo` or a browser/account, so they are **not** safe to delegate.

1. **System packages** (`sudo`): `ffmpeg`, Python build dependencies, and
   LibreOffice (for `.odp`/`.pdf` output). Either run them by hand, or let
   `install.sh` do it:
   ```bash
   bash video-meeting/install.sh --all      # prompts for sudo; does steps 1–3
   ```
2. **NVIDIA driver + CUDA** (`sudo`, may need a reboot). Verify with `nvidia-smi`.
   `install.sh` does **not** install the driver by default — it only checks it.
3. **Ollama service** (`sudo`): installs the background service and writes the
   KV-cache tuning (`OLLAMA_KV_CACHE_TYPE=q8_0`, flash attention) so the 64K
   context fits in 16 GB. `install.sh --all` handles this.
4. **Hugging Face (web, one-time)** — pyannote's models are gated:
   - Create a free account at https://huggingface.co and a **read token**.
   - Accept the license on **both** model pages while logged in:
     - https://huggingface.co/pyannote/speaker-diarization-3.1
     - https://huggingface.co/pyannote/embedding
   - Keep the token handy for B2 (don't paste it into a shared chat — see Security).

If you ran `install.sh --all`, steps 1 and 3 are done, step 2 is verified, and the
installer will have told you about step 4. You can stop here and skip to **First
run** — or, if you ran the system parts separately, hand off to Claude with B2.

### B2. Ask Claude to do these — inside a session (no `sudo`)

Once B1 is in place, everything else lives in user space and is safe to delegate.
Ask Claude (it will run these on the GPU machine):

- **Create the config**: copy `video-meeting/config.example.yaml` to
  `config.yaml` and adjust paths if your home/layout differs. (Paths use
  `${USER_HOME}`, so usually no edits are needed.)
- **Store your HF token** — run the helper, which prompts so the token stays out
  of shell history (you type it; you need not give the token to Claude):
  ```bash
  bash video-meeting/scripts/set_hf_token.sh
  ```
- **Install the user-space stack** (no `sudo`): create the three virtualenvs,
  install the Python deps, download the Whisper + pyannote models, and pull the
  Ollama models:
  ```bash
  bash video-meeting/install.sh --user-space
  ```
- **Validate**: run preflight and fix any non-sudo issues it reports.
  ```bash
  bash video-meeting/install.sh --check
  ```

A good prompt is simply: *"Set up the video-meeting skill's user-space environment:
create config.yaml, run `install.sh --user-space`, then `install.sh --check`, and
tell me what's still missing."*

---

## Who does what — quick reference

| Step | Needs sudo / web? | Who | Command |
|---|---|---|---|
| Install the `.skill` into Claude | no (UI/file) | You | Save skill / unzip into `.claude/skills/` |
| apt packages (ffmpeg, build deps, LibreOffice) | **sudo** | You | `install.sh --all` |
| NVIDIA driver + CUDA | **sudo**/reboot | You | distro tooling; verify `nvidia-smi` |
| Ollama service + KV-cache tuning | **sudo** | You | `install.sh --all` |
| HF account, accept licenses, make token | **web** | You | huggingface.co |
| Create `config.yaml` | no | **Claude** | copy from `config.example.yaml` |
| Store HF token | no | You/Claude | `scripts/set_hf_token.sh` |
| Venvs + pip deps + models + ollama pulls | no | **Claude** | `install.sh --user-space` |
| Preflight check | no | **Claude** | `install.sh --check` |
| Process a recording | no | **Claude** | `scripts/run.py …` |

---

## First run & verification

1. Confirm everything is green:
   ```bash
   bash video-meeting/install.sh --check
   ```
2. Process a recording (ask Claude, or run it yourself):
   ```bash
   python3 video-meeting/scripts/run.py --video your_meeting.mp4 \
       --title "Test meeting" --meeting-type catchup
   ```
3. Outputs land in `<meetings_dir>/<date>-<slug>/`: `transcript.md`, `summary.md`,
   `tasks.xlsx`, `slides.pptx`/`.odp`, `report.pdf`, `email.md`, and
   `meeting_record.json`.

Notes for the first run:
- The first meeting registers everyone as **new** voiceprints; recognition kicks
  in from the second meeting onward.
- If `torch.cuda.is_available()` is false, the installed torch is a CPU build —
  reinstall with the CUDA channel matching your driver (`VM_TORCH_CUDA=cu124` is
  the default; override if needed).

Run the test suite any time to sanity-check the non-GPU logic:
```bash
bash video-meeting/tests/run_tests.sh
```

---

## Updating the skill

After editing any file in `video-meeting/`, rebuild the bundle and reinstall it in
your Claude environment:

```bash
bash package.sh video-meeting          # -> video-meeting.skill
```

(If the existing `.skill` can't be overwritten due to a file lock, delete it first
or package into a subfolder: `bash package.sh video-meeting ./dist`.)

---

## Security

- The Hugging Face token is **biometric-adjacent infrastructure** — store it only
  at the configured path (`~/.config/video-meeting/hf_token`, `chmod 600`). It is
  never written into the skill folder and never shipped in the `.skill`.
- Don't paste the token into a shared chat. If you already have, **rotate it** at
  https://huggingface.co/settings/tokens.
- Voiceprints in the global registry are biometric data — mind retention and
  consent, especially for external participants.
