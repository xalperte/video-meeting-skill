#!/usr/bin/env bash
# Run the video-meeting test suite (stdlib unittest — no pytest needed).
#
# Tests degrade gracefully: anything needing numpy / openpyxl / python-pptx /
# python-docx / ffmpeg / LibreOffice is SKIPPED when that piece is absent, so the
# suite is meaningful both in a bare checkout and on the fully installed laptop.
#
# To exercise everything, run with the render-env python (which has the doc libs):
#   env.render.python in config.yaml, e.g.:
#   ~/.pyenv/versions/render-env/bin/python -m unittest discover -s tests -v
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
export USER_HOME="${USER_HOME:-${HOME:-/tmp/vm-test-home}}"
PY="${VM_TEST_PYTHON:-python3}"

echo "Running video-meeting tests with: $PY"
"$PY" -m unittest discover -s tests -p 'test_*.py' -v
