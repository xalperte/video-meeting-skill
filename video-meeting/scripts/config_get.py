#!/usr/bin/env python3
"""
Read values from the video-meeting config.yaml.

Shared by install.sh and preflight.py (and the pipeline scripts) so there is one
place that knows how to load config and expand path tokens.

Expansion rules:
  - ${USER_HOME} defaults to the invoking user's $HOME if USER_HOME is unset.
  - Any ${ENV_VAR} in a string value is expanded from the environment.

Usage:
  config_get.py env.whisper.python                 # print one value
  config_get.py ollama.ollama_models               # list -> one item per line
  config_get.py install.ollama_models --json       # raw JSON
  config_get.py --config /path/to/config.yaml KEY
  config_get.py                                     # dump the whole expanded config

Importable API:
  from config_get import load_config, get
"""
import argparse
import json
import os
import sys


def _expand(obj):
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    if isinstance(obj, list):
        return [_expand(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _expand(v) for k, v in obj.items()}
    return obj


def load_config(path):
    """Load and env-expand the config. Exits with code 3 if PyYAML is missing,
    2 if the file does not exist."""
    try:
        import yaml  # noqa: WPS433 (intentional lazy import)
    except ImportError:
        sys.stderr.write(
            "PyYAML is required to read the config.\n"
            "Install it with:  python3 -m pip install --user pyyaml\n"
            "             or:  sudo apt-get install -y python3-yaml\n"
        )
        sys.exit(3)
    # Default USER_HOME so ${USER_HOME} resolves even when not exported.
    os.environ.setdefault("USER_HOME", os.path.expanduser("~"))
    if not os.path.isfile(path):
        sys.stderr.write(f"Config not found: {path}\n")
        sys.exit(2)
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return _expand(data)


def get(data, dotted, default=None):
    """Fetch a dotted key path, e.g. 'env.whisper.python'."""
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def main():
    ap = argparse.ArgumentParser(description="Read a value from the config.")
    ap.add_argument("key", nargs="?", help="dotted key path, e.g. env.whisper.python")
    ap.add_argument(
        "--config",
        default=os.environ.get("VM_CONFIG", "config.yaml"),
        help="path to config.yaml (default: $VM_CONFIG or ./config.yaml)",
    )
    ap.add_argument("--json", action="store_true", help="print value as JSON")
    args = ap.parse_args()

    data = load_config(args.config)

    if args.key is None:
        print(json.dumps(data, indent=2))
        return

    sentinel = object()
    val = get(data, args.key, sentinel)
    if val is sentinel:
        sys.stderr.write(f"Key not found: {args.key}\n")
        sys.exit(4)

    if args.json:
        print(json.dumps(val))
    elif isinstance(val, list):
        for item in val:
            print(item)
    elif isinstance(val, bool):
        print("true" if val else "false")
    elif val is None:
        print("")
    else:
        print(val)


if __name__ == "__main__":
    main()
