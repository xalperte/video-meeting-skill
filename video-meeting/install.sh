#!/usr/bin/env bash
# =============================================================================
# video-meeting — idempotent installer for the local AI stack.
#
# Provisions: ffmpeg, pyenv + two virtualenvs (Whisper, pyannote), their Python
# deps, model weights, and (optionally) the Ollama service + models + KV-cache
# tuning. Safe to re-run — each phase checks "already done?" and only fills gaps.
#
# Paths come from config.yaml (./config.yaml by default), which uses ${USER_HOME}
# tokens expanded at read time. Override the base with:  export USER_HOME=/data/...
#
# Usage:
#   install.sh --all            # everything (default; uses sudo for apt + Ollama)
#   install.sh --user-space     # NO SUDO: venvs + pip deps + models + ollama pulls
#                               #   (assumes apt packages, GPU driver, Ollama service
#                               #    already installed; safe to delegate to Claude)
#   install.sh --no-ollama      # skip Ollama service + model pulls
#   install.sh --models-only    # just (re)download model weights
#   install.sh --check          # run preflight only; change nothing
#   install.sh --migrate-config # add new config.yaml keys from the example (non-destructive)
#   install.sh --install-cuda   # also attempt NVIDIA driver/CUDA (OFF by default)
#   install.sh --uninstall [--purge]   # remove venvs+models (+global registry)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${VM_CONFIG:-$SCRIPT_DIR/config.yaml}"
EXAMPLE="$SCRIPT_DIR/config.example.yaml"
CONFIG_GET="$SCRIPT_DIR/scripts/config_get.py"

# Defaults (override via environment if needed).
export USER_HOME="${USER_HOME:-$HOME}"
PY_VERSION="${VM_PY_VERSION:-3.11.9}"
TORCH_CUDA="${VM_TORCH_CUDA:-cu124}"   # match your NVIDIA driver (cu121/cu124/...)

# ----------------------------------------------------------------------------
# Pretty logging
# ----------------------------------------------------------------------------
c_g="\033[32m"; c_y="\033[33m"; c_r="\033[31m"; c_b="\033[1m"; c_0="\033[0m"
log()  { printf "${c_b}==>${c_0} %s\n" "$*"; }
ok()   { printf "  ${c_g}ok${c_0}   %s\n" "$*"; }
warn() { printf "  ${c_y}warn${c_0} %s\n" "$*"; }
die()  { printf "  ${c_r}err${c_0}  %s\n" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# sudo only when not already root
if [[ "$(id -u)" -eq 0 ]]; then SUDO=""; else SUDO="sudo"; fi

# ----------------------------------------------------------------------------
# Flag parsing
# ----------------------------------------------------------------------------
MODE="all"; INSTALL_CUDA=0; PURGE=0
for arg in "$@"; do
  case "$arg" in
    --all)          MODE="all" ;;
    --no-ollama)    MODE="no-ollama" ;;
    --user-space)   MODE="user-space" ;;
    --models-only)  MODE="models-only" ;;
    --check)        MODE="check" ;;
    --migrate-config) MODE="migrate-config" ;;
    --uninstall)    MODE="uninstall" ;;
    --install-cuda) INSTALL_CUDA=1 ;;
    --purge)        PURGE=1 ;;
    -h|--help)      grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)              die "unknown flag: $arg (try --help)" ;;
  esac
done

DO_SYSTEM=0; DO_PYENV=0; DO_PYDEPS=0; DO_MODELS=0; DO_OLLAMA=0; DO_PREFLIGHT=0
PULL_ONLY=0
case "$MODE" in
  all)         DO_SYSTEM=1; DO_PYENV=1; DO_PYDEPS=1; DO_MODELS=1; DO_OLLAMA=1; DO_PREFLIGHT=1 ;;
  no-ollama)   DO_SYSTEM=1; DO_PYENV=1; DO_PYDEPS=1; DO_MODELS=1; DO_OLLAMA=0; DO_PREFLIGHT=1 ;;
  # No sudo: everything that lives in user space. Assumes the system packages,
  # GPU driver, and Ollama service are already installed. Safe to delegate.
  user-space)  DO_PYENV=1; DO_PYDEPS=1; DO_MODELS=1; DO_OLLAMA=1; DO_PREFLIGHT=1; PULL_ONLY=1 ;;
  models-only) DO_MODELS=1 ;;
  check)         DO_PREFLIGHT=1 ;;
  migrate-config) : ;;   # handled separately in main()
  uninstall)     : ;;  # handled separately below
