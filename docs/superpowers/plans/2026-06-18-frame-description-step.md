# Frame-description Step + Upgrade-safe Config — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in pipeline step that grabs video frames at user-given timestamps, describes each with a local Ollama vision model, and writes `frames/`, `video-frames-details.json`, and `video-frames-summary.md` — plus make config upgrade-safe (new keys never break old configs; externalize a few tunables; non-destructive config migration).

**Architecture:** Two new stdlib-first scripts (`extract_frames.py` = ffmpeg; `describe_frames.py` = Ollama vision + text summary) run as a gated sub-stage inside `run.py` only when `--frames` is supplied. The feature is standalone — `meeting_record.json` and existing artifacts are untouched. A new `migrate_config.py` appends missing config keys non-destructively; `preflight.py` warns on drift; `install.sh --migrate-config` wires it up and ensures the vision model is pulled.

**Tech Stack:** Python 3 stdlib, ffmpeg, Ollama HTTP (`/api/generate` with `images`), PyYAML (already required by `config_get.py`), stdlib `unittest`.

---

## Conventions (read before starting)

- Scripts are **stdlib-first**, invoked by absolute interpreter paths from config. New scripts run under the **system `python3`** (`sys.executable` in `run.py`) — no GPU, no venv.
- Reuse, don't duplicate: `describe_frames.py` imports `generate`/`parse_json_loose` from `ollama_client` and `chunk_text`/`fill`/`language_phrase`/`load_template` from `summarize` (same as `extract_tasks.py` does).
- Every new config value is read via `get(cfg, "<dotted>", DEFAULT)` where DEFAULT equals the value in `config.example.yaml`, so an older `config.yaml` runs on built-in defaults.
- Tests: stdlib `unittest`, `import fixtures as F`, `sys.path.insert(0, F.SCRIPTS)`, skip cleanly when ffmpeg/Ollama are absent. Run the suite with:
  `bash video-meeting/tests/run_tests.sh`
- **Working directory** for all `python3 -m unittest` commands is `video-meeting/` (the tests dir is `video-meeting/tests`).
- **CRITICAL YAML fact:** `config_get.py` uses `yaml.safe_load`, where **duplicate top-level keys are last-wins for the entire mapping** (`a:\n x:1\na:\n y:2` → `{a:{y:2}}`, `x` lost). Therefore `migrate_config.py` must **insert** new leaves under an existing parent block in the raw text — never append a second `parent:` block.

## File Structure

New files:
- `video-meeting/scripts/extract_frames.py` — ffmpeg frame grab + manifest (pure helpers: `parse_timestamp`, `slide_id`, `build_manifest`).
- `video-meeting/scripts/describe_frames.py` — Ollama vision description + text summary (pure helpers: `build_details`, `render_digest_md`, `truncate`).
- `video-meeting/scripts/migrate_config.py` — non-destructive config key migration (pure helpers: `flatten`, `build_missing_tree`, `top_block_child_end`, `render_insert`).
- `video-meeting/templates/frame_prompts/describe.md` — per-frame prompt.
- `video-meeting/templates/frame_prompts/summary.md` — overall digest→summary prompt.
- `video-meeting/tests/test_frames.py` — frames logic tests.
- `video-meeting/tests/test_migrate_config.py` — migration tests.

Modified files:
- `video-meeting/scripts/ollama_client.py` — optional `images` (additive).
- `video-meeting/scripts/run.py` — `--frames` flag, gated frames block, pass `summary_max_chunk_chars`.
- `video-meeting/scripts/preflight.py` — config-drift warning + vision-model presence.
- `video-meeting/install.sh` — `--migrate-config` mode + ensure vision model pulled.
- `video-meeting/config.example.yaml` — new `ollama.*`, `frames.*`, vision model in `install.ollama_models`.
- `video-meeting/tests/test_offline.py` — extend `TestRunWiring` key list.
- `video-meeting/tests/test_cli.py` — add new scripts to `ALL_SCRIPTS`.
- `video-meeting/SKILL.md`, `video-meeting/references/install.md`, `video-meeting/references/design.md` — docs.

---

## Task 0: Git bootstrap (optional — skip if you don't want git here)

This repo is **not** currently a git repository. The plan uses a commit per task. If you want that cadence, initialize git on a feature branch. If the user prefers no git, **skip this task and ignore every "Commit" step below.**

**Files:** none (repo metadata only)

- [ ] **Step 1: Initialize git on a feature branch**

