# video-processor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local browser app to mark, label, and re-seek moments in a meeting video, saving them to `<video-stem>-frames.json` compatible with the existing `extract_frames.py` pipeline.

**Architecture:** A tiny Flask backend serves one static page and a small JSON API; playback uses the browser's HTML5 `<video>` with HTTP Range support via `send_file(conditional=True)`. A pure `timecode.py` module (mirrored by a JS twin) is the authoritative time parser/formatter. The "current video" is server-side state set by a CLI arg or the `/api/open` endpoint.

**Tech Stack:** Python 3.9+, Flask (only runtime dep), HTML/CSS/vanilla JS, stdlib `unittest` for tests. Own `pyproject.toml` and `.venv` under `video-meeting/bin/video-processor/`.

---

## File Structure

All paths relative to repo root `video-meeting/bin/video-processor/`:

- `pyproject.toml` — package metadata, Flask dep, `video-processor` console script.
- `.gitignore` — ignore `.venv/` and `__pycache__/`.
- `README.md` — usage.
- `video_processor/__init__.py` — empty package marker.
- `video_processor/timecode.py` — `parse_timecode`, `format_timecode` (pure).
- `video_processor/server.py` — Flask app factory + routes + frames load/save helpers.
- `video_processor/__main__.py` — CLI entry: parse arg, free port, launch, open browser.
- `video_processor/static/index.html` — single page (two columns).
- `video_processor/static/app.js` — UI logic + JS timecode twin.
- `video_processor/static/style.css` — layout.
- `tests/test_timecode.py` — parse/format unit tests.
- `tests/test_server.py` — Flask test-client tests (save/load, browse, open, Range).

---

## Task 1: Scaffold project, venv, and packaging

**Files:**
- Create: `video-meeting/bin/video-processor/pyproject.toml`
- Create: `video-meeting/bin/video-processor/.gitignore`
- Create: `video-meeting/bin/video-processor/video_processor/__init__.py`

- [ ] **Step 1: Create the package directory and empty package marker**

```bash
mkdir -p video-meeting/bin/video-processor/video_processor/static
mkdir -p video-meeting/bin/video-processor/tests
touch video-meeting/bin/video-processor/video_processor/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`**

File: `video-meeting/bin/video-processor/pyproject.toml`

```toml
[project]
name = "video-processor"
version = "0.1.0"
description = "Interactive frame-marking tool for meeting videos"
requires-python = ">=3.9"
dependencies = ["flask>=3.0"]

[project.scripts]
video-processor = "video_processor.__main__:main"

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["video_processor"]

[tool.setuptools.package-data]
video_processor = ["static/*"]
```

- [ ] **Step 3: Write `.gitignore`**

File: `video-meeting/bin/video-processor/.gitignore`

```gitignore
.venv/
__pycache__/
*.pyc
```

- [ ] **Step 4: Create the venv and install editable**

Run:
```bash
cd video-meeting/bin/video-processor && python3 -m venv .venv && .venv/bin/pip install -q -e .
```
Expected: installs Flask and the `video-processor` package without error.

- [ ] **Step 5: Commit**

```bash
git add video-meeting/bin/video-processor/pyproject.toml \
        video-meeting/bin/video-processor/.gitignore \
        video-meeting/bin/video-processor/video_processor/__init__.py
git commit -m "chore: scaffold video-processor package"
```

---

## Task 2: timecode parsing/formatting (TDD)

**Files:**
- Test: `video-meeting/bin/video-processor/tests/test_timecode.py`
- Create: `video-meeting/bin/video-processor/video_processor/timecode.py`

- [ ] **Step 1: Write the failing tests**

File: `video-meeting/bin/video-processor/tests/test_timecode.py`

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from video_processor.timecode import parse_timecode, format_timecode