esac

# ----------------------------------------------------------------------------
# Config bootstrap + reader
# ----------------------------------------------------------------------------
ensure_pyyaml() {
  python3 -c "import yaml" 2>/dev/null && return 0
  log "Installing PyYAML (needed to read config)"
  python3 -m pip install --user pyyaml 2>/dev/null && return 0
  $SUDO apt-get install -y python3-yaml
}

bootstrap_config() {
  if [[ ! -f "$CONFIG" ]]; then
    [[ -f "$EXAMPLE" ]] || die "no config.yaml and no config.example.yaml found"
    cp "$EXAMPLE" "$CONFIG"
    ok "created config.yaml from config.example.yaml (uses \${USER_HOME})"
  fi
}

cfg() { python3 "$CONFIG_GET" "$1" --config "$CONFIG"; }

# ----------------------------------------------------------------------------
# Phase: system packages (+ optional CUDA)
# ----------------------------------------------------------------------------
phase_system() {
  log "System packages"
  have apt-get || die "apt-get not found; this installer targets Debian/Ubuntu"
  $SUDO apt-get update -qq
  local pkgs=(ffmpeg build-essential libssl-dev libffi-dev zlib1g-dev libbz2-dev
              libreadline-dev libsqlite3-dev libsndfile1 liblzma-dev curl git)
  # LibreOffice only if .odp output is requested.
  if cfg rendering.slides.formats 2>/dev/null | grep -qx "odp"; then
    have soffice || pkgs+=(libreoffice-impress)
  fi
  $SUDO apt-get install -y "${pkgs[@]}"
  ok "apt packages present"

  if have nvidia-smi && nvidia-smi >/dev/null 2>&1; then
    ok "NVIDIA GPU visible"
  elif [[ "$INSTALL_CUDA" -eq 1 ]]; then
    warn "attempting driver install (ubuntu-drivers autoinstall) — reboot afterwards"
    have ubuntu-drivers || $SUDO apt-get install -y ubuntu-drivers-common
    $SUDO ubuntu-drivers autoinstall || warn "driver autoinstall failed; install manually"
  else
    warn "no usable GPU (nvidia-smi). Install the driver, then re-run. (--install-cuda to attempt)"
  fi
}

# ----------------------------------------------------------------------------
# Phase: pyenv + virtualenvs
# ----------------------------------------------------------------------------
phase_pyenv() {
  log "pyenv + virtualenvs"
  local root whisper_env pyannote_env render_env pyenv
  root="$(cfg install.pyenv_root)"
  whisper_env="$(cfg install.whisper_env)"
  pyannote_env="$(cfg install.pyannote_env)"
  render_env="$(cfg install.render_env)"
  export PYENV_ROOT="$root"

  if [[ ! -x "$root/bin/pyenv" ]]; then
    log "installing pyenv into $root"
    curl -fsSL https://pyenv.run | bash
  fi
  pyenv="$root/bin/pyenv"
  [[ -x "$pyenv" ]] || die "pyenv not found at $pyenv after install"

  "$pyenv" install -s "$PY_VERSION"
  ok "python $PY_VERSION available"

  for env in "$whisper_env" "$pyannote_env" "$render_env"; do
    if [[ -d "$root/versions/$env" ]]; then
      ok "virtualenv exists: $env"
    else
      "$pyenv" virtualenv "$PY_VERSION" "$env"
      ok "created virtualenv: $env"
    fi
  done
}

