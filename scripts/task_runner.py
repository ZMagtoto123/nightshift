#!/usr/bin/env python3
"""
Whitelisted task runner - the single funnel for "run something" requests.

The web console and GitHub Actions both end up here. Tasks are declared in
tasks.json (versioned in git): adding a runnable task is a commit, never a
remote shell. That keeps the dispatch API safe to expose.

Usage:
    python scripts/task_runner.py <task> [--args-json '{"k":"v"}']
    python scripts/task_runner.py --payload .run/payload.json
    python scripts/task_runner.py --list

Task types:
    script  - fixed argv from tasks.json; {placeholder} fields are filled
              from args (unknown placeholders pass through verbatim); argv
              goes straight to subprocess, the shell is never invoked
    browser - headless Chromium job executed by scripts/browser_job.py
              (args: {"url": "...", "preset": "snapshot|text|uptime"} or
               a full {"spec": {...}} job spec)

Outputs:
    results/<task>/<utc-ts>/   result.json + collected files + screenshots
    state/tasks.json           rolling summary (last 50) for the dashboard
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob as globmod
import json
import os
import shutil
import subprocess
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS_FILE = os.path.join(ROOT, "tasks.json")
RESULTS_DIR = os.path.join(ROOT, "results")
STATE_DIR = os.path.join(ROOT, "state")
STATE_FILE = os.path.join(STATE_DIR, "tasks.json")
SUMMARY_KEEP = 50
STDOUT_TAIL = 6000


class _SafeDict(dict):
    """format_map helper: unknown {placeholders} pass through untouched."""

    def __missing__(self, key):
        return "{" + key + "}"


def load_registry() -> dict:
    with open(TASKS_FILE, encoding="utf-8") as f:
        reg = json.load(f)
    return {t["name"]: t for t in reg["tasks"]}


def _tail(text: str, limit: int = STDOUT_TAIL) -> str:
    text = text or ""
    return text[-limit:] if len(text) > limit else text


def _write_summary(entry: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    rows = []
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                rows = json.load(f)
    except Exception:
        rows = []
    rows.append(entry)
    rows = rows[-SUMMARY_KEEP:]
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)
    os.replace(tmp, STATE_FILE)


def _collect(task: dict, out_dir: str) -> list:
    """Copy the freshest files a task produced (collect_globs) into out_dir."""
    collected = []
    for pattern in task.get("collect_globs", []):
        matches = sorted(
            globmod.glob(os.path.join(ROOT, pattern)), key=os.path.getmtime
        )[-3:]
        for src in matches:
            dest = os.path.join(out_dir, os.path.basename(src))
            try:
                shutil.copy2(src, dest)
                collected.append(os.path.basename(src))
            except OSError:
                pass
    return collected


def run_script_task(task: dict, args: dict, out_dir: str) -> dict:
    merged = dict(task.get("defaults", {}))
    merged.update(args or {})
    argv = [part.format_map(_SafeDict(merged)) for part in task["run"]]
    timeout = int(task.get("timeout", 1800))
    started = time.time()
    try:
        proc = subprocess.run(
            argv, cwd=ROOT, timeout=timeout,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        exit_code, stdout, stderr, error = proc.returncode, proc.stdout, proc.stderr, None
    except subprocess.TimeoutExpired as e:
        def _dec(x):
            if x is None:
                return ""
            return x.decode(errors="replace") if isinstance(x, bytes) else str(x)
        exit_code, error = 124, f"timeout after {timeout}s"
        stdout, stderr = _dec(e.stdout), _dec(e.stderr)
    except FileNotFoundError as e:
        exit_code, error, stdout, stderr = 127, f"executable not found: {e}", "", ""

    return {
        "task": task["name"], "type": "script", "argv": argv,
        "exit_code": exit_code, "error": error,
        "seconds": round(time.time() - started, 1),
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr, 2000),
        "collected": _collect(task, out_dir),
    }


def _preset_steps(url: str, preset: str) -> list:
    base = [
        {"goto": url},
        {"wait_for": {"selector": "body", "timeout": 20000}},
        {"wait": 1500},
    ]
    if preset == "uptime":
        return base + [{"extract": {"selector": "title", "as": "title"}}]
    if preset == "text":
        return base + [
            {"extract_all": {"selector": "h1, h2, h3, p", "as": "text", "limit": 30}},
            {"screenshot": {"name": "page"}},
        ]
    # default: snapshot
    return base + [
        {"screenshot": {"name": "page", "full_page": True}},
        {"extract": {"selector": "title", "as": "title"}},
    ]


def run_browser_task(task: dict, args: dict, out_dir: str) -> dict:
    spec = (args or {}).get("spec")
    if not spec:
        url = (args or {}).get("url")
        if not url:
            raise ValueError("browser task needs args.url or args.spec")
        spec = {
            "name": (args or {}).get("name") or "job",
            "steps": _preset_steps(url, (args or {}).get("preset", "snapshot")),
        }
    spec_file = os.path.join(out_dir, "job_spec.json")
    with open(spec_file, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)
    argv = [
        sys.executable, os.path.join("scripts", "browser_job.py"),
        "--spec", spec_file, "--out", out_dir,
    ]
    timeout = int(task.get("timeout", 600))
    started = time.time()
    try:
        proc = subprocess.run(
            argv, cwd=ROOT, timeout=timeout,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        exit_code, stdout, stderr, error = proc.returncode, proc.stdout, proc.stderr, None
    except subprocess.TimeoutExpired:
        exit_code, stdout, stderr, error = 124, "", "", f"timeout after {timeout}s"

    return {
        "task": task["name"], "type": "browser",
        "exit_code": exit_code, "error": error,
        "seconds": round(time.time() - started, 1),
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr, 2000),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Whitelisted task runner")
    ap.add_argument("task", nargs="?", help="task name from tasks.json")
    ap.add_argument("--args-json", default="{}", help="JSON args for the task")
    ap.add_argument("--payload", help="JSON file {task, args} (used by CI)")
    ap.add_argument("--list", action="store_true", help="print available tasks")
    ns = ap.parse_args()

    registry = load_registry()
    if ns.list:
        for name, t in registry.items():
            print(f"{name:22} [{t.get('type', 'script'):7}] {t.get('description', '')}")
        return 0

    if ns.payload:
        with open(ns.payload, encoding="utf-8") as f:
            payload = json.load(f)
        task_name, args = payload.get("task"), payload.get("args") or {}
    elif ns.task:
        task_name, args = ns.task, json.loads(ns.args_json)
    else:
        ap.error("give a task name, --payload, or --list")
        return 2

    task = registry.get(task_name)
    if not task:
        print(f"[FAIL] unknown task '{task_name}'. Available: {', '.join(sorted(registry))}",
              file=sys.stderr)
        return 2

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(RESULTS_DIR, task_name, ts)
    os.makedirs(out_dir, exist_ok=True)
    started_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    print(f"[RUN] {task_name} [{task.get('type', 'script')}] -> {out_dir}", flush=True)
    ok = False
    try:
        if task.get("type") == "browser":
            result = run_browser_task(task, args, out_dir)
        else:
            result = run_script_task(task, args, out_dir)
        ok = result.get("exit_code") == 0
    except Exception as e:
        traceback.print_exc()
        result = {
            "task": task_name, "type": task.get("type", "script"),
            "exit_code": 1, "error": f"{type(e).__name__}: {e}",
        }

    result["started"] = started_iso
    result["finished"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    _write_summary({
        "task": task_name,
        "type": result.get("type"),
        "ok": ok,
        "exit_code": result.get("exit_code"),
        "seconds": result.get("seconds"),
        "started": started_iso,
        "finished": result["finished"],
        "error": (result.get("error") or (result.get("stderr_tail") or "")[-300:]) if not ok else "",
    })

    print(json.dumps(
        {k: v for k, v in result.items() if k not in ("stdout_tail", "stderr_tail")},
        indent=2, default=str,
    ))
    print("[OK]" if ok else "[FAIL]", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