class ParseTimecode(unittest.TestCase):
    def test_bare_seconds(self):
        self.assertEqual(parse_timecode("70"), 70.0)

    def test_mm_ss(self):
        self.assertEqual(parse_timecode("01:10"), 70.0)

    def test_hh_mm_ss(self):
        self.assertEqual(parse_timecode("01:00:00"), 3600.0)

    def test_sec_prefix(self):
        self.assertEqual(parse_timecode("sec 70"), 70.0)

    def test_fractional(self):
        self.assertEqual(parse_timecode("130.5"), 130.5)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            parse_timecode("-5")

    def test_too_many_colons(self):
        with self.assertRaises(ValueError):
            parse_timecode("1:2:3:4")

    def test_non_numeric(self):
        with self.assertRaises(ValueError):
            parse_timecode("abc")

    def test_empty(self):
        with self.assertRaises(ValueError):
            parse_timecode("   ")


class FormatTimecode(unittest.TestCase):
    def test_mm_ss(self):
        self.assertEqual(format_timecode(70), "01:10")

    def test_hh_mm_ss(self):
        self.assertEqual(format_timecode(3661), "01:01:01")

    def test_drops_fraction(self):
        self.assertEqual(format_timecode(130.5), "02:10")

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            format_timecode(-1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd video-meeting/bin/video-processor && .venv/bin/python -m unittest tests.test_timecode -v
```
Expected: FAIL — `ModuleNotFoundError` / `ImportError` for `video_processor.timecode`.

- [ ] **Step 3: Write `timecode.py`**

File: `video-meeting/bin/video-processor/video_processor/timecode.py`

```python
"""Parse and format video timecodes.

Mirrors ``extract_frames.parse_timestamp`` rules so output feeds that pipeline:
one ':' is mm:ss, two is hh:mm:ss, a bare value is seconds. A leading 'sec'
prefix (UI convenience) is stripped to a bare number.
"""


def parse_timecode(value):
    """'mm:ss' | 'hh:mm:ss' | bare seconds | 'sec N' -> float seconds.

    Raises ValueError on empty, malformed, or negative input.
    """
    s = str(value).strip()
    if not s:
        raise ValueError("empty timecode")
    if s.lower().startswith("sec"):
        s = s[3:].strip()
        if not s:
            raise ValueError("empty timecode after 'sec'")
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError("too many ':' in timecode: %r" % value)
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValueError("non-numeric timecode: %r" % value)
    if any(n < 0 for n in nums):
        raise ValueError("negative timecode: %r" % value)
    if len(parts) == 1:
        secs = nums[0]
    elif len(parts) == 2:
        secs = nums[0] * 60 + nums[1]
    else:
        secs = nums[0] * 3600 + nums[1] * 60 + nums[2]
    return float(secs)


def format_timecode(seconds):
    """float seconds -> 'mm:ss', or 'hh:mm:ss' when >= 1 hour.

    Fractional seconds are dropped to whole seconds for display.
    """
    if seconds < 0:
        raise ValueError("negative seconds")
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%02d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd video-meeting/bin/video-processor && .venv/bin/python -m unittest tests.test_timecode -v
```
Expected: PASS (all tests OK).

- [ ] **Step 5: Commit**

```bash
git add video-meeting/bin/video-processor/video_processor/timecode.py \
        video-meeting/bin/video-processor/tests/test_timecode.py
git commit -m "feat: add timecode parse/format with tests"
```

---

## Task 3: Flask server — state, frames load/save, browse, open, video (TDD)

**Files:**
- Test: `video-meeting/bin/video-processor/tests/test_server.py`
- Create: `video-meeting/bin/video-processor/video_processor/server.py`

- [ ] **Step 1: Write the failing tests**

File: `video-meeting/bin/video-processor/tests/test_server.py`

```python
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from video_processor.server import create_app


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.video = os.path.join(self.tmp.name, "meeting.mp4")
        with open(self.video, "wb") as fh:
            fh.write(b"0123456789")  # tiny fake media bytes
        self.app = create_app(self.video)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_state_no_frames(self):
        data = self.client.get("/api/state").get_json()
        self.assertTrue(data["has_video"])
        self.assertEqual(data["video_name"], "meeting.mp4")
        self.assertEqual(data["frames"], [])

    def test_save_and_load_roundtrip(self):
        payload = {"frames": [
            {"timestamp_s": 130.5, "label": "b"},
            {"timestamp_s": 70.0, "label": "a"},
        ]}
        resp = self.client.post("/api/frames", json=payload)
        self.assertEqual(resp.status_code, 200)
        fr = resp.get_json()["frames"]
        self.assertEqual([f["timestamp_s"] for f in fr], [70.0, 130.5])
        self.assertEqual(fr[0]["timestamp"], "01:10")
        self.assertEqual(fr[0]["label"], "a")

        fp = os.path.join(self.tmp.name, "meeting-frames.json")
        self.assertTrue(os.path.exists(fp))
        with open(fp) as fh:
            disk = json.load(fh)
        self.assertEqual(disk["video"], "meeting.mp4")
        self.assertEqual(len(disk["frames"]), 2)

        data = self.client.get("/api/state").get_json()
        self.assertEqual(len(data["frames"]), 2)

    def test_load_recomputes_timestamp_s_from_string(self):
        fp = os.path.join(self.tmp.name, "meeting-frames.json")
        with open(fp, "w") as fh:
            json.dump({"video": "meeting.mp4",
                       "frames": [{"timestamp": "01:10", "label": "x"}]}, fh)
        data = self.client.get("/api/state").get_json()
        self.assertEqual(data["frames"][0]["timestamp_s"], 70.0)

    def test_browse_lists_video_and_json_and_dirs(self):
        open(os.path.join(self.tmp.name, "notes.json"), "w").close()
        os.mkdir(os.path.join(self.tmp.name, "sub"))
        data = self.client.get(
            "/api/browse?path=%s" % self.tmp.name).get_json()
        self.assertIn("meeting.mp4", data["files"])
        self.assertIn("notes.json", data["files"])
        self.assertIn("sub", data["dirs"])
        self.assertEqual(data["path"], self.tmp.name)

    def test_browse_bad_path(self):
        resp = self.client.get("/api/browse?path=/no/such/dir/xyz123")
        self.assertEqual(resp.status_code, 400)

    def test_open_switches_video(self):
        other = os.path.join(self.tmp.name, "other.mp4")
        with open(other, "wb") as fh:
            fh.write(b"xx")
        data = self.client.post("/api/open", json={"path": other}).get_json()
        self.assertEqual(data["video_name"], "other.mp4")

    def test_open_missing_path(self):
        resp = self.client.post("/api/open", json={"path": "/nope/x.mp4"})
        self.assertEqual(resp.status_code, 400)

    def test_video_range_returns_206(self):
        resp = self.client.get("/api/video", headers={"Range": "bytes=0-3"})
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp.data, b"0123")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd video-meeting/bin/video-processor && .venv/bin/python -m unittest tests.test_server -v
```
Expected: FAIL — `ImportError` for `video_processor.server`.

- [ ] **Step 3: Write `server.py`**

File: `video-meeting/bin/video-processor/video_processor/server.py`

```python
"""Flask app for the video-processor frame-marking UI.

The "current video" is process-level state set at launch or via /api/open.
Frames are persisted next to the video as <stem>-frames.json.
"""
import json
import os

