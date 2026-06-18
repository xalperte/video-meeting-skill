# video-processor — Design

**Date:** 2026-06-18
**Status:** Approved (design), pending implementation plan

## Purpose

A small local app to manually pick and label moments (frames) in a meeting
video. It lets you load a video, navigate it precisely (play/pause, scrub,
"go to" by `mm:ss` / `hh:mm:ss` / bare seconds), mark moments while watching,
and maintain a time-ordered column of marked frames you can re-seek to, label,
and delete. Selections are saved to `<video-stem>-frames.json` next to the
video, in a schema that feeds the existing `extract_frames.py` pipeline.

This tool produces the timestamp list that `extract_frames.py` consumes; it is
the interactive front-end for choosing those moments instead of typing
timestamps on the command line.

## Scope

In scope:
- Load one video at a time; navigate and mark/label/delete frames; save/load JSON.
- In-app file browsing to open a different video or frames file without restarting.

Out of scope (YAGNI):
- Editing/trimming video, exporting clips, thumbnails of every marker.
- Running `extract_frames.py`/`describe_frames.py` — this tool only writes the JSON.
- Multi-video sessions, auth, or any networked/multi-user use (single local user).

## Technology

- **Local web app.** A tiny Flask backend serves one page; playback uses the
  browser's HTML5 `<video>`. Launching opens the page in the default browser.
- **Flask is the single runtime dependency.** Rationale: HTML5 `<video>`
  seeking requires the server to honor HTTP **Range** requests. Python's stdlib
  `http.server` does not support Range out of the box (broken/no seeking on
  large files). Flask's `send_file(..., conditional=True)` handles Range
  natively. Hand-rolling Range parsing on stdlib was rejected as more fragile
  code for no benefit.
- Its own `pyproject.toml` and venv, independent of the skill's other venvs.

## Project layout

```
video-meeting/bin/video-processor/
  pyproject.toml          # name=video-processor, dep: flask; [project.scripts] video-processor=video_processor.__main__:main
  README.md
  video_processor/
    __init__.py
    __main__.py           # CLI: parse optional video path, pick free port, start server, open browser
    server.py             # Flask app factory + routes
    timecode.py           # parse/format seconds <-> "mm:ss"/"hh:mm:ss" (pure, unit-testable)
    static/
      index.html
      app.js
      style.css
  tests/
    test_timecode.py
    test_server.py
```

Launched via the `video-processor` console script with an optional path:
`video-processor meeting.mp4`.

## Backend (Flask)

Single video is "current" server-side state, set at launch (from the CLI arg)
or via `/api/open`.

Routes:
- `GET /` — serves the single page (`index.html`).
- `GET /api/state` — returns `{video_path, video_name, has_video, frames: [...]}`
  for the current video; `frames` is the loaded `<stem>-frames.json` or `[]`.
- `GET /api/video` — streams the current video file with `send_file(conditional=True)`
  so the browser can seek (HTTP 206 / Range).
- `POST /api/frames` — body is the frames list; writes
  `<video-dir>/<video-stem>-frames.json` atomically (temp file + `os.replace`).
- `GET /api/browse?path=<dir>` — lists subdirectories and relevant files
  (videos + `*.json`) under `<dir>` for the in-app Open panel. Defaults to the
  current video's directory (or cwd) when `path` is omitted.
- `POST /api/open` — body `{path}`; sets the current video, and auto-loads the
  sibling `<stem>-frames.json` if it exists. Returns the same shape as `/api/state`.

Path handling: `browse`/`open` resolve and normalize paths; reject paths that
don't exist or aren't readable. (Single local user, full filesystem read is
acceptable; guard only against malformed/nonexistent paths and basic traversal
of the served static dir.)

## Frontend (single page, two columns)

Left — **player**:
- `<video>` element sourced from `/api/video`.
- Play/pause, native scrubber, and a current-time readout shown both as
  `hh:mm:ss` and `(sec N)`.
- A **Go to** text input accepting `mm:ss`, `hh:mm:ss`, or a bare number /
  `sec N`; on submit it sets `video.currentTime`. Invalid input shows an inline
  message and does not seek.
- **Mark frame** button — and clicking on the video — capture the current
  `video.currentTime` as a new frame entry.

Right — **frames column**:
- Entries sorted ascending by time, each showing `hh:mm:ss` + an editable
  **label** field.
- Click an entry → seek the video to that frame's time.
- Per-entry **delete** button.
- A **Save** button persists the list via `POST /api/frames`.
- An **Open…** control opens the server-side file browser (`/api/browse`,
  `/api/open`).

## Data flow & schema

`video.currentTime` (float seconds) is the source of truth per marker. The
in-memory list is kept sorted by `timestamp_s`. Saving serializes to:

```json
{
  "video": "meeting.mp4",
  "frames": [
    {"timestamp_s": 70.0, "timestamp": "01:10", "label": "Architecture slide"},
    {"timestamp_s": 130.5, "timestamp": "02:10", "label": ""}
  ]
}
```

- `timestamp_s` is canonical (float seconds).
- `timestamp` is the derived display string (`hh:mm:ss` or `mm:ss`).
- `label` is a free-text string, possibly empty.
- `video` is the basename of the video file.

This is compatible with `extract_frames.py`, which accepts bare seconds or
`mm:ss`/`hh:mm:ss` timestamps. On load, entries are read back and the column
repopulated; if a file lacks `timestamp_s`, it is recomputed from `timestamp`.

## Time parsing

`timecode.py` implements parse/format mirroring
`extract_frames.parse_timestamp` rules:
- one `:` → `mm:ss`; two `:` → `hh:mm:ss`; bare value → seconds.
- a leading `sec ` prefix (UI convenience) is stripped to a bare number.
- negative or malformed values raise `ValueError`.

A JavaScript twin in `app.js` implements the same rules for the Go-to field and
display formatting. `timecode.py` is the authoritative, unit-tested reference;
the JS mirrors it.

## Error handling

- Invalid Go-to input → inline message, no seek.
- Missing/nonexistent video → clear error on `/api/state` and `/api/open`.
- Port in use → `__main__` picks the next free port before opening the browser.
- `browse`/`open` with bad path → 400 with a message; static dir traversal guarded.
- Save failure (permissions/disk) → error surfaced in the UI; atomic write means
  no partially written JSON.

## Testing

Stdlib `unittest` (matches the repo convention; no pytest):
- `test_timecode.py` — parse/format round-trips and edge cases (mm:ss, hh:mm:ss,
  bare seconds, `sec N`, fractional seconds, invalid/negative inputs).
- `test_server.py` — via Flask test client: frames save → load round-trip,
  `/api/browse` listing shape, `/api/state` with and without a sibling JSON,
  and that `/api/video` honors a Range request (returns 206). Tests that need a
  real media file are skipped gracefully if no fixture/ffmpeg is available.
