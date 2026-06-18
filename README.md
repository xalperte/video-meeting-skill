# Video-Meeting Skill — project root

This folder holds the **`video-meeting`** skill and its packaging/installation
tooling. The skill turns a meeting/presentation recording (mp4) into a knowledge
pack — named transcript, summary, action items, slides, a PDF report, and a
ready-to-send email — running fully locally on a Linux + NVIDIA GPU machine
(Whisper + pyannote + Ollama), and maintaining a persistent registry of
participants recognized by voice across meetings.

## What's here

| Path | What it is |
|---|---|
| `video-meeting/` | The skill itself (SKILL.md, scripts, templates, tests, config) |
| `video-meeting.skill` | The packaged, installable bundle (zip) |
| `package.sh` | Rebuilds `video-meeting.skill` from the folder after edits |
| `video-meeting-skill-install.md` | **Start here** — install + environment setup guide |

## Quick links

- **Install & set up:** [`video-meeting-skill-install.md`](video-meeting-skill-install.md)
  — how to install the `.skill` into Claude and prepare the GPU machine, split into
  out-of-session (`sudo`/web) vs. in-session (no-sudo, delegable to Claude) steps.
- **How it works (canonical design doc):**
  [`video-meeting/references/design.md`](video-meeting/references/design.md)
- **Skill instructions / workflow:** [`video-meeting/SKILL.md`](video-meeting/SKILL.md)
- **Environment & troubleshooting:**
  [`video-meeting/references/install.md`](video-meeting/references/install.md)

## Common commands

```bash
# Rebuild the installable bundle after editing the skill
bash package.sh video-meeting                 # -> video-meeting.skill

# On the GPU machine: validate the environment
bash video-meeting/install.sh --check

# Run the pipeline on a recording
python3 video-meeting/scripts/run.py --video meeting.mp4 \
    --title "Sprint grooming" --meeting-type grooming

# Run the (offline) test suite
bash video-meeting/tests/run_tests.sh
```

## Three-line mental model

1. Install the `.skill` into your Claude environment (desktop/Cowork, Claude Code,
   or claude.ai).
2. Prepare the GPU machine once — the `sudo`/web parts yourself, the rest via
   `install.sh --user-space` (no sudo, safe to ask Claude to do).
3. Hand Claude a recording; it runs `run.py` and produces the artifacts.

See the install guide for the full, step-by-step process.
