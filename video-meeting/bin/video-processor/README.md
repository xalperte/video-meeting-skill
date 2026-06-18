# video-processor

A small local web app to mark, label, and re-seek moments ("frames") in a
meeting video, saving them to `<video-stem>-frames.json` — the timestamp list
consumed by the skill's `extract_frames.py` pipeline.

## Setup

```bash
cd video-meeting/bin/video-processor
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Run

```bash
.venv/bin/video-processor meeting.mp4   # or launch with no arg and use "Open…"
```

A browser tab opens on a free local port. Left: player with play/pause, scrub,
a "Go to" field (`mm:ss`, `hh:mm:ss`, or `sec N`/bare seconds), and "Mark frame"
(clicking the video also marks). Right: the time-ordered frame list — click a
time to seek, edit the label inline, ✕ to delete, "Save" to write the JSON.

## Output schema

```json
{
  "video": "meeting.mp4",
  "frames": [
    {"timestamp_s": 70.0, "timestamp": "01:10.000", "label": "Architecture slide"}
  ]
}
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```
