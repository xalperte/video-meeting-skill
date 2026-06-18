#!/usr/bin/env bash
# =============================================================================
# Store the Hugging Face token where the skill expects it (config:
# env.pyannote.hf_token_file), with 0600 permissions.
#
# The token is read from a silent prompt (or the HF_TOKEN env var) — it is never
# passed as a positional argument, so it stays out of your shell history.
#
# Run this ON THE MACHINE THAT RUNS THE PIPELINE (the Ubuntu/A5000 laptop):
#   bash scripts/set_hf_token.sh
#
# Reminder: you must also accept the model licenses while logged into the same
# HF account, or downloads 401 even with a valid token:
#   https://huggingface.co/pyannote/speaker-diarization-3.1
#   https://huggingface.co/pyannote/embedding
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${VM_CONFIG:-$SCRIPT_DIR/config.yaml}"
[[ -f "$CONFIG" ]] || CONFIG="$SCRIPT_DIR/config.example.yaml"
export USER_HOME="${USER_HOME:-$HOME}"

tok_path="$(python3 "$SCRIPT_DIR/scripts/config_get.py" env.pyannote.hf_token_file --config "$CONFIG")"

if [[ -n "${HF_TOKEN:-}" ]]; then
  token="$HF_TOKEN"
else
  read -rsp "Paste your Hugging Face token (input hidden): " token
  echo
fi

[[ -n "$token" ]] || { echo "No token provided." >&2; exit 1; }
case "$token" in
  hf_*) : ;;
  *) echo "Warning: token does not start with 'hf_' — continuing anyway." >&2 ;;
esac

mkdir -p "$(dirname "$tok_path")"
printf '%s' "$token" > "$tok_path"
chmod 600 "$tok_path"
echo "Saved token to: $tok_path (permissions 0600)"
echo "Next: accept the pyannote model licenses, then run: bash install.sh --models-only"
