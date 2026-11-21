#!/usr/bin/env python3
"""
Generic pipeline scheduler - the heart of "it runs while you sleep".

pipelines.json defines named pipelines: a cron expression (UTC), the task to
run (from tasks.json) and its args. This script runs on a 5-minute GitHub
Actions cron; every firing it checks which pipelines are due and executes
them through the whitelisted task runner.

A pipeline whose scheduled minute was skipped by GitHub's cron lag is simply
skipped (no catch-up) - design schedules coarser than 5 minutes.

Also writes state/status.json (the console's heartbeat) after every pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINES_FILE = ROOT / "pipelines.json"
TASKS_FILE = ROOT / "tasks.json"
STATE_DIR = ROOT / "state"
STATUS_FILE = STATE_DIR / "status.json"
RUNNER = ROOT / "scripts" / "task_runner.py"


# ---------------- cron matching (5-field, UTC) ----------------

def _match_field(expr: str, val: int) -> bool:
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*" or part == str(val):
            return True
        if part.startswith("*/"):
            try:
                if val % int(part[2:]) == 0:
                    return True
            except ValueError:
                continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                if int(a) <= val <= int(b):
                    return True
            except ValueError:
                continue
    return False


def cron_matches(expr: str, now: datetime) -> bool:
    """Standard 5-field cron. Note: cron dow 0=Sun..6=Sat, python dow Mon=0."""
    fields = expr.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    cron_dow = (now.weekday() + 1) % 7  # Mon(0)->1 ... Sun(6)->0
    return (
        _match_field(minute, now.minute)
        and _match_field(hour, now.hour)
        and _match_field(dom, now.day)
        and _match_field(month, now.month)
        and _match_field(dow, cron_dow)
    )


# ---------------- registry ----------------

def load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def run_task(name: str, args: dict, timeout: int) -> dict:
    cmd = [
        sys.executable, str(RUNNER), name,
        "--args-json", json.dumps(args or {}),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, timeout=timeout,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        ok = proc.returncode == 0
        tail = (proc.stdout or "")[-800:]
    except subprocess.TimeoutExpired:
        ok, tail = False, f"timeout after {timeout}s"
    return {"ok": ok, "tail": tail.strip().splitlines()[-3:] if tail else []}


def task_timeout(name: str, registry: dict) -> int:
    t = registry.get(name) or {}
    return int(t.get("timeout", 900))


def compute_due(now: datetime, force_all: bool = False) -> list:
    pipelines = (load_json(PIPELINES_FILE, {"pipelines": []})).get("pipelines", [])
    if force_all:
        return [p for p in pipelines if p.get("enabled", True)]
    return [
        p for p in pipelines
        if p.get("enabled", True) and cron_matches(str(p.get("cron", "")), now)
    ]


def main() -> int:
    now = datetime.now(timezone.utc)
    force_all = "all" in (os.environ.get("FORCE") or "").strip().lower()
    pipelines = (load_json(PIPELINES_FILE, {"pipelines": []})).get("pipelines", [])
    registry = {t["name"]: t for t in (load_json(TASKS_FILE, {"tasks": []})).get("tasks", [])}

    # CI pre-flight mode: report which task types are due so the workflow can
    # install the browser runtime only when a browser pipeline actually runs.
    if "--print-due-types" in sys.argv:
        due = compute_due(now, force_all)
        types = sorted({(registry.get(p.get("task")) or {}).get("type", "script") for p in due})
        print("\n".join(types) if types else "none")
        return 0

    due = compute_due(now, force_all)
    print(f"[scheduler] {now.isoformat(timespec='seconds')} - "
          f"{len(pipelines)} pipeline(s), {len(due)} due")

    results = []
    failed = False
    for p in due:
        name = p.get("name") or p.get("task")
        task = p.get("task")
        if task not in registry:
            results.append({"pipeline": name, "task": task, "ok": False, "seconds": 0,
                            "error": f"unknown task '{task}' (define it in tasks.json)"})
            failed = True
            continue
        print(f"[run] pipeline '{name}' -> task '{task}' args={p.get('args', {})}")
        r = run_task(task, p.get("args") or {}, task_timeout(task, registry))
        results.append({"pipeline": name, "task": task, "ok": r["ok"],
                        "error": "" if r["ok"] else " | ".join(r["tail"])})
        if not r["ok"]:
            failed = True

    STATE_DIR.mkdir(exist_ok=True)
    status = {
        "ts": now.isoformat(timespec="seconds"),
        "checked": len(pipelines),
        "ran": [
            {**r, "seconds": r.get("seconds", 0)} for r in results
        ],
    }
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, default=str)

    for r in results:
        print(f"  {'[OK]' if r['ok'] else '[FAIL]'} {r['pipeline']} ({r['task']})"
              + (f": {r.get('error', '')[:120]}" if not r["ok"] else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
