#!/usr/bin/env python3
"""
Flow runner - executes a flow from flows.json, no scripts needed.

A flow is an ordered list of steps: {"action": "<block from actions/library>",
"params": {...}}. Cloud steps run right here; LOCAL steps (your-PC actions
like youtube_upload or organize_folder) are queued in state/agent_queue.json
for the local agent to pull and execute.

Step outputs feed later steps:  "{{step1.url}}"  (and  "{{flow.x}}" for the
--args-json inputs). Results go to state/flows.json + state/flow_outputs/.

Usage:  python scripts/flow_runner.py --flow <name> [--args-json '{"x":1}']
        python scripts/flow_runner.py --list
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "actions"))

FLOWS_FILE = ROOT / "flows.json"
QUEUE_FILE = ROOT / "state" / "agent_queue.json"
STATE_FILE = ROOT / "state" / "flows.json"
OUTPUTS_DIR = ROOT / "state" / "flow_outputs"
KEEP_SUMMARY = 50
QUEUE_KEEP = 100

PLACEHOLDER = re.compile(r"\{\{\s*(step\d+|flow)\.([\w\-]+)\s*\}\}")


def load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    Path(tmp).replace(path)


def substitute(value, outputs, flow_args):
    if not isinstance(value, str):
        return value

    def repl(m):
        src, key = m.group(1), m.group(2)
        bag = outputs if src.startswith("step") else flow_args
        return str((bag or {}).get(src, "") if src.startswith("step") else (bag or {}).get(key, ""))

    return PLACEHOLDER.sub(repl, value)


def run_flow(flow: dict, flow_args: dict) -> dict:
    import library

    name = flow.get("name") or "flow"
    outputs, steps_report = {}, []
    queue = load_json(QUEUE_FILE, [])
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    for i, step in enumerate(flow.get("steps") or [], 1):
        act = step.get("action")
        if act not in library.SCHEMAS:
            raise KeyError(f"step {i}: unknown action '{act}'")
        schema = library.SCHEMAS[act]
        params = {k: substitute(v, outputs, flow_args) for k, v in (step.get("params") or {}).items()}
        where = step.get("where") or schema["where"]
        key = f"step{i}"

        if where == "local":
            job_id = f"{name[:20]}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S')}-{i}"
            queue.append({"id": job_id, "flow": name, "step": i, "action": act,
                          "params": params, "queued": ts})
            queue = queue[-QUEUE_KEEP:]
            outputs[key] = {"queued": job_id, "status": "sent to your PC agent"}
            steps_report.append({"step": i, "action": act, "where": "local",
                                 "ok": True, "detail": f"queued {job_id}"})
            print(f"[step {i}] {act} -> queued for local agent ({job_id})")
        else:
            print(f"[step {i}] {act} ({where}) params={ {k: (str(v)[:60]) for k, v in params.items()} }")
            out = library.run_action(act, params, log=lambda m: print(f"    {m}"))
            outputs[key] = out if isinstance(out, dict) else {"value": out}
            steps_report.append({"step": i, "action": act, "where": where,
                                 "ok": True, "detail": str(out)[:200]})
            print(f"[step {i}] OK -> {str(out)[:160]}")

    save_json(QUEUE_FILE, queue)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    save_json(OUTPUTS_DIR / f"{name}.json", outputs)

    summary = load_json(STATE_FILE, [])
    summary.append({"flow": name, "ts": ts,
                    "steps": [{"step": s["step"], "action": s["action"],
                               "where": s["where"]} for s in steps_report]})
    save_json(STATE_FILE, summary[-KEEP_SUMMARY:])
    return outputs


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a flow from flows.json")
    ap.add_argument("--flow")
    ap.add_argument("--args-json", default="{}")
    ap.add_argument("--list", action="store_true")
    ns = ap.parse_args()

    flows = (load_json(FLOWS_FILE, {"flows": []})).get("flows", [])
    if ns.list:
        for f in flows:
            print(f"{f.get('name', '?'):24} {len(f.get('steps', []))} step(s)")
        return 0
    if not ns.flow:
        ap.error("--flow or --list required")

    flow = next((f for f in flows if f.get("name") == ns.flow), None)
    if not flow:
        print(f"[FAIL] no flow named '{ns.flow}'. Have: {', '.join(f.get('name', '?') for f in flows)}",
              file=sys.stderr)
        return 2

    try:
        flow_args = json.loads(ns.args_json)
    except json.JSONDecodeError:
        flow_args = {}

    print(f"[FLOW] {ns.flow} - {len(flow.get('steps', []))} step(s)")
    run_flow(flow, flow_args)
    print("[FLOW] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
