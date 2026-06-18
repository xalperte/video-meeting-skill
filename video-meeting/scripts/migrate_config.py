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
    if apply(args.config, example):
        print(f"Appended missing keys. Backup: {args.config}.bak")
    else:
        print("No changes applied (some keys may need manual attention).")


if __name__ == "__main__":
    main()
