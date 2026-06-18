#!/usr/bin/env bash
# =============================================================================
# package.sh — build a distributable .skill from a skill folder.
#
# A .skill is just a zip of the skill directory (with SKILL.md at its root). This
# script validates the SKILL.md frontmatter, strips build artifacts and secrets,
# and writes <skill-name>.skill. Self-contained — no external packager needed.
#
# Usage:
#   bash package.sh <skill-folder> [output-dir]
#
# Examples:
#   bash package.sh video-meeting           # -> ./video-meeting.skill
#   bash package.sh ./video-meeting ./dist  # -> ./dist/video-meeting.skill
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: bash package.sh <skill-folder> [output-dir]" >&2
  exit 1
fi

# Resolve the skill folder: accept a path or a bare name next to this script.
SKILL_ARG="$1"
if [[ -d "$SKILL_ARG" ]]; then
  SKILL_DIR="$(cd "$SKILL_ARG" && pwd)"
elif [[ -d "$SCRIPT_DIR/$SKILL_ARG" ]]; then
  SKILL_DIR="$(cd "$SCRIPT_DIR/$SKILL_ARG" && pwd)"
else
  echo "Error: skill folder not found: $SKILL_ARG" >&2
  exit 1
fi

OUT_DIR="${2:-$SCRIPT_DIR}"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

python3 - "$SKILL_DIR" "$OUT_DIR" <<'PY'
import os, re, sys, zipfile

skill_dir, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
name = os.path.basename(skill_dir)

# ---- exclusion rules (build artifacts + machine-specific + secrets) --------- #
EXCLUDE_DIRS   = {"__pycache__", "node_modules", ".git", ".venv", "venv"}
ROOT_EXCL_DIRS = {"evals"}                 # excluded only at the skill root
EXCLUDE_FILES  = {".DS_Store", "config.yaml", "hf_token"}   # config.yaml/token: never ship
EXCLUDE_GLOBS  = ("*.pyc", "*.token", "*token*.txt")

def excluded(rel):
    import fnmatch
    parts = rel.split(os.sep)
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    if any(fnmatch.fnmatch(p, "*.egg-info") for p in parts):
        return True
    if len(parts) > 1 and parts[0] in ROOT_EXCL_DIRS:
        return True
    base = parts[-1]
    if base in EXCLUDE_FILES:
        return True
    import fnmatch
    return any(fnmatch.fnmatch(base, g) for g in EXCLUDE_GLOBS)

# ---- validate SKILL.md ------------------------------------------------------ #
def fail(msg):
    sys.stderr.write(f"❌ {msg}\n"); sys.exit(1)

skill_md = os.path.join(skill_dir, "SKILL.md")
if not os.path.isfile(skill_md):
    fail(f"SKILL.md not found in {skill_dir}")

# exactly one packaged SKILL.md (nested ones are rejected on upload)
nested = []
for root, dirs, files in os.walk(skill_dir):
    rel_root = os.path.relpath(root, skill_dir)
    if rel_root != "." and excluded(os.path.join(name, rel_root)):
        dirs[:] = []
        continue
    for f in files:
        if f == "SKILL.md":
            nested.append(os.path.relpath(os.path.join(root, f), skill_dir))
if len(nested) > 1:
    fail("multiple SKILL.md files (exactly one allowed at <folder>/SKILL.md): "
         + ", ".join(sorted(nested)))

content = open(skill_md, encoding="utf-8").read()
m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
if not m:
    fail("SKILL.md has no YAML frontmatter")
fm_text = m.group(1)

# parse frontmatter (PyYAML if available, else a minimal flat parser)
try:
    import yaml
    fm = yaml.safe_load(fm_text) or {}
except Exception:
    fm = {}
    for line in fm_text.splitlines():
        mm = re.match(r"^([A-Za-z][\w-]*):\s?(.*)$", line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip().strip('"\'')

ALLOWED = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
extra = set(fm) - ALLOWED
if extra:
    fail(f"unexpected frontmatter key(s): {', '.join(sorted(extra))}")
nm, desc = (fm.get("name") or "").strip(), (fm.get("description") or "").strip()
comp = (fm.get("compatibility") or "").strip()
if not nm:
    fail("frontmatter missing 'name'")
if not desc:
    fail("frontmatter missing 'description'")
if not re.match(r"^[a-z0-9-]+$", nm) or nm.startswith("-") or nm.endswith("-") or "--" in nm:
    fail(f"name '{nm}' must be kebab-case (lowercase, digits, single hyphens)")
if len(nm) > 64:
    fail(f"name too long ({len(nm)} > 64)")
if "<" in desc or ">" in desc:
    fail("description cannot contain angle brackets (< or >)")
if len(desc) > 1024:
    fail(f"description too long ({len(desc)} > 1024)")
if comp and len(comp) > 500:
    fail(f"compatibility too long ({len(comp)} > 500)")

# ---- build the .skill (zip, arcname under <name>/) -------------------------- #
out_path = os.path.join(out_dir, f"{name}.skill")
added = skipped = 0
with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(skill_dir):
        # prune excluded dirs so we don't descend into them
        kept = []
        for dname in dirs:
            rel = os.path.relpath(os.path.join(root, dname), skill_dir)
            if not excluded(os.path.join(name, rel)):
                kept.append(dname)
            else:
                skipped += 1
        dirs[:] = kept
        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, skill_dir)
            arc = os.path.join(name, rel)
            if excluded(arc):
                skipped += 1
                continue
            z.write(full, arc)
            added += 1

size_kb = os.path.getsize(out_path) / 1024
print(f"✅ {name}: valid frontmatter")
print(f"   packaged {added} files ({skipped} excluded), {size_kb:.0f} KB")
print(f"   -> {out_path}")
PY
