#!/usr/bin/env python3
"""
NIGHTSHIFT local agent - gives your flows full access to THIS computer.

Pull-based (safe): the agent polls your repo every ~15s for queued local
jobs, executes them here (files, apps, uploads), and commits the results
back to state/agent_results/. No ports opened, nothing listens - your PC
reaches out to GitHub only.

Setup:
  1. create agent/.env with:
       AGENT_REPO=your-name/nightshift
       AGENT_TOKEN=<fine-grained PAT: this repo, Contents read+write>
     (EMAIL_*, YT_* secrets the actions need go here too)
  2. python agent/local_agent.py            (keep the window open, or)
     run agent/install_startup.bat once     (auto-start with Windows)

Only people with WRITE access to your repo can queue jobs for this agent -
that's you. Keep your AGENT_TOKEN private.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "actions"))

STATE_FILE = Path(__file__).resolve().parent / "agent_state.json"
RESULTS_DIR_REMOTE = "state/agent_results"
LOG_FILE_REMOTE = "state/agent_log.json"
POLL_SECONDS = 15
LOG_KEEP = 30


def env(name, default=None):
    val = os_get(name)
    if val:
        return val
    dotenv = ROOT / "agent" / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


def os_get(name):
    import os
    return os.getenv(name)


def gh_api(path, method="GET", body=None, token=None):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        headers={"Accept": "application/vnd.github+json",
                 "Authorization": f"Bearer {token}",
                 "User-Agent": "nightshift-agent"},
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def raw_file(repo, path):
    import urllib.request
    url = f"https://raw.githubusercontent.com/{repo}/HEAD/{path}?t={dt.datetime.now().timestamp()}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read().decode()
    except Exception:
        return None


def commit_file(repo, token, path, content: str, message: str) -> bool:
    code, cur = gh_api(f"/repos/{repo}/contents/{path}", token=token)
    sha = cur.get("sha") if code == 200 else None
    body = {"message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "sha": sha}
    code, _ = gh_api(f"/repos/{repo}/contents/{path}", method="PUT", body=body, token=token)
    if code not in (200, 201):
        print(f"[WARN] commit {path} failed: HTTP {code}")
        return False
    return True


def append_log(repo, token, entry: dict) -> None:
    log = []
    raw = raw_file(repo, LOG_FILE_REMOTE)
    if raw:
        try:
            log = json.loads(raw)
        except Exception:
            log = []
    log.append(entry)
    commit_file(repo, token, LOG_FILE_REMOTE,
                json.dumps(log[-LOG_KEEP:], indent=2, default=str),
                f"agent: {entry.get('action')} {'ok' if entry.get('ok') else 'FAILED'} [skip ci]")


def load_done() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def save_done(done: set) -> None:
    STATE_FILE.write_text(json.dumps(sorted(done)[-500:]), encoding="utf-8")


def process_queue(repo: str, token: str, once: bool) -> None:
    import library

    done = load_done()
    while True:
        raw = raw_file(repo, "state/agent_queue.json")
        jobs = []
        if raw:
            try:
                jobs = json.loads(raw)
            except Exception:
                jobs = []
        pending = [j for j in jobs if j.get("id") and j["id"] not in done]
        if pending:
            print(f"[agent] {len(pending)} job(s) queued")
        for job in pending:
            jid, act = job["id"], job.get("action")
            print(f"[agent] run {jid}: {act} {json.dumps(job.get('params', {}))[:140]}")
            started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            try:
                out = library.run_action(act, job.get("params") or {},
                                         log=lambda m: print(f"    {m}"))
                result = {"id": jid, "flow": job.get("flow"), "action": act,
                          "ok": True, "ts": started, "output": out}
            except Exception as e:  # noqa: BLE001 - report, never crash the agent
                result = {"id": jid, "flow": job.get("flow"), "action": act,
                          "ok": False, "ts": started, "error": f"{type(e).__name__}: {e}"}
                print(f"    FAILED: {result['error']}")
            commit_file(repo, token, f"{RESULTS_DIR_REMOTE}/{jid}.json",
                        json.dumps(result, indent=2, default=str),
                        f"agent: {act} {'ok' if result['ok'] else 'FAILED'} [skip ci]")
            append_log(repo, token, {"id": jid, "action": act, "flow": job.get("flow"),
                                     "ok": result["ok"], "ts": started,
                                     "detail": (result.get("error") or json.dumps(result.get("output", {}))[:160])})
            done.add(jid)
            save_done(done)
        if once:
            break
        time.sleep(POLL_SECONDS)


def main() -> int:
    ap = argparse.ArgumentParser(description="NIGHTSHIFT local agent")
    ap.add_argument("--once", action="store_true", help="single poll, then exit")
    ns = ap.parse_args()

    repo = env("AGENT_REPO")
    token = env("AGENT_TOKEN")
    if not repo or not token:
        print("[FAIL] set AGENT_REPO and AGENT_TOKEN in agent/.env (see file header)")
        return 2

    print(f"[agent] NIGHTSHIFT local agent online -> {repo} "
          f"(poll {POLL_SECONDS}s, Ctrl+C to stop)")
    try:
        process_queue(repo, token, ns.once)
    except KeyboardInterrupt:
        print("\n[agent] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