from flask import Flask, abort, jsonify, request, send_file

from .timecode import format_timecode, parse_timecode

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}


def frames_path_for(video_path):
    """<dir>/<stem>-frames.json next to the given video."""
    d = os.path.dirname(os.path.abspath(video_path))
    stem = os.path.splitext(os.path.basename(video_path))[0]
    return os.path.join(d, "%s-frames.json" % stem)


def _normalize(frames):
    """Coerce frame dicts to canonical form, sorted ascending by time."""
    norm = []
    for fr in frames:
        ts = fr.get("timestamp_s")
        if ts is None and fr.get("timestamp") is not None:
            ts = parse_timecode(fr["timestamp"])
        if ts is None:
            continue
        ts = float(ts)
        norm.append({
            "timestamp_s": ts,
            "timestamp": format_timecode(ts),
            "label": fr.get("label") or "",
        })
    norm.sort(key=lambda x: x["timestamp_s"])
    return norm


def load_frames(video_path):
    """Read and normalize <stem>-frames.json, or [] if absent/unreadable."""
    fp = frames_path_for(video_path)
    if not os.path.exists(fp):
        return []
    with open(fp, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    frames = data.get("frames", []) if isinstance(data, dict) else []
    return _normalize(frames)


def save_frames(video_path, frames):
    """Atomically write normalized frames; return the file path."""
    fp = frames_path_for(video_path)
    payload = {"video": os.path.basename(video_path),
               "frames": _normalize(frames)}
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, fp)
    return fp


