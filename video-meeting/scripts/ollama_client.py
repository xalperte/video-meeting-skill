#!/usr/bin/env python3
"""
Minimal Ollama HTTP client (stdlib only).

Used by summarize.py and extract_tasks.py. Ollama is a running service reached
over HTTP — we never spawn the binary. `fmt="json"` asks Ollama to constrain the
output to valid JSON, which we rely on for structured task extraction.
"""
import json
import sys
import urllib.error
import urllib.request


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


def parse_json_loose(text):
    """Parse JSON that may be wrapped in prose or code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise
