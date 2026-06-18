# Tests

A stdlib `unittest` suite — no pytest or other test dependency. It validates the
deterministic logic of the pipeline and **skips gracefully** when an optional
dependency (numpy, openpyxl, python-pptx, python-docx, ffmpeg, LibreOffice) or a
service (Ollama, GPU) is absent. So it's useful both in a bare checkout and on the
fully installed laptop.

## Run

```bash
bash tests/run_tests.sh
# or directly:
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

To exercise the renderer tests too, run with a python that has the doc libraries —
on the laptop that is the render-env interpreter:

```bash
VM_TEST_PYTHON=~/.pyenv/versions/render-env/bin/python bash tests/run_tests.sh
```

## What is covered

| File | Covers | Needs |
|---|---|---|
| `test_offline.py` | config expansion/lookup; loose-JSON parsing; task normalize/merge; summarize helpers; build_record alignment/transcript/participants; run.py helpers + config-key wiring | stdlib only |
| `test_registry_identify.py` | registry add/match/sample-cap, CSV export; identify `match`→`confirm` hybrid flow with controlled-similarity voiceprints | numpy |
| `test_renderers.py` | tasks.xlsx / slides.pptx / report.docx generation; email `--no-llm` | openpyxl / python-pptx / python-docx |
| `test_cli.py` | every script parses `--help`; `extract_audio.py` against a real ffmpeg-made clip | ffmpeg (extract only) |

## Not covered here (require the live stack)

Whisper transcription, pyannote diarization, and the Ollama summary/task calls are
integration steps that need GPU + models + a running service. Validate those with a
real `run.py` invocation on the laptop after `install.sh --check` passes. The
fixtures in `fixtures.py` mirror the JSON shapes those stages emit, so the rest of
the pipeline is tested without them.
