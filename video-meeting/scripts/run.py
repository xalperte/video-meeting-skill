#!/usr/bin/env python3
"""
Orchestrator — run the full pipeline for one recording.

Runs with the system python3 (reads config via config_get). Each stage is a
SEPARATE subprocess so its VRAM is freed before the next loads — on a 16 GB GPU
Whisper, pyannote, and the LLM never co-reside. Audio stages use their venv
interpreters with the CUDA env; LLM stages talk to Ollama over HTTP.

Typical:
  python3 scripts/run.py --video meeting.mp4 --title "Sprint grooming" \
     --meeting-type grooming --participants "Alice Ng" "Bob Li"

Stages: extract audio -> transcribe -> diarize -> identify speakers
        -> (confirm) -> transcript -> summarize -> extract tasks
        -> meeting_record.json -> render artifacts.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from config_get import load_config, get  # noqa: E402
from templates import templates_root, resolve_template  # noqa: E402

LANG_NAMES = {"en": "English", "es": "Spanish", "zh": "Chinese", "pt": "Portuguese",
              "fr": "French", "de": "German", "it": "Italian"}
MEETING_TYPES = {"feature", "grooming", "catchup", "presentation", "other"}


# --------------------------------------------------------------------------- #
def banner(msg):
    print(f"\n\033[1m==> {msg}\033[0m", flush=True)


def gpu_env(cfg):
    e = os.environ.copy()
    e["CUDA_VISIBLE_DEVICES"] = str(get(cfg, "env.cuda.visible_devices", "0"))
    hf = get(cfg, "env.cuda.hf_home")
    if hf:
        e["HF_HOME"] = hf
    ld = get(cfg, "env.cuda.extra_ld_library_path")
    if ld:
        e["LD_LIBRARY_PATH"] = ld + ":" + e.get("LD_LIBRARY_PATH", "")
    return e


def run_stage(cmd, env=None, capture=False):
    t0 = time.time()
    if capture:
        p = subprocess.run(cmd, env=env, text=True, capture_output=True, check=False)
        if p.stderr:
            sys.stderr.write(p.stderr)
        if p.returncode != 0:
            sys.exit(f"stage failed ({p.returncode}): {' '.join(map(str, cmd))}")
        print(f"   ({time.time() - t0:.1f}s)")
        return p.stdout
    p = subprocess.run(cmd, env=env, check=False)
    if p.returncode != 0:
        sys.exit(f"stage failed ({p.returncode}): {' '.join(map(str, cmd))}")
    print(f"   ({time.time() - t0:.1f}s)")
    return None


def slugify(text):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "meeting"


def lang_name(code):
    return LANG_NAMES.get((code or "").lower(), code)


def script(name):
    return os.path.join(HERE, name)


# --------------------------------------------------------------------------- #
def confirm_pending(args, cfg, mapping_path, embeddings, gdir, max_samples):
    """Handle gray-zone / pending speakers. Interactive prompt when a TTY is
    available and --interactive is set; otherwise warn and continue (those
    speakers stay labeled as unconfirmed in the transcript)."""
    doc = json.load(open(mapping_path, encoding="utf-8"))
    pending = doc.get("pending_confirmation", [])
    if not pending:
        return
    if not (args.interactive and sys.stdin.isatty()):
        print(f"\n\033[33m! {len(pending)} speaker(s) need confirmation: "
              f"{', '.join(pending)}\033[0m")
        print("  They are labeled '(?)' in the transcript. Re-run with --interactive, "
              "or call identify_speakers.py confirm with a decisions.json to resolve.")
        return
    decisions = {}
    for spk in pending:
        info = doc["mapping"].get(spk, {})
        cand = info.get("candidate_name")
        conf = info.get("confidence")
        print(f"\nSpeaker {spk}"
              + (f" — best guess: {cand} (similarity {conf})" if cand else ""))
        choice = input("  [m]atch guess  [n]ew person  [i]gnore ? ").strip().lower()
        if choice == "m" and info.get("candidate_id"):
            decisions[spk] = {"action": "match",
                              "participant_id": info["candidate_id"]}
        elif choice == "n":
            first = input("    first name: ").strip()
            last = input("    last name: ").strip()
            decisions[spk] = {"action": "new", "first_name": first, "last_name": last}
        else:
            decisions[spk] = {"action": "ignore"}
    dec_path = os.path.join(os.path.dirname(mapping_path), "decisions.json")
    json.dump(decisions, open(dec_path, "w"), indent=2)
    run_stage([sys.executable, script("identify_speakers.py"), "confirm",
               "--decisions", dec_path, "--embeddings", embeddings,
               "--global-dir", gdir, "--mapping", mapping_path,
               "--out", mapping_path, "--max-samples", str(max_samples)])


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Run the meeting pipeline on one video.")
    ap.add_argument("--video", required=True)
    ap.add_argument("--config", default=os.environ.get("VM_CONFIG",
                                                        os.path.join(ROOT, "config.yaml")))
    ap.add_argument("--title", default=None)
    ap.add_argument("--date", default=None)
    ap.add_argument("--meeting-type", default=None)
    ap.add_argument("--template", default=None)
    ap.add_argument("--output-language", default=None)
    ap.add_argument("--audience", default=None)
    ap.add_argument("--tone", default=None)
    ap.add_argument("--detail-level", default=None)
    ap.add_argument("--participants", nargs="*", default=None)
    ap.add_argument("--artifacts", nargs="*", default=None)
    ap.add_argument("--frames", nargs="*", default=None,
                    help="timestamps (mm:ss or hh:mm:ss) to capture + describe frames")
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--interactive", action="store_true",
                    help="prompt to confirm gray-zone speakers")
    args = ap.parse_args()

    if not os.path.isfile(args.video):
        sys.exit(f"video not found: {args.video}")
    cfg = load_config(args.config)

    # ---- resolve context (CLI overrides config defaults) ------------------- #
    cd = get(cfg, "context_defaults", {}) or {}
    mtype = args.meeting_type or cd.get("meeting_type", "other")
    mtype = mtype if mtype in MEETING_TYPES else "other"
    tname = args.template or get(cfg, "rendering.template", "internal")
    template_dir, _ = resolve_template(templates_root(ROOT), tname)
    audience = args.audience or cd.get("audience", "team")
    tone = args.tone or cd.get("tone", "neutral")
    detail = args.detail_level or cd.get("detail_level", "standard")
    out_lang_cfg = args.output_language or cd.get("output_language", "auto")
    suggest_tasks = bool(cd.get("suggest_tasks", True))
    artifacts = set(args.artifacts or cd.get("artifacts",
                    ["transcript", "summary", "tasks", "slides", "report", "email"]))
    title = args.title or os.path.splitext(os.path.basename(args.video))[0]
    date = args.date or dt.date.today().isoformat()

    # ---- meeting folder ---------------------------------------------------- #
    meetings_dir = get(cfg, "paths.meetings_dir")
    work_dir = get(cfg, "paths.work_dir")
    gdir = get(cfg, "paths.global_dir")
    mdir = os.path.join(meetings_dir, f"{date}-{slugify(title)}")
    os.makedirs(mdir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    P = lambda *p: os.path.join(mdir, *p)  # noqa: E731
    print(f"Meeting folder: {mdir}")

    genv = gpu_env(cfg)
    need_summary = bool(artifacts & {"summary", "slides", "report", "email"})
    need_tasks = bool(artifacts & {"tasks", "slides", "report", "email"})

    # ---- 1. extract audio -------------------------------------------------- #
    banner("1/9  Extract audio")
    out = run_stage([sys.executable, script("extract_audio.py"),
                     "--in", args.video, "--out", P("audio.wav"),
                     "--ffmpeg", get(cfg, "env.ffmpeg_bin", "ffmpeg")], capture=True)
    duration = (json.loads(out) or {}).get("duration_s")

    # ---- 2. transcribe (whisper-env) -------------------------------------- #
    banner("2/9  Transcribe (Whisper)")
    w = lambda k, d=None: get(cfg, f"env.whisper.{k}", d)  # noqa: E731
    tcmd = [w("python"), script("transcribe.py"),
            "--in", P("audio.wav"), "--out", P("segments.json"),
            "--model", w("model", "large-v3"), "--device", "cuda",
            "--compute-type", w("compute_type", "float16"),
            "--beam-size", str(w("beam_size", 5))]
    if w("model_dir"):
        tcmd += ["--model-dir", w("model_dir")]
    if w("vad_filter", True):
        tcmd += ["--vad-filter"]
    run_stage(tcmd, env=genv)
    detected = (json.load(open(P("segments.json"), encoding="utf-8")) or {}).get("language")
    out_language = lang_name(detected) if out_lang_cfg == "auto" else lang_name(out_lang_cfg)
    print(f"   detected language: {detected} -> output language: {out_language}")

    # ---- 3. diarize (pyannote-env) ---------------------------------------- #
    banner("3/9  Diarize + voiceprints (pyannote)")
    pn = lambda k, d=None: get(cfg, f"env.pyannote.{k}", d)  # noqa: E731
    dcmd = [pn("python"), script("diarize.py"),
            "--in", P("audio.wav"), "--out", P("turns.json"),
            "--embeddings-out", P("voiceprints.npz"),
            "--diarization-model", pn("diarization_model", "pyannote/speaker-diarization-3.1"),
            "--embedding-model", pn("embedding_model", "pyannote/embedding"),
            "--device", "cuda",
            "--min-turn-seconds", str(get(cfg, "voiceprints.min_turn_seconds", 3.0))]
    if pn("model_dir"):
        dcmd += ["--model-dir", pn("model_dir")]
    if pn("hf_token_file"):
        dcmd += ["--hf-token-file", pn("hf_token_file")]
    if args.num_speakers:
        dcmd += ["--num-speakers", str(args.num_speakers)]
    run_stage(dcmd, env=genv)

    # ---- 4. identify speakers (numpy; pyannote-env) ----------------------- #
    banner("4/9  Identify speakers")
    max_samples = int(get(cfg, "voiceprints.max_samples_per_person", 8))
    icmd = [pn("python"), script("identify_speakers.py"), "match",
            "--turns", P("turns.json"), "--embeddings", P("voiceprints.npz"),
            "--global-dir", gdir, "--out", P("mapping.json"),
            "--high", str(get(cfg, "speaker_id.thresholds.high", 0.75)),
            "--low", str(get(cfg, "speaker_id.thresholds.low", 0.55)),
            "--strategy", get(cfg, "speaker_id.score_strategy", "best"),
            "--max-samples", str(max_samples)]
    if get(cfg, "voiceprints.add_sample_on_match", True):
        icmd += ["--add-sample-on-match"]
    if args.participants:
        icmd += ["--hint-names", *args.participants]
    run_stage(icmd)
    confirm_pending(args, cfg, P("mapping.json"), P("voiceprints.npz"), gdir, max_samples)

    # ---- 5. transcript.md (build_record, first pass) ---------------------- #
    banner("5/9  Build named transcript")
    base_record = [sys.executable, script("build_record.py"),
                   "--segments", P("segments.json"), "--turns", P("turns.json"),
                   "--mapping", P("mapping.json"),
                   "--transcript-out", P("transcript.md"),
                   "--record-out", P("meeting_record.json"),
                   "--title", title, "--date", date, "--meeting-type", mtype,
                   "--language-out", (detected or "auto")]
    if duration:
        base_record += ["--duration", str(duration)]
    run_stage(base_record)

    # participant names for task assignment
    mp = json.load(open(P("mapping.json"), encoding="utf-8")).get("mapping", {})
    names = sorted({v.get("name") for v in mp.values()
                    if v.get("status") in ("known", "new") and v.get("name")})
    host = get(cfg, "ollama.host", "http://127.0.0.1:11434")
    num_ctx = str(get(cfg, "ollama.num_ctx", 65536))
    temp = str(get(cfg, "ollama.temperature", 0.2))

    # ---- 6. summarize (Ollama) -------------------------------------------- #
    if need_summary:
        banner("6/9  Summarize (Ollama)")
        run_stage([sys.executable, script("summarize.py"),
                   "--transcript", P("transcript.md"),
                   "--out-json", P("summary.json"), "--out-md", P("summary.md"),
                   "--host", host, "--model", get(cfg, "ollama.summary_model", "gemma4:12b"),
                   "--meeting-type", mtype, "--output-language", out_language,
                   "--audience", audience, "--tone", tone, "--detail-level", detail,
                   "--num-ctx", num_ctx, "--temperature", temp,
                   "--max-chunk-chars",
                   str(get(cfg, "ollama.summary_max_chunk_chars", 24000))])

    # ---- 7. extract tasks (Ollama) ---------------------------------------- #
    if need_tasks:
        banner("7/9  Extract action items (Ollama)")
        ecmd = [sys.executable, script("extract_tasks.py"),
                "--transcript", P("transcript.md"), "--out", P("tasks.json"),
                "--host", host, "--model", get(cfg, "ollama.tasks_model", "qwen3.5:9b"),
                "--meeting-type", mtype, "--output-language", out_language,
                "--num-ctx", num_ctx, "--temperature", temp,
                "--suggest-tasks" if suggest_tasks else "--no-suggest-tasks"]
        if names:
            ecmd += ["--participants", *names]
        run_stage(ecmd)

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

    # ---- 8. finalize meeting_record.json ---------------------------------- #
    banner("8/9  Assemble meeting_record.json")
    final_record = list(base_record)
    if need_summary and os.path.isfile(P("summary.json")):
        final_record += ["--summary", P("summary.json")]
    if need_tasks and os.path.isfile(P("tasks.json")):
        final_record += ["--tasks", P("tasks.json")]
    run_stage(final_record)

    # ---- 9. render artifacts (render-env / LibreOffice) ------------------- #
    banner("9/9  Render artifacts")
    rpy = get(cfg, "env.render.python")
    soffice = get(cfg, "rendering.slides.libreoffice_bin", "soffice")
    produced = ["transcript.md", "meeting_record.json"]
    if "summary" in artifacts and os.path.isfile(P("summary.md")):
        produced.append("summary.md")
    if "tasks" in artifacts:
        run_stage([rpy, script("render_tasks_xlsx.py"),
                   "--record", P("meeting_record.json"), "--out", P("tasks.xlsx"),
                   "--template-dir", template_dir])
        produced.append("tasks.xlsx")
    if "slides" in artifacts:
        formats = get(cfg, "rendering.slides.formats", ["pptx", "odp"])
        run_stage([rpy, script("render_slides.py"),
                   "--record", P("meeting_record.json"), "--out-pptx", P("slides.pptx"),
                   "--formats", *formats, "--libreoffice", soffice,
                   "--template-dir", template_dir])
        produced += [f"slides.{f}" for f in formats]
    if "report" in artifacts:
        run_stage([rpy, script("render_report.py"),
                   "--record", P("meeting_record.json"), "--out-pdf", P("report.pdf"),
                   "--libreoffice", soffice, "--template-dir", template_dir])
        produced += ["report.pdf", "report.docx"]
    if "email" in artifacts:
        run_stage([sys.executable, script("render_email.py"),
                   "--record", P("meeting_record.json"), "--out", P("email.md"),
                   "--host", host, "--model", get(cfg, "ollama.summary_model", "gemma4:12b")])
        produced.append("email.md")

    if args.frames:
        produced += ["frames", "video-frames-details.json", "video-frames-summary.md"]

    banner("Done")
    print(f"Outputs in {mdir}:")
    for f in produced:
        mark = "✓" if os.path.isfile(P(f)) else "·"
        print(f"  {mark} {f}")


if __name__ == "__main__":
    main()
