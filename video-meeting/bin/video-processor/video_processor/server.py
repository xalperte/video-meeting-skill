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