def state_dict(state):
    vp = state.get("video_path")
    if not vp:
        return {"has_video": False, "video_path": None,
                "video_name": None, "frames": []}
    return {"has_video": True, "video_path": vp,
            "video_name": os.path.basename(vp), "frames": load_frames(vp)}


def create_app(video_path=None):
    here = os.path.dirname(os.path.abspath(__file__))
    app = Flask(__name__, static_folder=os.path.join(here, "static"),
                static_url_path="/static")
    state = {"video_path": os.path.abspath(video_path) if video_path else None}

    @app.get("/")
    def index():
        return send_file(os.path.join(app.static_folder, "index.html"))

    @app.get("/api/state")
    def api_state():
        return jsonify(state_dict(state))

    @app.get("/api/video")
    def api_video():
        vp = state.get("video_path")
        if not vp or not os.path.exists(vp):
            abort(404)
        return send_file(vp, conditional=True)

    @app.post("/api/frames")
    def api_frames():
        vp = state.get("video_path")
        if not vp:
            return jsonify({"error": "no video loaded"}), 400
        body = request.get_json(silent=True) or {}
        try:
            save_frames(vp, body.get("frames", []))
        except (OSError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify({"frames": load_frames(vp)})

    @app.get("/api/browse")
    def api_browse():
        path = request.args.get("path")
        if not path:
            vp = state.get("video_path")
            path = os.path.dirname(vp) if vp else os.getcwd()
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(path):
            return jsonify({"error": "not a directory: %s" % path}), 400
        dirs, files = [], []
        try:
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                if os.path.isdir(full):
                    dirs.append(name)
                else:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in VIDEO_EXTS or ext == ".json":
                        files.append(name)
        except OSError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"path": path, "parent": os.path.dirname(path),
                        "dirs": dirs, "files": files})

    @app.post("/api/open")
    def api_open():
        body = request.get_json(silent=True) or {}
        path = body.get("path")
        if not path:
            return jsonify({"error": "missing path"}), 400
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path):
            return jsonify({"error": "not a file: %s" % path}), 400
        state["video_path"] = path
        return jsonify(state_dict(state))

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd video-meeting/bin/video-processor && .venv/bin/python -m unittest tests.test_server -v
```
Expected: PASS (all tests OK).

- [ ] **Step 5: Commit**

```bash
git add video-meeting/bin/video-processor/video_processor/server.py \
        video-meeting/bin/video-processor/tests/test_server.py
git commit -m "feat: add flask server with frames load/save, browse, open, range video"
```

---

## Task 4: CLI entry point (`__main__.py`)

**Files:**
- Create: `video-meeting/bin/video-processor/video_processor/__main__.py`

- [ ] **Step 1: Write `__main__.py`**

File: `video-meeting/bin/video-processor/video_processor/__main__.py`

```python
"""CLI entry: parse optional video path, find a free port, launch, open browser."""
import argparse
import os
import socket
import threading
import webbrowser

from .server import create_app


