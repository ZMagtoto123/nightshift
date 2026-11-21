"""
Action library - the building blocks every flow is made of.

Each action declares WHERE it runs:
  cloud - on GitHub's runners (no access to your PC)
  local - on YOUR pc via the local agent (full computer access)
  any   - cloud by default; a flow step can override with "where": "local"

A flow step's params can reference earlier outputs:
    "{{step1.video_id}}"  ->  output of step 1
and flow inputs:  "{{flow.title}}"

Add a new action = add a decorated function here + `python actions/library.py --dump`
to regenerate library.json (the dashboard's block menu).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
import webbrowser
from email.message import EmailMessage
from pathlib import Path

SCHEMAS: dict = {}


def action(name, where, title, params, outputs=None):
    def deco(fn):
        SCHEMAS[name] = {"where": where, "title": title, "params": params,
                         "outputs": outputs or [], "fn": fn}
        return fn
    return deco


# ---------------- cloud / any actions ----------------

@action("http_request", "any", "HTTP request (call any API)", {
    "url": {"type": "str", "required": True, "hint": "https://api.example.com/v1/thing"},
    "method": {"type": "str", "default": "GET"},
    "headers": {"type": "json", "default": "{}"},
    "body": {"type": "str", "default": ""},
}, outputs=["status", "body"])
def http_request(p, log):
    import requests
    headers = json.loads(p.get("headers") or "{}")
    r = requests.request(p.get("method", "GET").upper(), p["url"],
                         headers=headers, data=p.get("body") or None, timeout=60)
    log(f"HTTP {r.status_code} from {p['url']}")
    return {"status": r.status_code, "body": r.text[:6000]}


@action("download_file", "any", "Download a file to a folder", {
    "url": {"type": "str", "required": True},
    "folder": {"type": "str", "default": "downloads"},
}, outputs=["path", "bytes"])
def download_file(p, log):
    import requests
    folder = Path(os.path.expandvars(p.get("folder") or "downloads"))
    folder.mkdir(parents=True, exist_ok=True)
    name = p["url"].split("?")[0].rstrip("/").split("/")[-1] or "download.bin"
    dest = folder / name
    with requests.get(p["url"], stream=True, timeout=300) as r:
        r.raise_for_status()
        n = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
                n += len(chunk)
    log(f"saved {dest} ({n} bytes)")
    return {"path": str(dest), "bytes": n}


@action("email_send", "any", "Send an email (SMTP)", {
    "to": {"type": "str", "required": True},
    "subject": {"type": "str", "required": True},
    "body": {"type": "str", "required": True},
}, outputs=["sent"])
def email_send(p, log):
    host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    port = int(os.getenv("EMAIL_PORT", "587"))
    user, pw = os.getenv("EMAIL_USER"), os.getenv("EMAIL_PASS")
    if not user or not pw:
        raise RuntimeError("set EMAIL_USER / EMAIL_PASS secrets (Gmail: use an App Password)")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, p["to"], p["subject"]
    msg.set_content(p["body"])
    with smtplib.SMTP(host, port, timeout=60) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    log(f"email sent to {p['to']}")
    return {"sent": True}


@action("telegram_notify", "any", "Send a Telegram message", {
    "text": {"type": "str", "required": True},
}, outputs=["sent"])
def telegram_notify(p, log):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from notify import _send
    ok = _send(p["text"])
    log(f"telegram: {'sent' if ok else 'NOT sent (no token?)'}")
    return {"sent": ok}


# ---------------- local actions (your PC, via the agent) ----------------

@action("youtube_upload", "local", "Upload a video file to YouTube", {
    "file": {"type": "str", "required": True, "hint": "C:/Users/you/Videos/clip.mp4"},
    "title": {"type": "str", "required": True},
    "description": {"type": "str", "default": ""},
    "privacy": {"type": "str", "default": "private"},
    "tags": {"type": "str", "default": ""},
}, outputs=["video_id", "url"])
def youtube_upload(p, log):
    import requests
    cid, csec, rt = (os.getenv("YT_CLIENT_ID"), os.getenv("YT_CLIENT_SECRET"),
                     os.getenv("YT_REFRESH_TOKEN"))
    if not (cid and csec and rt):
        raise RuntimeError("set YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN "
                           "in the agent's .env (see AUTOMATION_SETUP.md, YouTube section)")
    tok = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": cid, "client_secret": csec,
        "refresh_token": rt, "grant_type": "refresh_token",
    }, timeout=60).json()["access_token"]
    meta = {
        "snippet": {"title": p["title"], "description": p.get("description", ""),
                    "tags": [t.strip() for t in p.get("tags", "").split(",") if t.strip()],
                    "categoryId": "22"},
        "status": {"privacyStatus": p.get("privacy", "private"),
                   "selfDeclaredMadeForKids": False},
    }
    size = os.path.getsize(p["file"])
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Length": str(size),
                 "X-Upload-Content-Type": "video/mp4"},
        data=json.dumps(meta), timeout=60)
    init.raise_for_status()
    log(f"uploading {p['file']} ({size/1e6:.1f} MB)...")
    with open(p["file"], "rb") as f:
        up = requests.put(init.headers["Location"],
                          headers={"Content-Length": str(size)}, data=f, timeout=7200)
    up.raise_for_status()
    vid = up.json().get("id", "?")
    log(f"uploaded -> https://youtu.be/{vid}")
    return {"video_id": vid, "url": f"https://youtu.be/{vid}"}


@action("organize_folder", "local", "Organize a folder by file type", {
    "folder": {"type": "str", "required": True, "hint": "%USERPROFILE%/Downloads"},
    "dry_run": {"type": "str", "default": "true"},
}, outputs=["count", "moved"])
def organize_folder(p, log):
    folder = Path(os.path.expandvars(p["folder"].strip()))
    groups = {".jpg": "images", ".jpeg": "images", ".png": "images", ".gif": "images",
              ".pdf": "docs", ".docx": "docs", ".txt": "docs", ".md": "docs",
              ".mp4": "video", ".mkv": "video", ".mp3": "audio", ".wav": "audio",
              ".zip": "archives", ".7z": "archives", ".exe": "installers", ".msi": "installers"}
    moved, dry = [], str(p.get("dry_run", "true")).lower() == "true"
    for f in folder.iterdir():
        if f.is_file():
            sub = groups.get(f.suffix.lower(), "other")
            moved.append(f"{f.name} -> {sub}/")
            if not dry:
                dest = folder / sub
                dest.mkdir(exist_ok=True)
                shutil.move(str(f), dest / f.name)
    log(f"{len(moved)} file(s) {'(dry run) ' if dry else ''}in {folder}")
    return {"count": len(moved), "moved": moved[:60]}


@action("run_command", "local", "Run a shell command on your PC", {
    "command": {"type": "str", "required": True, "hint": "git -C C:/proj pull"},
}, outputs=["exit", "stdout", "stderr"])
def run_command(p, log):
    proc = subprocess.run(p["command"], shell=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=900)
    log(f"command exit={proc.returncode}")
    return {"exit": proc.returncode,
            "stdout": (proc.stdout or "")[-3000:], "stderr": (proc.stderr or "")[-1500:]}


@action("open_url", "local", "Open a URL / app on your PC", {
    "url": {"type": "str", "required": True, "hint": "https://... or C:/app.exe"},
}, outputs=["opened"])
def open_url(p, log):
    target = os.path.expandvars(p["url"].strip())
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target):
        webbrowser.open(target)
    else:
        os.startfile(target)  # noqa: attribute-defined-outside-init - Windows-only
    log(f"opened {target}")
    return {"opened": target}


@action("screenshot_folder", "local", "List files in a folder on your PC", {
    "folder": {"type": "str", "required": True},
}, outputs=["count", "files"])
def list_folder(p, log):
    folder = Path(os.path.expandvars(p["folder"].strip()))
    files = sorted(f.name for f in folder.iterdir() if f.is_file())[:100]
    return {"count": len(files), "files": files}


# ---------------- file access (your PC, via the agent) ----------------

def _local_path(raw: str) -> Path:
    """Expand ~ and %VAR% and resolve to an absolute path."""
    return Path(os.path.expandvars(raw.strip().replace("\"", ""))).expanduser().resolve()


@action("read_file", "local", "Read a file from your PC", {
    "path": {"type": "str", "required": True, "hint": "C:/Users/you/notes/todo.txt"},
    "max_chars": {"type": "str", "default": "20000"},
}, outputs=["text", "bytes", "path"])
def read_file(p, log):
    f = _local_path(p["path"])
    data = f.read_bytes()
    limit = int(p.get("max_chars") or 20000)
    text = data.decode("utf-8", errors="replace")
    log(f"read {f} ({len(data)} bytes)")
    return {"text": text[:limit], "bytes": len(data), "path": str(f)}


@action("write_file", "local", "Write / create a file on your PC", {
    "path": {"type": "str", "required": True, "hint": "C:/Users/you/notes/out.txt"},
    "content": {"type": "str", "default": ""},
    "mode": {"type": "str", "default": "overwrite", "hint": "overwrite | append"},
}, outputs=["path", "bytes"])
def write_file(p, log):
    f = _local_path(p["path"])
    f.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if str(p.get("mode", "overwrite")).lower() == "append" else "w"
    with open(f, mode, encoding="utf-8") as fh:
        fh.write(p.get("content") or "")
    log(f"{mode} {f} ({len(p.get('content') or '')} chars)")
    return {"path": str(f), "bytes": len((p.get("content") or "").encode("utf-8"))}


@action("move_file", "local", "Move / rename a file on your PC", {
    "src": {"type": "str", "required": True},
    "dest": {"type": "str", "required": True, "hint": "folder or full new path"},
}, outputs=["src", "dest"])
def move_file(p, log):
    src, dest = _local_path(p["src"]), _local_path(p["dest"])
    if dest.is_dir() or str(p["dest"]).rstrip("/\\").endswith(("/", "\\")):
        dest = dest / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    log(f"moved {src} -> {dest}")
    return {"src": str(src), "dest": str(dest)}


@action("delete_file", "local", "Delete a file on your PC", {
    "path": {"type": "str", "required": True},
}, outputs=["deleted", "path"])
def delete_file(p, log):
    f = _local_path(p["path"])
    if not f.exists():
        log(f"already gone: {f}")
        return {"deleted": False, "path": str(f)}
    if f.is_dir():
        raise ValueError(f"refusing to delete a folder: {f} (folders are off-limits)")
    f.unlink()
    log(f"deleted {f}")
    return {"deleted": True, "path": str(f)}


@action("find_files", "local", "Find files on your PC (search a folder)", {
    "folder": {"type": "str", "required": True, "hint": "C:/Users/you/Documents"},
    "pattern": {"type": "str", "default": "*", "hint": "*.pdf, report*, *.mp4"},
    "recursive": {"type": "str", "default": "true"},
}, outputs=["count", "files"])
def find_files(p, log):
    folder = _local_path(p["folder"])
    pattern = p.get("pattern") or "*"
    it = folder.rglob(pattern) if str(p.get("recursive", "true")).lower() == "true" else folder.glob(pattern)
    files = []
    for f in it:
        if f.is_file():
            files.append({"path": str(f), "size": f.stat().st_size,
                          "modified": dt_mod(f)})
        if len(files) >= 200:
            break
    log(f"found {len(files)} file(s) matching '{pattern}' under {folder}")
    return {"count": len(files), "files": files}


def dt_mod(f: Path) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")


# ---------------- browser control (your PC, via the agent) ----------------

@action("browser_control", "local", "Control a browser on your PC (click, type, screenshot)", {
    "url": {"type": "str", "required": True, "hint": "https://site.com"},
    "steps": {"type": "json", "default": "[]",
              "hint": '[{"click":"#login"},{"type":{"selector":"#user","text":"me"}}]'},
    "screenshot": {"type": "str", "default": "true"},
    "show": {"type": "str", "default": "false", "hint": "true = visible window"},
}, outputs=["extracted", "screenshots", "results_dir"])
def browser_control(p, log):
    """Drive headless Chromium on this PC via scripts/browser_job.py."""
    import tempfile
    root = Path(__file__).resolve().parent.parent
    steps = json.loads(p.get("steps") or "[]")
    if not isinstance(steps, list):
        raise ValueError("'steps' must be a JSON list, e.g. [{\"click\": \"#btn\"}]")
    spec_steps = [{"goto": p["url"]}]
    spec_steps.extend(steps)
    if str(p.get("screenshot", "true")).lower() == "true":
        spec_steps.append({"screenshot": {"name": "page"}})
    spec = {"name": "block-browser-control", "steps": spec_steps}
    out_dir = Path(tempfile.mkdtemp(prefix="ns-browser-"))
    spec_file = out_dir / "spec.json"
    spec_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    argv = [sys.executable, str(root / "scripts" / "browser_job.py"),
            "--spec", str(spec_file), "--out", str(out_dir)]
    if str(p.get("show", "false")).lower() == "true":
        argv.append("--headed")
    log(f"browser job: {len(spec_steps)} step(s) -> {out_dir}")
    proc = subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-400:]
        detail = ""
        try:
            res = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
            detail = res.get("error") or ""
        except Exception:
            tail = tail or (proc.stdout or "")[-400:]
        raise RuntimeError(f"browser job failed (exit {proc.returncode}): "
                           f"{detail or tail}")
    data = {}
    results = out_dir / "results.json"
    if results.exists():
        data = json.loads(results.read_text(encoding="utf-8"))
    shots = [f.name for f in out_dir.glob("*.png")]
    log(f"done - extracted: {list(data.get('data', {}).keys())}, screenshots: {shots}")
    return {"extracted": data.get("data", {}), "screenshots": shots,
            "results_dir": str(out_dir)}


# ---------------- AI chat (cloud) ----------------

@action("ai_chat", "any", "Talk to an AI (GPT / Gemini / any OpenAI-compatible API)", {
    "prompt": {"type": "str", "required": True,
               "hint": "summarize this: {{step1.body}}"},
    "system": {"type": "str", "default": "You are a helpful assistant."},
    "model": {"type": "str", "default": "", "hint": "gpt-4o-mini, gemini-2.0-flash, ..."},
}, outputs=["reply"])
def ai_chat(p, log):
    """Call an OpenAI-compatible chat API. Works with OpenAI, Gemini's
    OpenAI-compatible endpoint, Groq, Ollama, LM Studio - anything that
    speaks /chat/completions."""
    import requests
    key = (os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
           or os.getenv("GEMINI_API_KEY") or os.getenv("GROQ_API_KEY"))
    base = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    model = p.get("model") or os.getenv("AI_MODEL", "gpt-4o-mini")
    if not key:
        raise RuntimeError(
            "no AI key found. set AI_API_KEY (and optionally AI_BASE_URL / AI_MODEL) "
            "in the agent .env or repo secrets. Gemini: base url "
            "https://generativelanguage.googleapis.com/v1beta/openai")
    r = requests.post(f"{base.rstrip('/')}/chat/completions", timeout=120, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
    }, json={
        "model": model,
        "messages": [
            {"role": "system", "content": p.get("system") or "You are a helpful assistant."},
            {"role": "user", "content": p["prompt"]},
        ],
    })
    if r.status_code >= 400:
        raise RuntimeError(f"AI API error {r.status_code}: {r.text[:400]}")
    reply = r.json()["choices"][0]["message"]["content"]
    log(f"AI ({model}) replied: {reply[:120]}...")
    return {"reply": reply}


def run_action(name: str, params: dict, log=print) -> dict:
    if name not in SCHEMAS:
        raise KeyError(f"unknown action '{name}' (available: {', '.join(sorted(SCHEMAS))})")
    spec = SCHEMAS[name]["params"]
    params = dict(params or {})
    for k, s in spec.items():
        if params.get(k) in (None, "") and "default" in s:
            params[k] = s["default"]
        if s.get("required") and params.get(k) in (None, ""):
            raise ValueError(f"action '{name}' missing required param '{k}'")
    return SCHEMAS[name]["fn"](params, log)


def dump(path: str) -> None:
    lib = {n: {k: v for k, v in s.items() if k != "fn"} for n, s in SCHEMAS.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lib, f, indent=2)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    dump(here / "library.json")
    print(f"[OK] library.json: {len(SCHEMAS)} actions -> {here / 'library.json'}")
