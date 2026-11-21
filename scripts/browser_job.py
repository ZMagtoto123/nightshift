#!/usr/bin/env python3
"""
Headless Chromium job runner (Playwright) - "browser control" for the bot.

A job spec is JSON with an ordered step list; each step maps 1:1 to a
Playwright call with its own timeout, and every step's outcome is recorded.
Screenshots and extracted data land in --out DIR as PNGs + results.json.

Supported steps:
  {"goto": "https://..."}                                        navigate
  {"click": "css-selector"}                                      click
  {"type": {"selector": "...", "text": "...", "submit": false}}  fill (+Enter)
  {"press": "Enter"}                                             key press
  {"scroll": 800}                                                wheel scroll (px)
  {"wait": 1200}                                                 sleep ms
  {"wait_for": {"selector": "...", "timeout": 15000}}            wait for selector
  {"screenshot": {"name": "page", "full_page": false}}           PNG
  {"extract": {"selector": "...", "attr": "text|html|<attr>", "as": "name"}}
  {"extract_all": {"selector": "...", "attr": "text", "as": "name", "limit": 50}}
  {"eval": {"script": "() => document.title", "as": "name"}}     page-context JS

Example:
  {"name": "market-check",
   "steps": [{"goto": "https://example.com"},
             {"wait_for": {"selector": "h1"}},
             {"screenshot": {"name": "page", "full_page": true}},
             {"extract": {"selector": "h1", "as": "headline"}}]}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import traceback


def _shot(page, path: str) -> str:
    page.screenshot(path=path, full_page=False)
    return os.path.basename(path)


def _attr_of(el, attr):
    if attr in (None, "text"):
        return el.inner_text()
    if attr == "html":
        return el.inner_html()
    return el.get_attribute(attr)


def _do(page, action, detail, out_dir, data, shots):
    """Execute one step; returns a short human-readable detail string."""
    if action == "goto":
        if isinstance(detail, str):
            url, timeout, wait_until = detail, 30000, "domcontentloaded"
        else:
            url = detail["url"]
            timeout = int(detail.get("timeout", 30000))
            wait_until = detail.get("wait_until", "domcontentloaded")
        resp = page.goto(url, timeout=timeout, wait_until=wait_until)
        return f"status={resp.status if resp else '?'} url={page.url}"
    if action == "click":
        page.click(detail)
        return f"clicked {detail}"
    if action == "type":
        page.fill(detail["selector"], detail.get("text", ""))
        if detail.get("submit"):
            page.keyboard.press("Enter")
        return f"filled {detail['selector']}"
    if action == "press":
        page.keyboard.press(detail)
        return f"pressed {detail}"
    if action == "scroll":
        page.mouse.wheel(0, int(detail))
        page.wait_for_timeout(300)
        return f"scrolled {detail}px"
    if action == "wait":
        page.wait_for_timeout(int(detail))
        return f"waited {detail}ms"
    if action == "wait_for":
        page.wait_for_selector(detail["selector"], timeout=int(detail.get("timeout", 15000)))
        return f"found {detail['selector']}"
    if action == "screenshot":
        name = detail.get("name", f"shot{len(shots) + 1}")
        path = os.path.join(out_dir, f"{name}.png")
        page.screenshot(path=path, full_page=bool(detail.get("full_page")))
        shots.append(os.path.basename(path))
        return os.path.basename(path)
    if action == "extract":
        cfg = detail
        el = page.locator(cfg["selector"]).first
        val = _attr_of(el, cfg.get("attr", "text"))
        data[cfg.get("as", "extract")] = val
        return f"{cfg.get('as')}: {str(val)[:120]}"
    if action == "extract_all":
        cfg = detail
        loc = page.locator(cfg["selector"])
        n = min(loc.count(), int(cfg.get("limit", 50)))
        vals = [_attr_of(loc.nth(i), cfg.get("attr", "text")) for i in range(n)]
        data[cfg.get("as", "extract_all")] = vals
        return f"{n} matches"
    if action == "eval":
        val = page.evaluate(detail["script"])
        data[detail.get("as", "eval")] = val
        return f"{detail.get('as')}: {str(val)[:120]}"
    raise ValueError(f"unknown step action: {action}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a headless browser job spec")
    ap.add_argument("--spec", required=True, help="job spec JSON file")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser window instead of headless")
    ns = ap.parse_args()

    os.makedirs(ns.out, exist_ok=True)
    with open(ns.spec, encoding="utf-8") as f:
        spec = json.load(f)

    try:
        from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright
    except ImportError:
        print("[FAIL] playwright not installed: pip install playwright && "
              "playwright install --with-deps chromium", file=sys.stderr)
        return 3

    steps_out, data, shots = [], {}, []
    t0 = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not ns.headed)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
            locale="en-US",
        )
        ctx.set_default_timeout(20000)
        page = ctx.new_page()
        error = None
        try:
            for i, raw in enumerate(spec.get("steps", []), 1):
                step = dict(raw)
                action = next(iter(step))
                detail = step[action]
                s0 = time.time()
                entry = {"step": i, "action": action, "ok": True, "detail": None}
                try:
                    entry["detail"] = _do(page, action, detail, ns.out, data, shots)
                except PWTimeout as e:
                    entry["ok"] = False
                    entry["detail"] = f"timeout: {str(e)[:200]}"
                    try:
                        _shot(page, os.path.join(ns.out, "error.png"))
                    except Exception:
                        pass
                except Exception as e:  # noqa: BLE001 - record and continue
                    entry["ok"] = False
                    entry["detail"] = f"{type(e).__name__}: {str(e)[:200]}"
                entry["ms"] = round((time.time() - s0) * 1000)
                steps_out.append(entry)
                if not entry["ok"]:
                    error = f"step {i} ({action}) failed: {entry['detail']}"
                    break
        except Exception as e:  # noqa: BLE001 - top-level guard
            error = f"{type(e).__name__}: {e}"
            traceback.print_exc()
            try:
                _shot(page, os.path.join(ns.out, "error.png"))
            except Exception:
                pass
        finally:
            browser.close()

    results = {
        "name": spec.get("name", "job"),
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0, 1),
        "steps": steps_out,
        "data": data,
        "screenshots": shots,
        "error": error,
        "ok": error is None and bool(steps_out) and all(s["ok"] for s in steps_out),
    }
    with open(os.path.join(ns.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(json.dumps({"ok": results["ok"], "data": data, "screenshots": shots}, indent=2))
    return 0 if results["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