def find_free_port(start=8000, end=8100):
    """Return the first bindable port on 127.0.0.1 in [start, end)."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port in range %d-%d" % (start, end))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="video-processor",
        description="Mark, label, and re-seek frames in a meeting video.")
    parser.add_argument("video", nargs="?",
                        help="path to a video file to open on launch")
    args = parser.parse_args(argv)

    video_path = os.path.abspath(args.video) if args.video else None
    app = create_app(video_path)
    port = find_free_port()
    url = "http://127.0.0.1:%d/" % port
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print("video-processor running at %s  (Ctrl-C to stop)" % url)
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the port finder and import**

Run:
```bash
cd video-meeting/bin/video-processor && .venv/bin/python -c "from video_processor.__main__ import find_free_port; p=find_free_port(); print('free port:', p); assert 8000 <= p < 8100"
```
Expected: prints a free port between 8000 and 8100, no assertion error.

- [ ] **Step 3: Commit**

```bash
git add video-meeting/bin/video-processor/video_processor/__main__.py
git commit -m "feat: add CLI entry with free-port selection and browser launch"
```

---

## Task 5: Frontend — page, styles, and UI logic

**Files:**
- Create: `video-meeting/bin/video-processor/video_processor/static/index.html`
- Create: `video-meeting/bin/video-processor/video_processor/static/style.css`
- Create: `video-meeting/bin/video-processor/video_processor/static/app.js`

- [ ] **Step 1: Write `index.html`**

File: `video-meeting/bin/video-processor/video_processor/static/index.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>video-processor</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header>
    <span id="video-name">No video loaded</span>
    <button id="open-btn" type="button">Open…</button>
  </header>
  <main>
    <section id="player">
      <video id="video" controls></video>
      <div class="controls">
        <span id="time-readout">00:00 (sec 0)</span>
        <form id="goto-form">
          <input id="goto-input" type="text"
                 placeholder="mm:ss, hh:mm:ss or sec N" autocomplete="off">
          <button type="submit">Go to</button>
        </form>
        <button id="mark-btn" type="button">Mark frame</button>
        <span id="goto-error" class="error"></span>
      </div>
      <p class="hint">Tip: click the video to mark the current moment.</p>
    </section>
    <aside id="frames">
      <div class="frames-head">
        <h2>Frames</h2>
        <button id="save-btn" type="button">Save</button>
        <span id="save-status"></span>
      </div>
      <ul id="frames-list"></ul>
    </aside>
  </main>
  <div id="browse-modal" class="hidden">
    <div class="browse-box">
      <div class="browse-path" id="browse-path"></div>
      <ul id="browse-list"></ul>
      <button id="browse-close" type="button">Close</button>
    </div>
  </div>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `style.css`**

File: `video-meeting/bin/video-processor/video_processor/static/style.css`

```css
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, sans-serif;
  color: #1c1c1c;
  background: #f4f4f5;
}
header {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.6rem 1rem;
  background: #222;
  color: #fff;
}
header #video-name { font-weight: 600; }
header button { margin-left: auto; }
main {
  display: flex;
  gap: 1rem;
  padding: 1rem;
  align-items: flex-start;
}
#player { flex: 1 1 auto; min-width: 0; }
#player video { width: 100%; max-height: 60vh; background: #000; border-radius: 6px; }
.controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.6rem;
  flex-wrap: wrap;
}
#time-readout { font-variant-numeric: tabular-nums; min-width: 9rem; }
.hint { color: #777; font-size: 0.85rem; }
.error { color: #c0392b; font-size: 0.85rem; }
#frames {
  flex: 0 0 22rem;
  background: #fff;
  border-radius: 6px;
  padding: 0.75rem;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.frames-head { display: flex; align-items: center; gap: 0.5rem; }
.frames-head h2 { margin: 0; font-size: 1.1rem; flex: 1; }
#save-status { color: #2e7d32; font-size: 0.85rem; }
#frames-list { list-style: none; margin: 0.75rem 0 0; padding: 0; }
#frames-list li {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0;
  border-bottom: 1px solid #eee;
}
.frame-time {
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  background: #eef;
  border: 1px solid #ccd;
  border-radius: 4px;
  padding: 0.2rem 0.4rem;
}
.frame-label { flex: 1; min-width: 0; padding: 0.2rem; }
.frame-del { color: #c0392b; border: none; background: none; cursor: pointer; font-size: 1rem; }
.hidden { display: none; }
#browse-modal {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center;
}
.browse-box {
  background: #fff; border-radius: 8px; padding: 1rem;
  width: 32rem; max-height: 70vh; overflow: auto;
}
.browse-path { font-family: monospace; font-size: 0.85rem; color: #555; margin-bottom: 0.5rem; word-break: break-all; }
#browse-list { list-style: none; margin: 0 0 0.75rem; padding: 0; }
#browse-list li { padding: 0.3rem 0.4rem; cursor: pointer; border-radius: 4px; }
#browse-list li:hover { background: #eef; }
#browse-list li.dir { font-weight: 600; }
```

- [ ] **Step 3: Write `app.js`**

File: `video-meeting/bin/video-processor/video_processor/static/app.js`

```javascript
"use strict";

// --- timecode twin of video_processor/timecode.py ---
function parseTimecode(value) {
  let s = String(value).trim();
  if (!s) throw new Error("empty");
  if (s.toLowerCase().startsWith("sec")) {
    s = s.slice(3).trim();
    if (!s) throw new Error("empty");
  }
  const parts = s.split(":");
  if (parts.length > 3) throw new Error("too many ':'");
  const nums = parts.map((p) => {
    const n = Number(p);
    if (p.trim() === "" || Number.isNaN(n)) throw new Error("non-numeric");
    return n;
  });
  if (nums.some((n) => n < 0)) throw new Error("negative");
  if (nums.length === 1) return nums[0];
  if (nums.length === 2) return nums[0] * 60 + nums[1];
  return nums[0] * 3600 + nums[1] * 60 + nums[2];
}

function formatTimecode(seconds) {
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

// --- state ---
let frames = [];

const video = document.getElementById("video");
const framesList = document.getElementById("frames-list");
const timeReadout = document.getElementById("time-readout");
const gotoError = document.getElementById("goto-error");
const saveStatus = document.getElementById("save-status");
const modal = document.getElementById("browse-modal");
const browseList = document.getElementById("browse-list");
const browsePath = document.getElementById("browse-path");

function renderFrames() {
  frames.sort((a, b) => a.timestamp_s - b.timestamp_s);
  framesList.innerHTML = "";
  frames.forEach((fr, idx) => {
    const li = document.createElement("li");

    const t = document.createElement("button");
    t.className = "frame-time";
    t.type = "button";
    t.textContent = formatTimecode(fr.timestamp_s);
    t.addEventListener("click", () => { video.currentTime = fr.timestamp_s; });

    const label = document.createElement("input");
    label.className = "frame-label";
    label.type = "text";
    label.value = fr.label || "";
    label.placeholder = "label…";
    label.addEventListener("input", () => { frames[idx].label = label.value; });

    const del = document.createElement("button");
    del.className = "frame-del";
    del.type = "button";
    del.textContent = "✕";
    del.addEventListener("click", () => { frames.splice(idx, 1); renderFrames(); });

    li.append(t, label, del);
    framesList.appendChild(li);
  });
}

function addFrame(seconds) {
  frames.push({ timestamp_s: seconds, timestamp: formatTimecode(seconds), label: "" });
  renderFrames();
}

video.addEventListener("timeupdate", () => {
  timeReadout.textContent =
    `${formatTimecode(video.currentTime)} (sec ${Math.floor(video.currentTime)})`;
});
video.addEventListener("click", () => {
  if (video.src) addFrame(video.currentTime);
});

document.getElementById("mark-btn").addEventListener("click", () => {
  if (video.src) addFrame(video.currentTime);
});

document.getElementById("goto-form").addEventListener("submit", (e) => {
  e.preventDefault();
  gotoError.textContent = "";
  try {
    video.currentTime = parseTimecode(document.getElementById("goto-input").value);
  } catch (err) {
    gotoError.textContent = "Invalid time";
  }
});

document.getElementById("save-btn").addEventListener("click", async () => {
  saveStatus.textContent = "Saving…";
  try {
    const resp = await fetch("/api/frames", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frames }),
    });
    if (!resp.ok) throw new Error("save failed");
    const data = await resp.json();
    frames = data.frames;
    renderFrames();
    saveStatus.textContent = "Saved";
  } catch (err) {
    saveStatus.textContent = "Save failed";
  }
});

async function loadState() {
  const data = await (await fetch("/api/state")).json();
  document.getElementById("video-name").textContent =
    data.has_video ? data.video_name : "No video loaded";
  if (data.has_video) video.src = "/api/video?ts=" + Date.now();
  frames = data.frames || [];
  renderFrames();
}

// --- browse / open ---
async function browse(path) {
  const url = path ? `/api/browse?path=${encodeURIComponent(path)}` : "/api/browse";
  const data = await (await fetch(url)).json();
  if (data.error) return;
  browsePath.textContent = data.path;
  browseList.innerHTML = "";

  const up = document.createElement("li");
  up.textContent = ".. (up)";
  up.className = "dir";
  up.addEventListener("click", () => browse(data.parent));
  browseList.appendChild(up);

  data.dirs.forEach((d) => {
    const li = document.createElement("li");
    li.textContent = d + "/";
    li.className = "dir";
    li.addEventListener("click", () => browse(data.path + "/" + d));
    browseList.appendChild(li);
  });
  data.files.forEach((f) => {
    const li = document.createElement("li");
    li.textContent = f;
    li.className = "file";
    li.addEventListener("click", () => openVideo(data.path + "/" + f));
    browseList.appendChild(li);
  });
}

async function openVideo(path) {
  if (!/\.(mp4|mkv|mov|avi|webm|m4v)$/i.test(path)) return; // only videos open
  const resp = await fetch("/api/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (resp.ok) {
    modal.classList.add("hidden");
    await loadState();
  }
}

document.getElementById("open-btn").addEventListener("click", () => {
  modal.classList.remove("hidden");
  browse(null);
});
document.getElementById("browse-close").addEventListener("click",
  () => modal.classList.add("hidden"));

loadState();
```

- [ ] **Step 4: Add a smoke test that `/` serves the page and references the assets**

Append to `video-meeting/bin/video-processor/tests/test_server.py` inside class `ServerTests`:

```python
    def test_index_served(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"video-processor", resp.data)
        self.assertIn(b"/static/app.js", resp.data)

    def test_static_assets_served(self):
        for asset in ("/static/app.js", "/static/style.css"):
            resp = self.client.get(asset)
            self.assertEqual(resp.status_code, 200, asset)
```

- [ ] **Step 5: Run the full test suite**

Run:
```bash
cd video-meeting/bin/video-processor && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```
Expected: PASS — all timecode and server tests, including the two new asset tests.

- [ ] **Step 6: Commit**

```bash
git add video-meeting/bin/video-processor/video_processor/static/ \
        video-meeting/bin/video-processor/tests/test_server.py
git commit -m "feat: add frontend page, styles, UI logic, and asset smoke tests"
```

---

## Task 6: Manual end-to-end verification + README

**Files:**
- Create: `video-meeting/bin/video-processor/README.md`

- [ ] **Step 1: Launch against a real video and verify in the browser**

Run (replace with a real file you have):
```bash
cd video-meeting/bin/video-processor && .venv/bin/video-processor /path/to/some.mp4
```
Expected, in the opened browser tab:
- Video loads and plays; scrubber seeks (Range working).
- "Go to" accepts `01:10`, `sec 70`, and `70` — each seeks correctly.
- Clicking the video and "Mark frame" both add a time-ordered entry.
- Clicking an entry's time seeks to it; editing a label persists in the list; ✕ deletes it.
- "Save" writes `/path/to/some-frames.json`; relaunching reloads those frames.
- "Open…" browses the filesystem and switches videos, auto-loading sibling frames.

Stop with Ctrl-C.

- [ ] **Step 2: Write `README.md`**

File: `video-meeting/bin/video-processor/README.md`

```markdown
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
    {"timestamp_s": 70.0, "timestamp": "01:10", "label": "Architecture slide"}
  ]
}
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```
```

- [ ] **Step 3: Commit**

```bash
git add video-meeting/bin/video-processor/README.md
git commit -m "docs: add video-processor README"
```

---

## Notes / follow-ups (not blocking)

- `package.sh` currently excludes `__pycache__`, `config.yaml`, and token files
  but not `.venv/`. If `bin/video-processor` is ever included in the packaged
  skill bundle, add `.venv` to the package exclusions so the per-tool venv does
  not bloat `video-meeting.skill`. Out of scope for this plan — flag to the user.
```
