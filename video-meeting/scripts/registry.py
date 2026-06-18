#!/usr/bin/env python3
"""
Global participant registry — the long-lived store that lets the skill recognize
returning people by voice across meetings.

Source of truth is a single JSON file (`participants.json`) plus per-participant
voiceprint samples on disk. Excel is treated as an export, never the source.

Layout under global_dir/:
  participants.json                 # source of truth (this module owns it)
  participants.csv                  # stdlib export (xlsx is produced via the xlsx skill)
  voiceprints/<participant_id>/NNNN.npy   # multiple embedding samples per person

Design choices that matter:
  - MULTIPLE samples per person (config voiceprints.max_samples_per_person). A new
    turn is matched against the whole set (best or mean similarity).
  - Writes are atomic (temp file + os.replace) under an flock, so concurrent runs
    can't corrupt the registry.
  - Registration happens ONLY when there is no confident match (caller decides).

This module is imported by identify_speakers.py and is also runnable for small
maintenance tasks:
  registry.py list   --global-dir DIR
  registry.py export --global-dir DIR
"""
import argparse
import csv
import datetime as _dt
import glob
import json
import os
import sys
import tempfile
from contextlib import contextmanager

import numpy as np

REGISTRY_VERSION = 1


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def reg_path(global_dir):
    return os.path.join(global_dir, "participants.json")


def voiceprints_dir(global_dir, pid=None):
    base = os.path.join(global_dir, "voiceprints")
    return os.path.join(base, pid) if pid else base


def today():
    return _dt.date.today().isoformat()


# --------------------------------------------------------------------------- #
# Locking + atomic IO
# --------------------------------------------------------------------------- #
@contextmanager
def locked(global_dir):
    """Advisory lock around a read-modify-write of the registry."""
    os.makedirs(global_dir, exist_ok=True)
    lock_file = os.path.join(global_dir, ".registry.lock")
    fd = open(lock_file, "w")
    try:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        except Exception:  # noqa: BLE001 (no fcntl on some platforms)
            pass
        yield
    finally:
        fd.close()


