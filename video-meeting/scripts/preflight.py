#!/usr/bin/env python3
"""
Preflight validation for the video-meeting skill.

Runs with the system python3 and shells out to the per-tool venv interpreters.
It validates everything a real run needs and fails fast with the offending item,
so a long transcription/diarization job never dies halfway.

Exit codes:
  0  all required checks passed (warnings allowed)
  1  one or more required checks FAILED

Usage:
  python3 scripts/preflight.py --config config.yaml
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config_get import load_config, get  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OK, WARN, FAIL = "OK", "WARN", "FAIL"
GREEN, YELLOW, RED, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[0m"
_COLOR = {OK: GREEN, WARN: YELLOW, FAIL: RED}

results = []


def record(status, name, detail=""):
    results.append((status, name, detail))


def run(cmd, timeout=60):
    """Run a command, return (returncode, stdout+stderr)."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def venv_import(py, module):
    """Check a module imports inside a given interpreter."""
    if not py or not os.path.isfile(py):
        return False, f"interpreter missing: {py}"
    rc, out = run([py, "-c", f"import {module}"])
    return rc == 0, out


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #
def check_ffmpeg(cfg):
    ffmpeg = get(cfg, "env.ffmpeg_bin", "ffmpeg")
    path = ffmpeg if os.path.isfile(ffmpeg) else shutil.which(ffmpeg)
    if not path:
        return record(FAIL, "ffmpeg", f"not found at {ffmpeg}")
    rc, _ = run([path, "-version"])
    record(OK if rc == 0 else FAIL, "ffmpeg", path)


def check_whisper(cfg):
    impl = get(cfg, "env.whisper.impl", "faster-whisper")
    if impl == "whisper.cpp":
        binary = get(cfg, "env.whisper.binary", "")
        if binary and os.path.isfile(binary):
            record(OK, "whisper (whisper.cpp)", binary)
        else:
            record(FAIL, "whisper (whisper.cpp)", f"binary missing: {binary}")
        return
    py = get(cfg, "env.whisper.python")
    ok, detail = venv_import(py, "faster_whisper")
    record(OK if ok else FAIL, "whisper-env: faster_whisper", detail if not ok else py)


def check_pyannote(cfg):
    py = get(cfg, "env.pyannote.python")
    ok, detail = venv_import(py, "pyannote.audio")
    record(OK if ok else FAIL, "pyannote-env: pyannote.audio", detail if not ok else py)


def check_render(cfg):
    py = get(cfg, "env.render.python")
    if not py or not os.path.isfile(py):
        return record(FAIL, "render-env", f"interpreter missing: {py}")
    for mod in ("openpyxl", "pptx", "docx"):
        ok, detail = venv_import(py, mod)
        record(OK if ok else FAIL, f"render-env: {mod}", detail if not ok else py)


def check_libreoffice(cfg):
    """Needed only for .odp slides and the PDF report (docx/pptx -> pdf/odp)."""
    soffice = get(cfg, "rendering.slides.libreoffice_bin", "soffice")
    path = soffice if os.path.isfile(soffice) else shutil.which(soffice) or shutil.which("libreoffice")
    if path:
        record(OK, "LibreOffice (soffice)", path)
    else:
        record(WARN, "LibreOffice (soffice)",
               "not found — .odp/.pdf conversion unavailable; .pptx still works")


def check_gpu(cfg):
    py = get(cfg, "env.pyannote.python")
    if not py or not os.path.isfile(py):
        return record(FAIL, "GPU (torch.cuda)", f"pyannote interpreter missing: {py}")
    script = (
        "import torch,json;"
        "print(json.dumps({'cuda':torch.cuda.is_available(),"
        "'name':(torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)}))"
    )
    env = dict(os.environ)
    dev = get(cfg, "env.cuda.visible_devices")
    if dev is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(dev)
    try:
        p = subprocess.run([py, "-c", script], capture_output=True, text=True,
                           timeout=120, env=env, check=False)
        info = json.loads(p.stdout.strip().splitlines()[-1])
        if info.get("cuda"):
            record(OK, "GPU (torch.cuda)", info.get("name") or "available")
        else:
            record(FAIL, "GPU (torch.cuda)", "torch.cuda.is_available() is False")
    except Exception as exc:  # noqa: BLE001
        record(FAIL, "GPU (torch.cuda)", str(exc))