Run (from the repo root `/home/xalperte/Personal/code/skills/video-meeting-skill`):
```bash
git init -q && git add -A && git commit -q -m "chore: baseline before frame-description step" && git checkout -q -b feature/frame-description-step
```
Expected: a feature branch `feature/frame-description-step`. Do NOT push (local only, per user's git rules).

---

## Task 1: `ollama_client` — optional image support (additive)

**Files:**
- Modify: `video-meeting/scripts/ollama_client.py`
- Test: `video-meeting/tests/test_frames.py` (created here)

- [ ] **Step 1: Write the failing test**

Create `video-meeting/tests/test_frames.py`:
```python
"""Frame-step logic tests — stdlib only; ffmpeg/Ollama parts skip when absent."""
import os
import sys
import unittest

import fixtures as F

sys.path.insert(0, F.SCRIPTS)


class TestOllamaImages(unittest.TestCase):
    def test_images_included_only_when_present(self):
        from ollama_client import build_payload
        p = build_payload("v", "describe", images=["BASE64DATA"])
        self.assertEqual(p["images"], ["BASE64DATA"])
        p2 = build_payload("v", "describe")
        self.assertNotIn("images", p2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd video-meeting && python3 -m unittest tests.test_frames.TestOllamaImages -v`
Expected: FAIL — `build_payload() got an unexpected keyword argument 'images'`.

- [ ] **Step 3: Add `images` to `build_payload` and `generate`**

In `video-meeting/scripts/ollama_client.py`, change the `build_payload` signature and body:
```python
def build_payload(model, prompt, system=None, options=None, fmt=None, images=None):
    """Assemble the /api/generate request body.

    `think` is always disabled: thinking models (e.g. qwen3.x) otherwise put
    their output in the `thinking` field and return an empty `response`.
    Non-thinking models and older Ollama versions ignore the field.
    `images` (a list of base64-encoded image strings) is included only for
    vision models; omitted entirely when not provided.
    """
    payload = {"model": model, "prompt": prompt, "stream": False, "think": False}
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options
    if fmt:
        payload["format"] = fmt
    if images:
        payload["images"] = images
    return payload
```
And update `generate` to accept and forward `images`:
```python
def generate(host, model, prompt, system=None, options=None, fmt=None, images=None, timeout=900):
    """Call /api/generate (non-streaming) and return the response text."""
    url = host.rstrip("/") + "/api/generate"
    payload = build_payload(model, prompt, system=system, options=options, fmt=fmt, images=images)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        sys.exit(f"Ollama request failed ({url}): {exc}")
    if "error" in body:
        sys.exit(f"Ollama error: {body['error']}")
    return body.get("response", "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd video-meeting && python3 -m unittest tests.test_frames.TestOllamaImages -v`
Expected: PASS. Also confirm no regression: `python3 -m unittest tests.test_offline.TestGeneratePayload -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add video-meeting/scripts/ollama_client.py video-meeting/tests/test_frames.py
git commit -m "feat(ollama): optional images arg for vision models"
```

---

## Task 2: `extract_frames.py` — pure helpers (timestamp, slide id, manifest)

**Files:**
- Create: `video-meeting/scripts/extract_frames.py`
- Test: `video-meeting/tests/test_frames.py`

- [ ] **Step 1: Write the failing test**

Append to `video-meeting/tests/test_frames.py` (before the `if __name__` block):
```python
class TestTimestampParsing(unittest.TestCase):
    def test_formats(self):
        import extract_frames as E
        self.assertEqual(E.parse_timestamp("10:20"), 620)       # mm:ss
        self.assertEqual(E.parse_timestamp("01:10:23"), 4223)   # hh:mm:ss
        self.assertEqual(E.parse_timestamp("90"), 90)           # bare seconds
        self.assertEqual(E.parse_timestamp("0:05"), 5)

    def test_rejects_bad(self):
        import extract_frames as E
        for bad in ("1:2:3:4", "aa:bb", "-5", "", "10:xx"):
            with self.assertRaises(ValueError, msg=bad):
                E.parse_timestamp(bad)


class TestSlideIdAndManifest(unittest.TestCase):
    def test_slide_id(self):
        import extract_frames as E
        self.assertEqual(E.slide_id(1), "slide-0001")
        self.assertEqual(E.slide_id(42), "slide-0042")

    def test_build_manifest_order_and_shape(self):
        import extract_frames as E
        m = E.build_manifest("/x/meeting.mp4", ["10:20", "01:10:23"], image_format="png")
        self.assertEqual(m["image_format"], "png")
        self.assertEqual([f["slide"] for f in m["frames"]], ["slide-0001", "slide-0002"])
        self.assertEqual(m["frames"][0]["timestamp"], "10:20")
        self.assertEqual(m["frames"][0]["timestamp_s"], 620)
        self.assertEqual(m["frames"][0]["image"], "frames/slide-0001.png")
        self.assertEqual(m["frames"][1]["timestamp_s"], 4223)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd video-meeting && python3 -m unittest tests.test_frames.TestTimestampParsing tests.test_frames.TestSlideIdAndManifest -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'extract_frames'`.

- [ ] **Step 3: Create `extract_frames.py` with the helpers + main**

Create `video-meeting/scripts/extract_frames.py`:
```python
#!/usr/bin/env python3
"""
Optional stage — grab single video frames at given timestamps (ffmpeg).

Pure stdlib + ffmpeg, so it runs with the system python3 (no venv). Used only
when the user asks to process specific moments (e.g. a shared presentation).
Writes frames/slide-NNNN.<ext> into the meeting folder and a manifest the
describe step consumes. The vision description happens in describe_frames.py.

Timestamps: "mm:ss" (one colon) or "hh:mm:ss" (two colons); a bare number is
seconds. Order is preserved — the i-th timestamp becomes slide-000i.

Usage:
  extract_frames.py --video meeting.mp4 --out-dir <meeting_dir> \
      --manifest <meeting_dir>/frames_manifest.json [--image-format png] \
      10:20 15:10 32:30 46:00 01:10:23
"""
import argparse
import json
import os
import subprocess
import sys


def parse_timestamp(value):
    """'mm:ss' | 'hh:mm:ss' | bare seconds -> int/float seconds. Raises ValueError."""
    s = str(value).strip()
    if not s:
        raise ValueError("empty timestamp")
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(f"too many ':' in timestamp: {value!r}")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"non-numeric timestamp: {value!r}")
    if any(n < 0 for n in nums):
        raise ValueError(f"negative timestamp: {value!r}")
    if len(parts) == 1:
        secs = nums[0]
    elif len(parts) == 2:
        secs = nums[0] * 60 + nums[1]
    else:
        secs = nums[0] * 3600 + nums[1] * 60 + nums[2]
    return int(secs) if float(secs).is_integer() else secs


def slide_id(index):
    """1-based index -> 'slide-0001'."""
    return f"slide-{index:04d}"


def build_manifest(video, timestamps, image_format="png"):
    """Build the (pure, no-ffmpeg) manifest. Image paths are relative to the
    meeting folder so the JSON stays portable."""
    frames = []
    for i, ts in enumerate(timestamps, 1):
        sid = slide_id(i)
        frames.append({
            "slide": sid,
            "timestamp": str(ts).strip(),
            "timestamp_s": parse_timestamp(ts),
            "image": f"frames/{sid}.{image_format}",
        })
    return {
        "video": os.path.abspath(video),
        "image_format": image_format,
        "frames": frames,
    }


def extract_one(ffmpeg, video, seconds, out_path, image_format, jpeg_quality):
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-ss", str(seconds), "-i", video,
           "-frames:v", "1"]
    if image_format in ("jpg", "jpeg"):
        cmd += ["-q:v", str(jpeg_quality)]
    cmd += [out_path]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0 or not os.path.isfile(out_path):
        sys.stderr.write(p.stderr)
        sys.exit(f"ffmpeg failed to extract a frame at {seconds}s "
                 f"(past end of video?) -> {out_path}")


def main():
    ap = argparse.ArgumentParser(description="Grab video frames at timestamps (ffmpeg).")
    ap.add_argument("--video", required=True)
    ap.add_argument("--out-dir", required=True, help="meeting folder; frames/ created inside")
    ap.add_argument("--manifest", required=True, help="output manifest JSON path")
    ap.add_argument("--image-format", default="png", choices=["png", "jpg", "jpeg"])
    ap.add_argument("--jpeg-quality", type=int, default=2)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("timestamps", nargs="+", help="mm:ss or hh:mm:ss, in order")
    args = ap.parse_args()

    if not os.path.isfile(args.video):
        sys.exit(f"video not found: {args.video}")

    manifest = build_manifest(args.video, args.timestamps, args.image_format)
    frames_dir = os.path.join(args.out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    for fr in manifest["frames"]:
        out_path = os.path.join(args.out_dir, fr["image"])
        extract_one(args.ffmpeg, args.video, fr["timestamp_s"], out_path,
                    args.image_format, args.jpeg_quality)
        sys.stderr.write(f"  {fr['slide']} @ {fr['timestamp']} -> {fr['image']}\n")

    os.makedirs(os.path.dirname(os.path.abspath(args.manifest)) or ".", exist_ok=True)
    with open(args.manifest, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    sys.stderr.write(f"  wrote manifest ({len(manifest['frames'])} frames) -> {args.manifest}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd video-meeting && python3 -m unittest tests.test_frames.TestTimestampParsing tests.test_frames.TestSlideIdAndManifest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add video-meeting/scripts/extract_frames.py video-meeting/tests/test_frames.py
git commit -m "feat(frames): extract_frames.py — timestamps, slide ids, manifest"
```

---

## Task 3: `extract_frames.py` — ffmpeg integration test

**Files:**
- Test: `video-meeting/tests/test_frames.py`

- [ ] **Step 1: Write the failing test**

Append to `video-meeting/tests/test_frames.py`:
```python
import shutil
import subprocess
import tempfile


class TestExtractFramesFfmpeg(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_extract_two_frames(self):
        with tempfile.TemporaryDirectory() as d:
            mp4 = os.path.join(d, "v.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=4",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                 "-shortest", mp4], check=True)
            manifest = os.path.join(d, "frames_manifest.json")
            p = subprocess.run(
                [sys.executable, os.path.join(F.SCRIPTS, "extract_frames.py"),
                 "--video", mp4, "--out-dir", d, "--manifest", manifest,
                 "0:01", "0:03"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(os.path.isfile(os.path.join(d, "frames", "slide-0001.png")))
            self.assertTrue(os.path.isfile(os.path.join(d, "frames", "slide-0002.png")))
            m = F.read_json(manifest)
            self.assertEqual(len(m["frames"]), 2)
            self.assertEqual(m["frames"][1]["timestamp_s"], 3)
```

- [ ] **Step 2: Run test to verify it fails or skips, then passes**

Run: `cd video-meeting && python3 -m unittest tests.test_frames.TestExtractFramesFfmpeg -v`
Expected: PASS if ffmpeg present (the implementation from Task 2 already supports this); SKIP if ffmpeg absent. (No code change needed — this test guards the wiring.)

- [ ] **Step 3: Commit**

```bash
git add video-meeting/tests/test_frames.py
git commit -m "test(frames): ffmpeg integration for extract_frames"
```

---

## Task 4: Frame prompt templates

**Files:**
- Create: `video-meeting/templates/frame_prompts/describe.md`
- Create: `video-meeting/templates/frame_prompts/summary.md`

- [ ] **Step 1: Create `describe.md`**

Create `video-meeting/templates/frame_prompts/describe.md`:
```
You are analyzing a single still frame captured from a meeting recording, taken at __TIMESTAMP__. The frame usually shows a shared screen — a slide, document, diagram, chart, or application.

Describe the meaningful content of this frame so a reader who did not see it understands what was on screen and what it conveys. Transcribe visible text faithfully (titles, bullet points, labels, numbers). For diagrams or charts, explain what they depict and the key relationships or values. Ignore meeting-UI chrome (webcam tiles, toolbars, cursors) unless it carries information.

If the frame shows no meaningful shared content (e.g. only webcam video or a blank screen), say so in one short sentence.

Write the description in this language: __LANGUAGE__. Output only the description — no preamble, no markdown headings.
```

- [ ] **Step 2: Create `summary.md`**

Create `video-meeting/templates/frame_prompts/summary.md`:
```
Below are descriptions of frames captured from a shared presentation during a meeting, in chronological order. Each is labeled with its slide id and timestamp.

Write a coherent summary in Markdown of the presentation's content: the overall topic/thesis, the key points in order, and any notable data, diagrams, or conclusions. Use short sections and bullet points. Reference slide timestamps where useful so claims stay traceable. Base everything strictly on the descriptions below — do not invent content.

Write ALL output in this language: __LANGUAGE__.

Frame descriptions:
__CONTENT__
```

- [ ] **Step 3: Commit**

```bash
git add video-meeting/templates/frame_prompts/
git commit -m "feat(frames): per-frame + summary prompt templates"
```

---

## Task 5: `describe_frames.py` — pure helpers + Ollama wiring

**Files:**
- Create: `video-meeting/scripts/describe_frames.py`
- Test: `video-meeting/tests/test_frames.py`

- [ ] **Step 1: Write the failing test**

Append to `video-meeting/tests/test_frames.py`:
```python
class TestDescribeHelpers(unittest.TestCase):
    def _manifest(self):
        return {
            "video": "/abs/meeting.mp4",
            "image_format": "png",
            "frames": [
                {"slide": "slide-0001", "timestamp": "10:20", "timestamp_s": 620,
                 "image": "frames/slide-0001.png"},
                {"slide": "slide-0002", "timestamp": "15:10", "timestamp_s": 910,
                 "image": "frames/slide-0002.png"},
            ],
        }

    def test_build_details_shape(self):
        import describe_frames as D
        det = D.build_details(self._manifest(),
                              {"slide-0001": "Title slide about Q3 plan",
                               "slide-0002": "Architecture diagram with 3 services"},
                              vision_model="chandra-ocr-2", output_language="English")
        self.assertEqual(det["video"], "meeting.mp4")        # basename only
        self.assertEqual(det["vision_model"], "chandra-ocr-2")
        self.assertEqual(len(det["frames"]), 2)
        self.assertEqual(det["frames"][0]["slide"], "slide-0001")
        self.assertEqual(det["frames"][0]["image"], "frames/slide-0001.png")
        self.assertEqual(det["frames"][1]["text"], "Architecture diagram with 3 services")

    def test_missing_description_is_empty_string(self):
        import describe_frames as D
        det = D.build_details(self._manifest(), {"slide-0001": "x"},
                              vision_model="m", output_language="English")
        self.assertEqual(det["frames"][1]["text"], "")

    def test_render_digest_md(self):
        import describe_frames as D
        det = D.build_details(self._manifest(),
                              {"slide-0001": "A", "slide-0002": "B"}, "m", "English")
        md = D.render_digest_md(det)
        self.assertIn("## slide-0001 [10:20]", md)
        self.assertIn("A", md)
        self.assertIn("## slide-0002 [15:10]", md)

    def test_truncate(self):
        import describe_frames as D
        self.assertEqual(D.truncate("abc", 10), "abc")
        self.assertTrue(D.truncate("a" * 100, 10).endswith("…"))
        self.assertLessEqual(len(D.truncate("a" * 100, 10)), 11)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd video-meeting && python3 -m unittest tests.test_frames.TestDescribeHelpers -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'describe_frames'`.

- [ ] **Step 3: Create `describe_frames.py`**

Create `video-meeting/scripts/describe_frames.py`:
```python
#!/usr/bin/env python3
"""
Optional stage — describe extracted frames with a local Ollama vision model,
then summarize all descriptions into a markdown digest.

Stdlib only; reuses ollama_client (HTTP) and summarize helpers. Runs with the
system python3. Reads the manifest written by extract_frames.py; never calls
ffmpeg itself. Vision and text-summary models never co-reside — Ollama's
keep_alive=0s unloads one before the next loads.

Outputs (into the meeting folder):
  video-frames-details.json  -> {video, vision_model, output_language, frames:[
                                  {slide, timestamp, timestamp_s, image, text}]}
  video-frames-summary.md    -> markdown summary of the shared presentation
"""
import argparse
import base64
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ollama_client import generate  # noqa: E402
from summarize import chunk_text, fill, language_phrase, load_template  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATES = os.path.normpath(os.path.join(HERE, "..", "templates"))


def truncate(text, max_chars):
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def build_details(manifest, descriptions, vision_model, output_language):
    """Combine the manifest with {slide: text} into the details document."""
    frames = []
    for fr in manifest.get("frames", []):
        frames.append({
            "slide": fr["slide"],
            "timestamp": fr["timestamp"],
            "timestamp_s": fr["timestamp_s"],
            "image": fr["image"],
            "text": (descriptions.get(fr["slide"], "") or "").strip(),
        })
    return {
        "video": os.path.basename(manifest.get("video", "")),
        "vision_model": vision_model,
        "output_language": output_language,
        "frames": frames,
    }


def render_digest_md(details):
    """Markdown of per-slide descriptions, fed to the summary model."""
    lines = []
    for fr in details["frames"]:
        lines.append(f"## {fr['slide']} [{fr['timestamp']}]")
        lines.append(fr["text"] or "(no meaningful shared content)")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def encode_image(path):
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def ensure_model(host, model):
    """Fail fast (with the pull command) if the vision model isn't present."""
    url = host.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            names = {m.get("name", "") for m in json.loads(resp.read()).get("models", [])}
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Ollama unreachable at {host}: {exc}")
    base = model.split(":")[0]
    if not any(n == model or n.split(":")[0] == base for n in names):
        sys.exit(f"vision model not pulled: {model}\n  run: ollama pull {model}")


def summarize_digest(host, model, digest, lang, options, max_chunk_chars, templates_dir):
    tpl = load_template(templates_dir, "frame_prompts", "summary.md")
    chunks = chunk_text(digest, max_chunk_chars)
    parts = [generate(host, model, fill(tpl, {"__LANGUAGE__": lang, "__CONTENT__": ch}),
                      options=options) for ch in chunks]
    if len(parts) > 1:
        combined = "\n\n".join(parts)
        return generate(host, model,
                        fill(tpl, {"__LANGUAGE__": lang, "__CONTENT__": combined}),
                        options=options)
    return parts[0]


def main():
    ap = argparse.ArgumentParser(description="Describe + summarize frames via Ollama.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--base-dir", default=None,
                    help="folder image paths are relative to (default: manifest dir)")
    ap.add_argument("--out-details", required=True)
    ap.add_argument("--out-summary", required=True)
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--vision-model", default="chandra-ocr-2")
    ap.add_argument("--summary-model", default="gemma4:12b")
    ap.add_argument("--output-language", default="auto")
    ap.add_argument("--num-ctx", type=int, default=65536)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--describe-max-chars", type=int, default=4000)
    ap.add_argument("--max-chunk-chars", type=int, default=24000)
    ap.add_argument("--templates-dir", default=DEFAULT_TEMPLATES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.manifest):
        sys.exit(f"manifest not found: {args.manifest}")
    with open(args.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    base_dir = args.base_dir or os.path.dirname(os.path.abspath(args.manifest))
    lang = language_phrase(args.output_language)
    options = {"num_ctx": args.num_ctx, "temperature": args.temperature}
    describe_tpl = load_template(args.templates_dir, "frame_prompts", "describe.md")

    if args.dry_run:
        print(f"(frames: {len(manifest.get('frames', []))})")
        print("===== DESCRIBE PROMPT (slide-0001) =====")
        print(fill(describe_tpl, {"__TIMESTAMP__": manifest["frames"][0]["timestamp"],
                                  "__LANGUAGE__": lang}))
        return

    ensure_model(args.host, args.vision_model)

    descriptions = {}
    for fr in manifest.get("frames", []):
        img_path = os.path.join(base_dir, fr["image"])
        if not os.path.isfile(img_path):
            sys.exit(f"frame image missing: {img_path}")
        sys.stderr.write(f"  describing {fr['slide']} @ {fr['timestamp']}…\n")
        prompt = fill(describe_tpl, {"__TIMESTAMP__": fr["timestamp"], "__LANGUAGE__": lang})
        raw = generate(args.host, args.vision_model, prompt, options=options,
                       images=[encode_image(img_path)])
        descriptions[fr["slide"]] = truncate(raw, args.describe_max_chars)

    details = build_details(manifest, descriptions, args.vision_model, args.output_language)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_details)) or ".", exist_ok=True)
    with open(args.out_details, "w", encoding="utf-8") as fh:
        json.dump(details, fh, ensure_ascii=False, indent=2)

    sys.stderr.write("  summarizing frames…\n")
    summary_md = summarize_digest(args.host, args.summary_model, render_digest_md(details),
                                  lang, options, args.max_chunk_chars, args.templates_dir)
    with open(args.out_summary, "w", encoding="utf-8") as fh:
        fh.write(summary_md.rstrip() + "\n")
    sys.stderr.write(f"  done -> {args.out_details}, {args.out_summary}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd video-meeting && python3 -m unittest tests.test_frames.TestDescribeHelpers -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add video-meeting/scripts/describe_frames.py video-meeting/tests/test_frames.py
git commit -m "feat(frames): describe_frames.py — vision description + summary"
```

---

## Task 6: Config keys + `TestRunWiring` extension

**Files:**
- Modify: `video-meeting/config.example.yaml`
- Modify: `video-meeting/tests/test_offline.py:168-176` (the `keys` list in `TestRunWiring`)

- [ ] **Step 1: Write the failing test**

In `video-meeting/tests/test_offline.py`, extend the `keys` list inside `TestRunWiring.test_helpers_and_config_keys` to include the new keys. Replace the existing list literal with:
```python
        keys = ["paths.meetings_dir", "paths.work_dir", "paths.global_dir",
                "env.ffmpeg_bin", "env.whisper.python", "env.pyannote.python",
                "env.render.python", "env.cuda.visible_devices",
                "speaker_id.thresholds.high", "speaker_id.thresholds.low",
                "ollama.host", "ollama.num_ctx", "ollama.summary_model",
                "ollama.tasks_model", "ollama.vision_model",
                "ollama.summary_max_chunk_chars",
                "frames.image_format", "frames.describe_max_chars",
                "frames.frames_summary_max_chunk_chars",
                "rendering.slides.formats", "context_defaults"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd video-meeting && python3 -m unittest tests.test_offline.TestRunWiring -v`
Expected: FAIL — assertion lists the new keys as missing from `config.example.yaml`.

- [ ] **Step 3: Add the keys to `config.example.yaml`**

In `video-meeting/config.example.yaml`, inside the `ollama:` block, after the `temperature: 0.2` line, add:
```yaml
  summary_max_chunk_chars: 24000      # map-reduce threshold for summarize.py
                                      # (was a script default; here so it survives upgrades)
  vision_model: "chandra-ocr-2"        # local VLM for the optional frame-description step
```

After the `ollama:` block (before `# ---- Speaker recognition`), add a new top-level block:
```yaml
# ----------------------------------------------------------------------------
# Optional frame description (only runs when a run passes specific timestamps)
# ----------------------------------------------------------------------------
frames:
  image_format: "png"                  # png | jpg
  jpeg_quality: 2                       # ffmpeg -q:v when image_format is jpg
  describe_max_chars: 4000              # cap per-frame description length
  frames_summary_max_chunk_chars: 24000 # map-reduce threshold for the frames digest
```

In the `install:` block, change `ollama_models` to include the vision model:
```yaml
  ollama_models: ["gemma4:12b", "qwen3.5:9b", "chandra-ocr-2"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd video-meeting && python3 -m unittest tests.test_offline.TestRunWiring -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add video-meeting/config.example.yaml video-meeting/tests/test_offline.py
git commit -m "feat(config): vision_model, frames.*, summary_max_chunk_chars keys"
```

---

## Task 7: Wire the frames stage into `run.py`

**Files:**
- Modify: `video-meeting/scripts/run.py` (argparse ~line 138; summarize call ~line 259-265; new block after task extraction ~line 278; produced list ~line 293)

- [ ] **Step 1: Add the `--frames` argument**

In `video-meeting/scripts/run.py`, in `main()`'s argparse section, after the `--artifacts` line add:
```python
    ap.add_argument("--frames", nargs="*", default=None,
                    help="timestamps (mm:ss or hh:mm:ss) to capture + describe frames")
```

- [ ] **Step 2: Pass `summary_max_chunk_chars` to summarize**

In the summarize stage (the `run_stage([... "summarize.py" ...])` call), add this to the argument list (e.g. after `--temperature`, `temp`):
```python
                   "--max-chunk-chars",
                   str(get(cfg, "ollama.summary_max_chunk_chars", 24000)),
```

- [ ] **Step 3: Add the gated frames block after task extraction**

In `video-meeting/scripts/run.py`, immediately after the `# ---- 7. extract tasks` block (after its closing `run_stage(ecmd)`), insert:
```python
    # ---- 7b. frames (optional: only when timestamps were given) ------------ #
    if args.frames:
        banner("Frames (optional): extract + describe")
        manifest = P("frames_manifest.json")
        img_fmt = get(cfg, "frames.image_format", "png")
        run_stage([sys.executable, script("extract_frames.py"),
                   "--video", args.video, "--out-dir", mdir, "--manifest", manifest,
                   "--image-format", img_fmt,
                   "--jpeg-quality", str(get(cfg, "frames.jpeg_quality", 2)),
                   "--ffmpeg", get(cfg, "env.ffmpeg_bin", "ffmpeg"),
                   *args.frames])
        run_stage([sys.executable, script("describe_frames.py"),
                   "--manifest", manifest, "--base-dir", mdir,
                   "--out-details", P("video-frames-details.json"),
                   "--out-summary", P("video-frames-summary.md"),
                   "--host", host,
                   "--vision-model", get(cfg, "ollama.vision_model", "chandra-ocr-2"),
                   "--summary-model", get(cfg, "ollama.summary_model", "gemma4:12b"),
                   "--output-language", out_language,
                   "--num-ctx", num_ctx, "--temperature", temp,
                   "--describe-max-chars", str(get(cfg, "frames.describe_max_chars", 4000)),
                   "--max-chunk-chars",
                   str(get(cfg, "frames.frames_summary_max_chunk_chars", 24000))])
```
(`host`, `num_ctx`, `temp`, and `out_language` are already defined earlier in `main()` and are in scope here.)

- [ ] **Step 4: List frames outputs in the final summary**

In the `# ---- 9. render artifacts` section, just before `banner("Done")`, add:
```python
    if args.frames:
        produced += ["frames", "video-frames-details.json", "video-frames-summary.md"]
```

- [ ] **Step 5: Verify run.py still parses and imports**

Run: `cd video-meeting && python3 scripts/run.py --help`
Expected: exit 0; help text shows `--frames`.
Run: `cd video-meeting && python3 -m unittest tests.test_offline.TestRunWiring -v`
Expected: PASS (run module still imports).

- [ ] **Step 6: Commit**

```bash
git add video-meeting/scripts/run.py
git commit -m "feat(run): gated --frames stage + pass summary_max_chunk_chars"
```

---

## Task 8: `migrate_config.py` — non-destructive key migration

**Files:**
- Create: `video-meeting/scripts/migrate_config.py`
- Test: `video-meeting/tests/test_migrate_config.py`

Note: appends new top-level blocks at EOF; **inserts** new leaves into an existing parent block in raw text (never a duplicate `parent:`, which `yaml.safe_load` would treat as last-wins and wipe siblings). Values come from `config.example.yaml`; original inline comments are not copied (a generated provenance header is added instead).

- [ ] **Step 1: Write the failing test**

Create `video-meeting/tests/test_migrate_config.py`:
```python
"""Non-destructive config migration tests — stdlib + PyYAML (skip if absent)."""
import os
import sys
import tempfile
import unittest

import fixtures as F

sys.path.insert(0, F.SCRIPTS)

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


@unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
class TestMigrateConfig(unittest.TestCase):
    def _write(self, d, name, text):
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def test_missing_keys_detected(self):
        import migrate_config as M
        example = {"ollama": {"host": "h", "vision_model": "v"},
                   "frames": {"image_format": "png"}}
        user = {"ollama": {"host": "h"}}
        self.assertEqual(sorted(M.missing_keys(example, user)),
                         ["frames.image_format", "ollama.vision_model"])

    def test_build_missing_tree(self):
        import migrate_config as M
        example = {"ollama": {"host": "h", "vision_model": "v"},
                   "frames": {"image_format": "png"}}
        user = {"ollama": {"host": "h"}}
        tree = M.build_missing_tree(example, user)
        self.assertEqual(tree, {"ollama": {"vision_model": "v"},
                                "frames": {"image_format": "png"}})

    def test_apply_preserves_customizations_and_adds_keys(self):
        import migrate_config as M
        from config_get import load_config
        with tempfile.TemporaryDirectory() as d:
            example = self._write(d, "config.example.yaml",
                'ollama:\n  host: "http://x"\n  summary_model: "gemma4:12b"\n'
                '  vision_model: "chandra-ocr-2"\n'
                'frames:\n  image_format: "png"\n  describe_max_chars: 4000\n')
            # user customized summary_model AND has a key not in example
            cfg = self._write(d, "config.yaml",
                'ollama:\n  host: "http://x"\n  summary_model: "myllm:70b"\n'
                '  max_chunk_chars: 100000\n')
            changed = M.apply(cfg, example)
            self.assertTrue(changed)
            self.assertTrue(os.path.isfile(cfg + ".bak"))  # backup made
            loaded = load_config(cfg)
            # customizations preserved
            self.assertEqual(loaded["ollama"]["summary_model"], "myllm:70b")
            self.assertEqual(loaded["ollama"]["max_chunk_chars"], 100000)
            # siblings under ollama NOT wiped, new key inserted
            self.assertEqual(loaded["ollama"]["host"], "http://x")
            self.assertEqual(loaded["ollama"]["vision_model"], "chandra-ocr-2")
            # new top-level block appended
            self.assertEqual(loaded["frames"]["image_format"], "png")
            self.assertEqual(loaded["frames"]["describe_max_chars"], 4000)

    def test_idempotent(self):
        import migrate_config as M
        with tempfile.TemporaryDirectory() as d:
            example = self._write(d, "config.example.yaml",
                'ollama:\n  host: "h"\n  vision_model: "v"\n')
            cfg = self._write(d, "config.yaml", 'ollama:\n  host: "h"\n')
            self.assertTrue(M.apply(cfg, example))     # first run adds vision_model
            self.assertFalse(M.apply(cfg, example))    # second run: nothing to do


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd video-meeting && python3 -m unittest tests.test_migrate_config -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'migrate_config'`.

- [ ] **Step 3: Create `migrate_config.py`**

Create `video-meeting/scripts/migrate_config.py`:
```python
#!/usr/bin/env python3
"""
Reconcile an existing config.yaml against a newer config.example.yaml by adding
ONLY the keys it is missing — non-destructively.

Why this is careful: config_get.py loads with yaml.safe_load, where DUPLICATE
top-level keys are last-wins for the whole mapping (a second `ollama:` block
would wipe the user's existing ollama settings). So:
  - a brand-new top-level key  -> append its block at EOF
  - a new leaf under an EXISTING top-level key -> insert the leaf line(s) into
    that block in the raw text, leaving every existing line byte-for-byte intact.

Existing values, ordering, and comments are never modified. A timestamped
backup (config.yaml.bak) is written before any change.

Usage:
  migrate_config.py --config config.yaml --example config.example.yaml [--dry-run]
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_raw(path):
    import yaml
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def flatten(d, prefix=""):
    """Dotted leaf paths -> value. Dicts recurse; lists/scalars are leaves."""
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and v:
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def missing_keys(example, user):
    ex, us = flatten(example), flatten(user)
    return [k for k in ex if k not in us]


def build_missing_tree(example, user):
    """Nested dict of only the keys present in example but absent in user."""
    out = {}
    user = user or {}
    for k, v in (example or {}).items():
        if k not in user:
            out[k] = v
        elif isinstance(v, dict) and isinstance(user.get(k), dict):
            sub = build_missing_tree(v, user[k])
            if sub:
                out[k] = sub
    return out


def top_block_child_end(lines, start):
    """Index just after the last indented child line of the top-level block that
    begins at `start`. Trailing blank/comment lines are not swallowed."""
    last_child = start
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if ln[:1] in (" ", "\t") and ln.strip() and not ln.lstrip().startswith("#"):
            last_child = j
        elif ln.strip() == "" or ln.lstrip().startswith("#"):
            continue
        else:
            break  # next top-level key
    return last_child + 1


def _dump_block(tree, indent=0):
    """Render a (shallow) tree to YAML text. Uses PyYAML for value correctness."""
    import yaml
    text = yaml.safe_dump(tree, default_flow_style=False, sort_keys=False,
                          allow_unicode=True)
    if indent:
        pad = " " * indent
        text = "".join(pad + ln if ln.strip() else ln for ln in text.splitlines(keepends=True))
    return text


def apply(config_path, example_path, dry_run=False):
    """Add missing keys to config_path. Returns True if a change was (or would be)
    made. Writes a .bak and an atomic temp-file rename when not dry_run."""
    example = _load_raw(example_path)
    user = _load_raw(config_path)
    tree = build_missing_tree(example, user)
    if not tree:
        return False
    if dry_run:
        return True

    with open(config_path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    lines = raw.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    import datetime as _dt
    stamp = _dt.date.today().isoformat()
    appended_blocks = []  # rendered text for brand-new top-level keys

    # Process inserts first (they shift indices), then appends at EOF.
    for top, sub in tree.items():
        top_line = None
        for i, ln in enumerate(lines):
            if re.match(rf"^{re.escape(top)}\s*:", ln):
                top_line = i
                break
        if top_line is None:
            appended_blocks.append(_dump_block({top: sub}))
        else:
            insert_at = top_block_child_end(lines, top_line)
            child_text = _dump_block(sub, indent=2)
            lines[insert_at:insert_at] = [
                f"  # added by migrate-config {stamp} (see config.example.yaml)\n"
            ] + child_text.splitlines(keepends=True)

    new_text = "".join(lines)
    if appended_blocks:
        new_text = new_text.rstrip("\n") + "\n\n"
        new_text += (f"# ----------------------------------------------------------------------------\n"
                     f"# added by migrate-config {stamp} (new keys from config.example.yaml)\n"
                     f"# ----------------------------------------------------------------------------\n")
        new_text += "\n".join(b.rstrip("\n") for b in appended_blocks) + "\n"

    # backup, then atomic replace
    with open(config_path + ".bak", "w", encoding="utf-8") as fh:
        fh.write(raw)
    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    os.replace(tmp, config_path)
    return True


def main():
    ap = argparse.ArgumentParser(description="Add missing config keys non-destructively.")
    ap.add_argument("--config", default=os.environ.get("VM_CONFIG", "config.yaml"))
    ap.add_argument("--example", default=None,
                    help="config.example.yaml (default: alongside the script's package)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    example = args.example or os.path.join(os.path.dirname(here), "config.example.yaml")
    if not os.path.isfile(args.config):
        sys.exit(f"config not found: {args.config}")
    if not os.path.isfile(example):
        sys.exit(f"example config not found: {example}")

    miss = missing_keys(_load_raw(example), _load_raw(args.config))
    if not miss:
        print("config.yaml is up to date (no missing keys).")
        return
    print(f"{len(miss)} key(s) missing from {args.config}:")
    for k in miss:
        print(f"    {k}")
    if args.dry_run:
        print("(dry-run) run without --dry-run to append them.")
        return
    apply(args.config, example)
    print(f"Appended missing keys. Backup: {args.config}.bak")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd video-meeting && python3 -m unittest tests.test_migrate_config -v`
Expected: PASS (or SKIP if PyYAML absent).

- [ ] **Step 5: Commit**

```bash
git add video-meeting/scripts/migrate_config.py video-meeting/tests/test_migrate_config.py
git commit -m "feat(config): migrate_config.py — non-destructive key migration"
```

---

## Task 9: `preflight.py` — config-drift warning + vision-model check

**Files:**
- Modify: `video-meeting/scripts/preflight.py` (imports ~line 25; `check_ollama` ~line 175-182; new check + `main()` call list ~line 223-234)

- [ ] **Step 1: Add a config-drift check function**

In `video-meeting/scripts/preflight.py`, after the imports block (after `from config_get import load_config, get`), add:
```python
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```
Then add this function alongside the other `check_*` functions:
```python
def check_config_drift(cfg_path):
    """Warn if config.yaml is missing keys present in config.example.yaml."""
    example = os.path.join(ROOT, "config.example.yaml")
    if not (os.path.isfile(cfg_path) and os.path.isfile(example)):
        return
    try:
        import migrate_config as MC
        miss = MC.missing_keys(MC._load_raw(example), MC._load_raw(cfg_path))
    except Exception as exc:  # noqa: BLE001
        return record(WARN, "config drift", f"could not check: {exc}")
    if miss:
        record(WARN, "config drift",
               f"{len(miss)} newer key(s) missing ({', '.join(miss)}); "
               "built-in defaults in effect — run: bash install.sh --migrate-config")
    else:
        record(OK, "config up to date", os.path.basename(cfg_path))
```

- [ ] **Step 2: Add a vision-model presence note in `check_ollama`**

In `check_ollama`, extend the model-check loop. Change:
```python
    for key, label in (("ollama.summary_model", "summary"),
                       ("ollama.tasks_model", "tasks")):
        model = get(cfg, key)
        if present(model):
            record(OK, f"Ollama model ({label})", model)
        else:
            record(FAIL, f"Ollama model ({label})",
                   f"{model} not pulled (run: ollama pull {model})")
```
to:
```python
    for key, label in (("ollama.summary_model", "summary"),
                       ("ollama.tasks_model", "tasks")):
        model = get(cfg, key)
        if present(model):
            record(OK, f"Ollama model ({label})", model)
        else:
            record(FAIL, f"Ollama model ({label})",
                   f"{model} not pulled (run: ollama pull {model})")
    # vision model is optional (only the --frames step needs it) -> WARN, not FAIL
    vmodel = get(cfg, "ollama.vision_model")
    if vmodel:
        if present(vmodel):
            record(OK, "Ollama model (vision)", vmodel)
        else:
            record(WARN, "Ollama model (vision)",
                   f"{vmodel} not pulled — needed only for --frames "
                   f"(run: ollama pull {vmodel})")
```

- [ ] **Step 3: Call the drift check in `main()`**

In `main()`, after `cfg = load_config(args.config)` and the existing check calls, add the drift check (e.g. right after `check_writable(cfg)`):
```python
    check_config_drift(args.config)
```

- [ ] **Step 4: Verify preflight still runs**

Run: `cd video-meeting && python3 scripts/preflight.py --help`
Expected: exit 0.
Run: `cd video-meeting && python3 -m unittest tests.test_cli.TestHelp -v`
Expected: PASS (preflight.py still parses).

- [ ] **Step 5: Commit**

```bash
git add video-meeting/scripts/preflight.py
git commit -m "feat(preflight): config-drift warning + vision-model check"
```

---

## Task 10: `install.sh` — `--migrate-config` + ensure vision model pulled

**Files:**
- Modify: `video-meeting/install.sh` (help block ~line 12-22; flag parse ~line 51-78; `phase_ollama` ~line 281-286; `main()` ~line 325-339)

- [ ] **Step 1: Add the `--migrate-config` flag**

In the usage comment block (top of file), add a line:
```bash
#   install.sh --migrate-config # add new config.yaml keys from the example (non-destructive)
```
In the flag-parsing `for arg in "$@"` case, add a case:
```bash
    --migrate-config) MODE="migrate-config" ;;
```
In the `case "$MODE" in` mode→phase mapping, add:
```bash
  migrate-config) : ;;   # handled separately in main()
```

- [ ] **Step 2: Ensure the vision model is pulled in `phase_ollama`**

In `phase_ollama`, after the existing `while ... ollama pull "$m" ... done < <(cfg install.ollama_models)` loop and its `ok "models pulled"`, add:
```bash
  # Vision model for the optional --frames step. Pulled even if the user's
  # install.ollama_models list predates this key (uses the configured value
  # or the built-in default).
  local vmodel
  vmodel="$(cfg ollama.vision_model 2>/dev/null || true)"
  [[ -n "$vmodel" ]] || vmodel="chandra-ocr-2"
  if ! ollama list 2>/dev/null | grep -q "^${vmodel%%:*}"; then
    log "pulling vision model $vmodel (for --frames)"
    ollama pull "$vmodel" || warn "could not pull $vmodel; --frames will be unavailable"
  else
    ok "vision model present: $vmodel"
  fi
```

- [ ] **Step 3: Handle the migrate-config mode in `main()`**

In `main()`, after the uninstall early-return line (`if [[ "$MODE" == "uninstall" ]]; then do_uninstall; exit 0; fi`), add:
```bash
  if [[ "$MODE" == "migrate-config" ]]; then
    ensure_pyyaml
    [[ -f "$CONFIG" ]] || die "no config.yaml to migrate (run install first)"
    python3 "$SCRIPT_DIR/scripts/migrate_config.py" --config "$CONFIG" --example "$EXAMPLE"
    exit 0
  fi
```

- [ ] **Step 4: Verify the script parses**

Run: `bash -n video-meeting/install.sh`
Expected: exit 0 (no syntax errors).
Run: `bash video-meeting/install.sh --help`
Expected: exit 0; usage shows `--migrate-config`.

- [ ] **Step 5: Commit**

```bash
git add video-meeting/install.sh
git commit -m "feat(install): --migrate-config + ensure vision model pulled"
```

---

## Task 11: Register new scripts in the `--help` smoke test

**Files:**
- Modify: `video-meeting/tests/test_cli.py:13-18` (`ALL_SCRIPTS`)

- [ ] **Step 1: Add the new scripts to `ALL_SCRIPTS`**

In `video-meeting/tests/test_cli.py`, extend the `ALL_SCRIPTS` list to include the three new scripts:
```python
ALL_SCRIPTS = [
    "extract_audio.py", "transcribe.py", "diarize.py", "build_record.py",
    "summarize.py", "extract_tasks.py", "render_email.py", "render_tasks_xlsx.py",
    "render_slides.py", "render_report.py", "identify_speakers.py", "registry.py",
    "preflight.py", "run.py", "config_get.py",
    "extract_frames.py", "describe_frames.py", "migrate_config.py",
]
```

- [ ] **Step 2: Run the smoke test**

Run: `cd video-meeting && python3 -m unittest tests.test_cli.TestHelp -v`
Expected: PASS — all three new scripts exit 0 on `--help` (none import optional deps at import time except `migrate_config`/`describe_frames`, which only import yaml/summarize lazily or via stdlib; `--help` must not error).

- [ ] **Step 3: Commit**

```bash
git add video-meeting/tests/test_cli.py
git commit -m "test(cli): cover extract_frames/describe_frames/migrate_config --help"
```

---

## Task 12: Documentation

**Files:**
- Modify: `video-meeting/SKILL.md`
- Modify: `video-meeting/references/install.md`
- Modify: `video-meeting/references/design.md`

- [ ] **Step 1: Document the frames step in `SKILL.md`**

In `video-meeting/SKILL.md`, under "Running it", after the "Useful flags" paragraph, add:
```markdown
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
```

Also add two rows to the Outputs table (after the `email.md` row):
```markdown
| `video-frames-details.json` | describe_frames.py | Per-slide timestamp + image + description (only with `--frames`) |
| `video-frames-summary.md` | describe_frames.py | Summary of the shared slides (only with `--frames`) |
```

- [ ] **Step 2: Document the upgrade procedure in `references/install.md`**

In `video-meeting/references/install.md`, add a new section:
```markdown
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
```

- [ ] **Step 3: Record the rationale in `references/design.md`**

In `video-meeting/references/design.md`, append a new section at the end:
```markdown
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
```

- [ ] **Step 4: Commit**

```bash
git add video-meeting/SKILL.md video-meeting/references/install.md video-meeting/references/design.md
git commit -m "docs: frames step + upgrade/migration procedure"
```

---

## Task 13: Full suite + repackage

**Files:**
- Verify only (no edits unless a failure surfaces)

- [ ] **Step 1: Run the whole test suite**

Run: `bash video-meeting/tests/run_tests.sh`
Expected: all tests pass or skip (ffmpeg/Ollama/PyYAML-dependent tests skip cleanly when those are absent). No failures, no errors.

- [ ] **Step 2: (If render-env available) run with the richer interpreter**

Run: `VM_TEST_PYTHON=~/.pyenv/versions/render-env/bin/python bash video-meeting/tests/run_tests.sh`
Expected: same — passes/skips, no failures. (Skip this step if that interpreter doesn't exist.)

- [ ] **Step 3: Rebuild the bundle and confirm exclusions**

Run: `bash package.sh video-meeting`
Expected: `video-meeting.skill` is (re)written, frontmatter validation passes, and `config.yaml`/`hf_token`/`*.token`/`__pycache__` are excluded. The new scripts, templates, and `config.example.yaml` keys are included.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: rebuild video-meeting.skill bundle with frames step"
```

---

## Manual validation (not automated — requires the GPU stack)

The vision/summary Ollama path is not unit-tested (consistent with the repo). After implementation, validate on a real machine:

```bash
bash video-meeting/install.sh --check            # vision model present? config drift?
python3 video-meeting/scripts/run.py --video meeting.mp4 --title "Demo" \
    --frames 10:20 15:10 01:10:23 --artifacts transcript
# inspect: frames/slide-000{1,2,3}.png, video-frames-details.json, video-frames-summary.md
```

Upgrade path on a machine with an older `config.yaml`:
```bash
bash video-meeting/install.sh --migrate-config   # adds ollama.vision_model, frames.*
diff <(git show HEAD:video-meeting/config.yaml 2>/dev/null || true) video-meeting/config.yaml  # if tracked
# confirm existing customized values are unchanged; new keys appended at end
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- §1 trigger/CLI → Task 7 (`--frames`), Task 12 (SKILL doc).
- §2 extract_frames/describe_frames/ollama images/templates → Tasks 1–5.
- §3 output schema → Tasks 2, 5 (manifest + details + digest).
- §4 pipeline placement/VRAM → Task 7 (block after tasks; uses summary_model with keep_alive).
- §5 config additions → Task 6.
- §6 upgrade-safe config + drift + migrate + vision pull → Tasks 6, 8, 9, 10.
- §7 testing → Tasks 1–5, 8, 11, 13.
- §8 files touched / repackage → all tasks + Task 13.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output.

**Type/name consistency:** `parse_timestamp`, `slide_id`, `build_manifest`, `build_details`, `render_digest_md`, `truncate`, `missing_keys`, `build_missing_tree`, `apply`, `_load_raw`, `top_block_child_end` are used consistently across tasks and tests. `run.py` passes `--describe-max-chars`/`--max-chunk-chars`/`--vision-model`/`--summary-model`/`--base-dir` exactly as `describe_frames.py` defines them. Config keys (`ollama.vision_model`, `ollama.summary_max_chunk_chars`, `frames.image_format`, `frames.jpeg_quality`, `frames.describe_max_chars`, `frames.frames_summary_max_chunk_chars`) match between `config.example.yaml` (Task 6), `run.py` (Task 7), and `test_offline.py` (Task 6).
