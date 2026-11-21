#!/usr/bin/env python3
"""
Build a clean github-upload/ folder ready to drag into github.com/new.

Copies everything the repo needs (workflows, dashboard, actions, agent,
scripts, docs, json config) and excludes local/private stuff:
  agent/.env, agent/agent_state.json, results/, __pycache__, *.log, .git

Usage:  python scripts/make_github_bundle.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "github-upload"

COPY_TOP = ["README.md", "flows.json", "tasks.json", "pipelines.json", "notify.py"]
COPY_DIRS = ["actions", "agent", "dashboard", "docs", "scripts", ".github"]
STATE_KEEP = ["tasks.json"]  # rolling state scaffolding (safe to publish)

EXCLUDE_NAMES = {".env", "agent_state.json", "__pycache__", ".git",
                 "results", ".run", "github-upload", "graphify-out"}
EXCLUDE_SUFFIX = {".log", ".pyc", ".tmp"}


def excluded(p: Path) -> bool:
    return p.name in EXCLUDE_NAMES or p.suffix in EXCLUDE_SUFFIX


def copy_tree(src: Path, dst: Path) -> int:
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for item in src.iterdir():
        if excluded(item):
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(
                *{n.lower() for n in EXCLUDE_NAMES}),
                dirs_exist_ok=True)
            n += sum(1 for _ in target.rglob("*") if _.is_file())
        else:
            shutil.copy2(item, target)
            n += 1
    return n


def main() -> int:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir()

    total = 0
    for name in COPY_TOP:
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, DEST / name)
            total += 1
    for d in COPY_DIRS:
        if (ROOT / d).exists():
            total += copy_tree(ROOT / d, DEST / d)

    state = DEST / "state"
    state.mkdir(exist_ok=True)
    for name in STATE_KEEP:
        if (ROOT / "state" / name).exists():
            shutil.copy2(ROOT / "state" / name, state / name)
    for empty in ("state/flow_outputs", "state/agent_results"):
        (DEST / empty).mkdir(parents=True, exist_ok=True)
        (DEST / empty / ".gitkeep").touch()

    print(f"[OK] {total} files -> {DEST}")
    print("next: github.com/new -> create a PUBLIC repo -> 'uploading an existing")
    print("file' -> drag EVERYTHING from github-upload/ in -> commit.")
    print("(agent/.env, caches, results are excluded - they stay on your PC)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