def check_model_dir(cfg, key, label, required=True):
    d = get(cfg, key)
    if d and os.path.isdir(d) and any(os.scandir(d)):
        record(OK, label, d)
    elif d and os.path.isdir(d):
        record(WARN, label, f"empty (will download on first use): {d}")
    else:
        record(FAIL if required else WARN, label, f"missing: {d}")


def check_hf_token(cfg):
    tok = get(cfg, "env.pyannote.hf_token_file")
    if tok and os.path.isfile(tok) and os.path.getsize(tok) > 0:
        record(OK, "Hugging Face token", tok)
    else:
        record(FAIL, "Hugging Face token",
               f"missing/empty: {tok} (accept pyannote license + save token)")


def check_ollama(cfg):
    host = get(cfg, "ollama.host", "http://127.0.0.1:11434").rstrip("/")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=10) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
        names = {m.get("name", "") for m in tags.get("models", [])}
    except Exception as exc:  # noqa: BLE001
        return record(FAIL, "Ollama service", f"unreachable at {host}: {exc}")
    record(OK, "Ollama service", host)

    def present(model):
        if not model:
            return True
        if model in names:
            return True
        # tolerate :latest and bare-name matches
        base = model.split(":")[0]
        return any(n == model or n.split(":")[0] == base for n in names)

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


def check_kv_cache(cfg):
    """Best-effort: warn if the service env doesn't match the configured KV type."""
    want = get(cfg, "ollama.kv_cache_type", "f16")
    rc, out = run(["systemctl", "show", "ollama", "-p", "Environment"], timeout=10)
    if rc != 0:
        return record(WARN, "Ollama KV cache env",
                      "could not read service env (non-systemd?); ensure "
                      f"OLLAMA_KV_CACHE_TYPE={want}")
    if want == "f16" or f"OLLAMA_KV_CACHE_TYPE={want}" in out:
        record(OK, "Ollama KV cache env", f"kv_cache_type={want}")
    else:
        record(WARN, "Ollama KV cache env",
               f"config wants {want} but service env is: {out or '(unset)'}")


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


def check_writable(cfg):
    for key in ("paths.global_dir", "paths.meetings_dir", "paths.work_dir"):
        d = get(cfg, key)
        if not d:
            record(FAIL, f"writable {key}", "unset")
            continue
        try:
            os.makedirs(d, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=d, delete=True):
                pass
            record(OK, f"writable {key}", d)
        except Exception as exc:  # noqa: BLE001
            record(FAIL, f"writable {key}", f"{d}: {exc}")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Validate the video-meeting environment.")
    ap.add_argument("--config", default=os.environ.get("VM_CONFIG", "config.yaml"))
    args = ap.parse_args()

    cfg = load_config(args.config)

    check_ffmpeg(cfg)
    check_whisper(cfg)
    check_pyannote(cfg)
    check_render(cfg)
    check_libreoffice(cfg)
    check_gpu(cfg)
    check_model_dir(cfg, "env.whisper.model_dir", "Whisper model dir")
    check_model_dir(cfg, "env.pyannote.model_dir", "pyannote model dir", required=False)
    check_hf_token(cfg)
    check_ollama(cfg)
    check_kv_cache(cfg)
    check_writable(cfg)
    check_config_drift(args.config)

    print("\nPreflight results")
    print("-" * 60)
    failed = 0
    for status, name, detail in results:
        if status == FAIL:
            failed += 1
        color = _COLOR.get(status, "")
        line = f"  {color}{status:4}{RESET}  {name}"
        if detail:
            line += f"  —  {detail}"
        print(line)
    print("-" * 60)

    if failed:
        print(f"{RED}{failed} check(s) failed.{RESET} "
              "Fix the items above (see references/install.md) and re-run.")
        sys.exit(1)
    print(f"{GREEN}All required checks passed.{RESET}")


if __name__ == "__main__":
    main()