def load_registry(global_dir):
    path = reg_path(global_dir)
    if not os.path.isfile(path):
        return {"version": REGISTRY_VERSION, "participants": []}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_registry(global_dir, reg):
    os.makedirs(global_dir, exist_ok=True)
    path = reg_path(global_dir)
    fd, tmp = tempfile.mkstemp(dir=global_dir, prefix=".participants.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(reg, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)            # atomic on POSIX
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    export_csv(global_dir, reg)          # keep the flat export in sync


# --------------------------------------------------------------------------- #
# Participant helpers
# --------------------------------------------------------------------------- #
def _by_id(reg, pid):
    for p in reg["participants"]:
        if p["participant_id"] == pid:
            return p
    return None


def next_participant_id(reg):
    n = 0
    for p in reg["participants"]:
        try:
            n = max(n, int(p["participant_id"].split("_")[-1]))
        except (ValueError, KeyError):
            continue
    return f"p_{n + 1:04d}"


def display_name(p):
    name = " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x).strip()
    return name or p.get("display_name") or f"Unknown ({p['participant_id']})"


def load_samples(global_dir, p):
    """Return an (n_samples, dim) float32 array of a participant's voiceprints."""
    vecs = []
    for rel in p.get("voiceprints", []):
        fp = os.path.join(global_dir, rel)
        if os.path.isfile(fp):
            vecs.append(np.load(fp).astype("float32").reshape(-1))
    return np.vstack(vecs) if vecs else np.empty((0, 0), dtype="float32")


# --------------------------------------------------------------------------- #
# Similarity / matching
# --------------------------------------------------------------------------- #
def _norm(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def cosine(a, b):
    return float(np.dot(_norm(a), _norm(b)))


def score_against(query, samples, strategy="best"):
    """Similarity of a query vector to a participant's sample set."""
    if samples.size == 0:
        return -1.0
    sims = [cosine(query, s) for s in samples]
    return max(sims) if strategy == "best" else float(np.mean(sims))


def best_match(global_dir, reg, query, strategy="best"):
    """Return (participant_id, score) of the best-scoring participant, or (None, -1)."""
    best_pid, best_score = None, -1.0
    for p in reg["participants"]:
        s = score_against(query, load_samples(global_dir, p), strategy)
        if s > best_score:
            best_pid, best_score = p["participant_id"], s
    return best_pid, best_score


# --------------------------------------------------------------------------- #
# Mutations (caller is responsible for the lock + save)
# --------------------------------------------------------------------------- #
def _save_vector(global_dir, pid, index, vec):
    d = voiceprints_dir(global_dir, pid)
    os.makedirs(d, exist_ok=True)
    rel = os.path.join("voiceprints", pid, f"{index:04d}.npy")
    np.save(os.path.join(global_dir, rel), vec.astype("float32"))
    return rel


def add_participant(global_dir, reg, first_vec, meta=None):
    """Create a new participant seeded with one voiceprint sample. Returns the id."""
    pid = next_participant_id(reg)
    rel = _save_vector(global_dir, pid, 1, first_vec)
    p = {
        "participant_id": pid,
        "first_name": "", "last_name": "", "display_name": "",
        "description": "", "email": "", "contact": "",
        "voiceprints": [rel],
        "first_seen": today(), "last_seen": today(), "meetings_count": 1,
    }
    if meta:
        p.update({k: v for k, v in meta.items() if k in p})
    reg["participants"].append(p)
    return pid


def add_sample(global_dir, reg, pid, vec, max_samples=8):
    """Append a voiceprint sample, pruning oldest beyond the cap."""
    p = _by_id(reg, pid)
    if p is None:
        raise KeyError(pid)
    existing = p.get("voiceprints", [])
    idx = 1 + max((int(os.path.splitext(os.path.basename(r))[0]) for r in existing),
                  default=0)
    p.setdefault("voiceprints", []).append(_save_vector(global_dir, pid, idx, vec))
    # Prune oldest (lowest index) beyond the cap.
    while len(p["voiceprints"]) > max_samples:
        oldest = p["voiceprints"].pop(0)
        fp = os.path.join(global_dir, oldest)
        if os.path.isfile(fp):
            os.remove(fp)


def touch_meeting(reg, pid):
    p = _by_id(reg, pid)
    if p is not None:
        p["last_seen"] = today()
        p["meetings_count"] = int(p.get("meetings_count", 0)) + 1


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def export_csv(global_dir, reg=None):
    """Flat CSV export (stdlib). The polished participants.xlsx is produced
    separately via the xlsx skill from the same data."""
    if reg is None:
        reg = load_registry(global_dir)
    path = os.path.join(global_dir, "participants.csv")
    cols = ["participant_id", "first_name", "last_name", "display_name",
            "description", "email", "contact", "voiceprint_samples",
            "first_seen", "last_seen", "meetings_count"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for p in reg["participants"]:
            row = {c: p.get(c, "") for c in cols}
            row["display_name"] = display_name(p)
            row["voiceprint_samples"] = len(p.get("voiceprints", []))
            w.writerow(row)
    return path


# --------------------------------------------------------------------------- #
# Small CLI for maintenance
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Inspect/maintain the participant registry.")
    ap.add_argument("command", choices=["list", "export"])
    ap.add_argument("--global-dir", required=True)
    args = ap.parse_args()
    reg = load_registry(args.global_dir)
    if args.command == "list":
        if not reg["participants"]:
            print("(registry is empty)")
        for p in reg["participants"]:
            print(f"{p['participant_id']:8} {display_name(p):28} "
                  f"samples={len(p.get('voiceprints', []))} "
                  f"meetings={p.get('meetings_count', 0)} last_seen={p.get('last_seen','')}")
    elif args.command == "export":
        print("wrote", export_csv(args.global_dir, reg))


if __name__ == "__main__":
    main()