# ----------------------------------------------------------------------------
# Phase: python dependencies
# ----------------------------------------------------------------------------
phase_pydeps() {
  log "Python dependencies"
  local wpy ppy rpy
  wpy="$(cfg env.whisper.python)"
  ppy="$(cfg env.pyannote.python)"
  rpy="$(cfg env.render.python)"
  [[ -x "$wpy" ]] || die "whisper interpreter missing: $wpy (run pyenv phase first)"
  [[ -x "$ppy" ]] || die "pyannote interpreter missing: $ppy (run pyenv phase first)"
  [[ -x "$rpy" ]] || die "render interpreter missing: $rpy (run pyenv phase first)"

  log "whisper-env deps"
  "$wpy" -m pip install -q --upgrade pip
  "$wpy" -m pip install -q faster-whisper ctranslate2 av
  ok "faster-whisper installed"

  log "pyannote-env deps (torch $TORCH_CUDA build)"
  "$ppy" -m pip install -q --upgrade pip
  "$ppy" -m pip install -q torch torchaudio --index-url "https://download.pytorch.org/whl/$TORCH_CUDA"
  # pinned to the 4.x API (DiarizeOutput) that scripts/diarize.py targets
  "$ppy" -m pip install -q "pyannote.audio>=4.0,<5" speechbrain soundfile numpy
  ok "pyannote.audio installed"

  log "render-env deps (document renderers)"
  "$rpy" -m pip install -q --upgrade pip
  "$rpy" -m pip install -q openpyxl python-pptx python-docx pyyaml
  ok "openpyxl + python-pptx + python-docx + pyyaml installed"
}

# ----------------------------------------------------------------------------
# Phase: models
# ----------------------------------------------------------------------------
phase_models() {
  log "Models"
  local wpy ppy wmodel wdir pdir hf_home tok diar emb
  wpy="$(cfg env.whisper.python)"
  ppy="$(cfg env.pyannote.python)"
  wmodel="$(cfg env.whisper.model)"
  wdir="$(cfg env.whisper.model_dir)"
  pdir="$(cfg env.pyannote.model_dir)"
  hf_home="$(cfg env.cuda.hf_home)"
  tok="$(cfg env.pyannote.hf_token_file)"
  diar="$(cfg env.pyannote.diarization_model)"
  emb="$(cfg env.pyannote.embedding_model)"
  mkdir -p "$wdir" "$pdir" "$hf_home"
  export HF_HOME="$hf_home"

  # Whisper weights
  if [[ -n "$(ls -A "$wdir" 2>/dev/null || true)" ]]; then
    ok "Whisper weights already present in $wdir"
  else
    log "downloading Whisper '$wmodel'"
    "$wpy" - "$wmodel" "$wdir" <<'PY'
import sys
from faster_whisper import WhisperModel
model, root = sys.argv[1], sys.argv[2]
WhisperModel(model, device="cpu", download_root=root)
print("downloaded", model)
PY
    ok "Whisper weights cached"
  fi

  # pyannote (gated — needs token + accepted license)
  if [[ ! -s "$tok" ]]; then
    warn "no HF token at $tok — skipping pyannote download."
    warn "  Accept licenses for: $diar  and  $emb"
    warn "  Then: printf '%s' 'hf_xxx' > '$tok' && chmod 600 '$tok'  and re-run --models-only"
    return 0
  fi
  log "caching pyannote models"
  HF_TOKEN="$(tr -d '\n' < "$tok")" "$ppy" - "$diar" "$emb" "$pdir" <<'PY'
import os, sys
from pyannote.audio import Pipeline, Model
diar, emb, cache = sys.argv[1], sys.argv[2], sys.argv[3]
tok = os.environ["HF_TOKEN"]
Pipeline.from_pretrained(diar, token=tok, cache_dir=cache)
Model.from_pretrained(emb, token=tok, cache_dir=cache)
print("cached pyannote models")
PY
  ok "pyannote models cached"
}

# ----------------------------------------------------------------------------
# Phase: Ollama (service + KV tuning + models)
# ----------------------------------------------------------------------------
phase_ollama() {
  if [[ "$(cfg install.manage_ollama)" != "true" ]]; then
    warn "install.manage_ollama is false — skipping Ollama"
    return 0
  fi
  log "Ollama"

  if [[ "$PULL_ONLY" -eq 1 ]]; then
    # No-sudo path: assume the service + KV-cache env were set up out-of-session.
    have ollama || warn "ollama binary not found — the service must be installed (sudo) first"
    warn "user-space mode: skipping service install + systemd drop-in (need sudo)"
  else
    if ! have ollama; then
      log "installing Ollama"
      curl -fsSL https://ollama.com/install.sh | sh
    fi
    ok "ollama present"

    # KV-cache tuning so the configured num_ctx fits 16 GB.
    local kv dropin_dir dropin
    kv="$(cfg ollama.kv_cache_type)"; [[ -n "$kv" ]] || kv="q8_0"
    dropin_dir="/etc/systemd/system/ollama.service.d"
    dropin="$dropin_dir/video-meeting.conf"
    if have systemctl; then
      $SUDO mkdir -p "$dropin_dir"
      printf '[Service]\nEnvironment="OLLAMA_FLASH_ATTENTION=1"\nEnvironment="OLLAMA_KV_CACHE_TYPE=%s"\n' "$kv" \
        | $SUDO tee "$dropin" >/dev/null
      $SUDO systemctl daemon-reload
      $SUDO systemctl restart ollama || warn "could not restart ollama service"
      ok "KV-cache env set (OLLAMA_KV_CACHE_TYPE=$kv, flash attention on)"
    else
      warn "no systemd — set OLLAMA_FLASH_ATTENTION=1 and OLLAMA_KV_CACHE_TYPE=$kv yourself"
    fi
  fi

  log "pulling models"
  while IFS= read -r m; do
    [[ -n "$m" ]] || continue
    ollama pull "$m"
  done < <(cfg install.ollama_models)
  ok "models pulled"

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
}

# ----------------------------------------------------------------------------
# Phase: preflight
# ----------------------------------------------------------------------------
phase_preflight() {
  log "Preflight"
  python3 "$SCRIPT_DIR/scripts/preflight.py" --config "$CONFIG"
}

# ----------------------------------------------------------------------------
# Uninstall
# ----------------------------------------------------------------------------
do_uninstall() {
  ensure_pyyaml; bootstrap_config
  log "Uninstalling"
  local root whisper_env pyannote_env wdir pdir work gdir
  root="$(cfg install.pyenv_root)"
  whisper_env="$(cfg install.whisper_env)"
  pyannote_env="$(cfg install.pyannote_env)"
  wdir="$(cfg env.whisper.model_dir)"
  pdir="$(cfg env.pyannote.model_dir)"
  work="$(cfg paths.work_dir)"
  gdir="$(cfg paths.global_dir)"

  rm -rf "$root/versions/$whisper_env" "$root/versions/$pyannote_env" && ok "removed virtualenvs"
  rm -rf "$wdir" "$pdir" "$work" && ok "removed model caches + work dir"
  if [[ "$PURGE" -eq 1 ]]; then
    rm -rf "$gdir" && warn "purged global participant registry: $gdir"
  else
    ok "kept global registry (use --purge to remove): $gdir"
  fi
  ok "left system ffmpeg and Ollama untouched"
}

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
main() {
  if [[ "$MODE" == "uninstall" ]]; then do_uninstall; exit 0; fi

  if [[ "$MODE" == "migrate-config" ]]; then
    ensure_pyyaml
    [[ -f "$CONFIG" ]] || die "no config.yaml to migrate (run install first)"
    python3 "$SCRIPT_DIR/scripts/migrate_config.py" --config "$CONFIG" --example "$EXAMPLE"
    exit 0
  fi

  ensure_pyyaml
  bootstrap_config

  [[ "$DO_SYSTEM"    -eq 1 ]] && phase_system
  [[ "$DO_PYENV"     -eq 1 ]] && phase_pyenv
  [[ "$DO_PYDEPS"    -eq 1 ]] && phase_pydeps
  [[ "$DO_MODELS"    -eq 1 ]] && phase_models
  [[ "$DO_OLLAMA"    -eq 1 ]] && phase_ollama
  [[ "$DO_PREFLIGHT" -eq 1 ]] && phase_preflight

  log "Done."
}

main
