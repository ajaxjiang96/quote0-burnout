#!/usr/bin/env python3
"""
quote0-burnout v0.7 — fetch usage, build snapshot, render dashboard, push to Quote/0.

Usage:
  python display.py                   # Image API (default)
  python display.py --preview         # Save preview PNG, skip push
  python display.py --text            # Text API fallback (v0.1 compat)
  python display.py --check           # Self-check, no push
  python display.py --debug-json      # Print snapshot JSON, no push
  python display.py --list-tasks      # List fixed + loop task slots
  python display.py --list-tasks fixed
  python display.py --list-tasks loop
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from render import render_image

# Provider implementations live in providers/; display.py stays the shell
# (CLI, push, cache, orchestration, second-panel resolution).
from providers import claude, codex, configured_providers, deepseek, opencode
from providers.core import (CURRENCY_SYMBOLS, coerce_percent as _coerce_percent,
                            env as _env, pct_status as _pct_status,
                            time_until as _time_until, window_label as _window_label)

# ── Config (lazy — never crashes on missing env) ──────────────────────────────

_HERE = Path(__file__).parent

QUOTE0_API_KEY     = _env("QUOTE0_API_KEY")
QUOTE0_DEVICE_ID   = _env("QUOTE0_DEVICE_ID")
DEEPSEEK_API_KEY   = deepseek.DEEPSEEK_API_KEY
DEEPSEEK_MODEL     = deepseek.DEEPSEEK_MODEL
CLAUDE_ACCESS_TOKEN = claude.CLAUDE_ACCESS_TOKEN
QUOTE0_REFRESH_NOW = _env("QUOTE0_REFRESH_NOW", "false").lower() == "true"

# Second panel: auto (prefer opencode-go, fall back to deepseek) | deepseek | opencode
SECOND_PANEL = _env("SECOND_PANEL", "auto").strip().lower()

# Layout: auto (fit to configured providers) | stack | 1+1 | 1+2 | 2+2
LAYOUT_ENV = _env("LAYOUT", "auto").strip().lower()


def _normalize_layout(raw: str) -> str:
    """Validate a layout string; unknown values warn and fall back to auto."""
    raw = (raw or "auto").strip().lower()
    if raw in ("auto", "stack", "1+1", "1+2", "2+2"):
        return raw
    print(f"warning: unknown layout '{raw}', using auto", file=sys.stderr)
    return "auto"

QUOTE0_IMAGE_TASK_KEY = _env("QUOTE0_IMAGE_TASK_KEY")
QUOTE0_TEXT_TASK_KEY  = _env("QUOTE0_TEXT_TASK_KEY")
QUOTE0_PREVIEW_PATH   = _env("QUOTE0_PREVIEW_PATH", "/tmp/quote0_burnout_preview.png")

# Last good snapshot — served when the Codex API is unreachable.
# Pattern ported from PR #2 by Scott Zheng (heishanmao/quote0-burnout).
SNAPSHOT_CACHE_PATH = _HERE / "tmp" / "last_snapshot.json"

API_BASE = "https://dot.mindreset.tech"

# ── Backward-compat re-exports (tests + external scripts import these) ────────

build_codex_snapshot = codex.build_snapshot
build_claude_snapshot = claude.build_snapshot
build_deepseek_snapshot = deepseek.build_snapshot
build_opencode_snapshot = opencode.build_snapshot
format_codex_text = codex.format_text
format_claude_text = claude.format_text
format_deepseek_text = deepseek.format_text
format_opencode_text = opencode.format_text
get_codex_usage = codex.get_usage
get_claude_usage = claude.get_usage
get_deepseek_balance = deepseek.get_balance
get_opencode_usage = opencode.get_usage
parse_claude_cli_usage = claude.parse_claude_cli_usage
_extract_claude_access_token = claude._extract_claude_access_token
DEEPSEEK_PRICING = deepseek.DEEPSEEK_PRICING
deepseek_window = deepseek.deepseek_window
_countdown = deepseek._countdown
_balance_status = deepseek._balance_status
normalize_codex = codex.normalize_codex

def _resolve_second_panel(deepseek_sn: dict, opencode_sn: dict) -> str:
    """Pick which provider renders as the second panel.

    SECOND_PANEL env: 'auto' (prefer opencode-go, fall back to deepseek),
    'deepseek' (deepseek only, opencode only if deepseek absent), 'opencode'
    (opencode only, deepseek only if opencode absent). Returns 'none' when
    neither source has data — the layout omits the panel entirely.
    """
    mode = SECOND_PANEL
    if mode == "deepseek":
        return "deepseek" if deepseek_sn.get("ok") else ("opencode" if opencode_sn.get("ok") else "none")
    if mode == "opencode":
        return "opencode" if opencode_sn.get("ok") else ("deepseek" if deepseek_sn.get("ok") else "none")
    # auto
    if opencode_sn.get("ok"):
        return "opencode"
    if deepseek_sn.get("ok"):
        return "deepseek"
    return "none"


# ── Snapshot builder (v0.4) ────────────────────────────────────────────────────

def build_snapshot(layout: str | None = None) -> dict:
    """Fetch and build full snapshot, falling back to cache on failure.

    On success the snapshot JSON is cached at SNAPSHOT_CACHE_PATH. If the
    Codex API is unreachable the last cached codex snapshot is served,
    marked `` (cached)`` in updated_at, with freshly-fetched claude/deepseek/
    opencode panels overlaid. Cache writes are best-effort.

    layout: None → LAYOUT env (default auto). The snapshot carries the
    resolved layout, the configured-provider list, and the global refresh
    time (updated_at) that the grid engine renders at the screen top-right.
    """
    layout = layout if layout is not None else _normalize_layout(LAYOUT_ENV)
    now = datetime.now().strftime("%H:%M")

    codex = get_codex_usage()
    claude = get_claude_usage()
    deepseek = get_deepseek_balance()
    opencode = get_opencode_usage()
    codex_sn = build_codex_snapshot(codex)
    claude_sn = build_claude_snapshot(claude)
    deepseek_sn = build_deepseek_snapshot(deepseek)
    opencode_sn = build_opencode_snapshot(opencode)
    snap = {
        "codex": codex_sn,
        "claude": claude_sn,
        "deepseek": deepseek_sn,
        "opencode": opencode_sn,
        "second_panel": _resolve_second_panel(deepseek_sn, opencode_sn),
        "layout": layout,
        # reserved for the #10 panel-order work — the grid engine
        # currently selects cells by live ok flags, not by this list.
        "configured": configured_providers(),
        "updated_at": now,
        "_cached": False,
    }
    if codex.get("ok"):
        try:
            SNAPSHOT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            SNAPSHOT_CACHE_PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        except OSError:
            pass  # caching is best-effort — never fail a refresh over it
        return snap

    # Codex fetch failed → serve the last good codex snapshot if we have one
    try:
        cached = json.loads(SNAPSHOT_CACHE_PATH.read_text(encoding="utf-8"))
        if cached.get("codex", {}).get("ok"):
            cached["updated_at"] = snap["updated_at"] + " (cached)"
            cached["_cached"] = True
            cached["claude"] = snap["claude"]  # refresh what is fresh
            cached["deepseek"] = snap["deepseek"]
            cached["opencode"] = snap["opencode"]
            cached["second_panel"] = snap["second_panel"]
            # Always refresh layout metadata from the live run: a stale
            # cached copy would otherwise fight an changed --layout/LAYOUT
            # override or provider-credentials change until Codex recovers.
            # (Assignment also recreates keys missing from pre-upgrade caches.)
            cached["layout"] = snap["layout"]
            cached["configured"] = snap["configured"]
            return cached
    except (OSError, ValueError):
        pass
    return snap


def _second_panel_line(snapshot: dict) -> str | None:
    """One-line summary of the active second panel for --preview output."""
    second = snapshot.get("second_panel")
    if second == "opencode":
        oc = snapshot.get("opencode", {})
        if oc.get("ok"):
            r = oc.get("rolling", {})
            used_s = f"{r['used_percent']}%" if r.get("used_percent") is not None else "?"
            wk = oc.get("weekly", {})
            wk_s = f" Wk {wk['used_percent']}%" if wk.get("used_percent") is not None else ""
            return f"OpenCode:  {used_s} [{oc['status']}] reset {r.get('reset', '?')}{wk_s}"
        return f"OpenCode:  {oc.get('raw_status', 'error')}"
    if second == "deepseek":
        ds = snapshot.get("deepseek", {})
        if ds.get("ok"):
            win = ds.get("window", "?")
            return (
                f"DeepSeek:  {ds['symbol']}{ds['balance']:.2f} [{ds['status']}] {win} "
                f"in {ds['symbol']}{ds['price_in']:.2f} out {ds['symbol']}{ds['price_out']:.2f} "
                f"{ds.get('next_window', '?')} in {ds.get('countdown', '?')}"
            )
        return f"DeepSeek:  {ds.get('raw_status', 'error')}"
    return None  # no second panel


def _second_panel_text(snapshot: dict) -> str:
    """Active second panel's text-formatted string for Text API."""
    second = snapshot.get("second_panel")
    if second == "opencode":
        return format_opencode_text(snapshot.get("opencode", {}))
    if second == "deepseek":
        return format_deepseek_text(snapshot.get("deepseek", {}))
    return ""


# ── Push ──────────────────────────────────────────────────────────────────────

def push_image(png_bytes: bytes) -> dict:
    url = f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/image"
    payload = {
        "refreshNow": QUOTE0_REFRESH_NOW,
        "image": base64.b64encode(png_bytes).decode(),
        "ditherType": "DIFFUSION",
        "ditherKernel": "FLOYD_STEINBERG",
        "border": 0,
    }
    if QUOTE0_IMAGE_TASK_KEY:
        payload["taskKey"] = QUOTE0_IMAGE_TASK_KEY
    r = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {QUOTE0_API_KEY}"},
        timeout=20,
    )
    if not r.ok:
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text}
        return {"ok": False, "status": r.status_code, "body": body}
    return {"ok": True, "body": r.json()}


def push_text(payload: dict) -> dict:
    url = f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/text"
    body = {"refreshNow": QUOTE0_REFRESH_NOW, **payload}
    if QUOTE0_TEXT_TASK_KEY:
        body["taskKey"] = QUOTE0_TEXT_TASK_KEY
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {QUOTE0_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=20,
    )
    if not r.ok:
        try:
            body_resp = r.json()
        except Exception:
            body_resp = {"_raw": r.text}
        return {"ok": False, "status": r.status_code, "body": body_resp}
    return {"ok": True, "body": r.json()}


# ── Run (push) ────────────────────────────────────────────────────────────────

def run(preview: bool = False, text_mode: bool = False, layout: str | None = None):
    snapshot = build_snapshot(layout=layout)
    print(f"layout: {snapshot.get('layout', 'stack')}")

    if text_mode:
        cx_text = format_codex_text(snapshot["codex"])
        cl_text = format_claude_text(snapshot["claude"])
        second_text = _second_panel_text(snapshot)
        print(f"Codex:     {cx_text.replace(chr(10), ' / ')}")
        print(f"Claude:    {cl_text.replace(chr(10), ' / ')}")
        if second_text:
            tag = "OpenCode" if snapshot.get("second_panel") == "opencode" else "DeepSeek"
            print(f"{tag}:  {second_text.replace(chr(10), ' / ')}")

        now = snapshot["updated_at"]
        message = f"Codex {cx_text}\nClaude {cl_text}"
        if second_text:
            message += f"\n{snapshot.get('second_panel', 'deepseek').capitalize()} {second_text}"
        payload = {
            "message": message,
            "signature": now,
        }
        result = push_text(payload)
    else:
        # v0.4 uses snapshot dict; render.py handles both
        png = render_image(snapshot)

        if preview is True:
            Path(QUOTE0_PREVIEW_PATH).write_bytes(png)
            print(f"Preview saved to {QUOTE0_PREVIEW_PATH}")
            print("--preview only, skipping push")
            # Also print a summary for preview
            cx = snapshot["codex"]
            cl = snapshot["claude"]
            if cx["ok"]:
                print(f"Codex:     {cx['short_label']} {cx['short_used_percent']}% reset {cx['short_reset']} [{cx['status']}]")
                if cx["long_used_percent"] is not None:
                    print(f"          {cx['long_label']} {cx['long_used_percent']}%")
            else:
                print(f"Codex:     {cx['raw_status']}")
            if cl["ok"]:
                print(f"Claude:    {cl['short_label']} {cl['short_used_percent']}% reset {cl['short_reset']} [{cl['status']}]")
                if cl["long_used_percent"] is not None:
                    print(f"          {cl['long_label']} {cl['long_used_percent']}%")
            else:
                print(f"Claude:    {cl['raw_status']}")
            second_line = _second_panel_line(snapshot)
            if second_line:
                print(second_line)
            return True

        result = push_image(png)

    output = {
        "ok": result.get("ok"),
        "status": result.get("status"),
    }
    body = result.get("body", {})
    if isinstance(body, dict):
        output["message"] = body.get("message", "")
    else:
        output["message"] = str(body)

    print(json.dumps(output, ensure_ascii=False, indent=2))

    if not result.get("ok"):
        msg = output.get("message", "unknown error")
        print(f"\n⚠️  Push failed (HTTP {result.get('status')}): {msg}", file=sys.stderr)
        return False

    return True


# ── Check ─────────────────────────────────────────────────────────────────────

def _status(label: str, ok: bool, detail: str = "") -> str:
    tag = "OK" if ok else "FAIL"
    suffix = f" {detail}" if detail else ""
    return f"  {label:<24} {tag}{suffix}"


def check() -> int:
    """Run self-check. Returns exit code (0=OK, 1=problems)."""
    print("quote0-burnout check\n")

    warnings = 0
    failures = 0

    # ── Environment ────────────────────────────────────────────────────────
    print("Environment:")

    env_vars = [
        ("QUOTE0_API_KEY",        QUOTE0_API_KEY,        True),
        ("QUOTE0_DEVICE_ID",      QUOTE0_DEVICE_ID,      True),
        ("QUOTE0_IMAGE_TASK_KEY", QUOTE0_IMAGE_TASK_KEY, False),
        ("QUOTE0_TEXT_TASK_KEY",  QUOTE0_TEXT_TASK_KEY,  False),
        ("CLAUDE_ACCESS_TOKEN",   CLAUDE_ACCESS_TOKEN,   False),
    ]

    for name, val, required in env_vars:
        if val:
            masked = val[:3] + "..." if len(val) > 6 else val
            print(_status(name, True, masked))
        elif required:
            print(_status(name, False, "missing"))
            failures += 1
        else:
            print(_status(name, True, "optional / missing"))

    print()

    # ── Codex (direct API) ──────────────────────────────────────────────────
    print("Codex:")
    auth_ok = False
    try:
        token, acct = _load_codex_token()
        if token:
            acct_str = f" (acct {acct[:8]}...)" if acct else ""
            print(_status("auth", True, f"token loaded{acct_str}"))
            auth_ok = True
        else:
            print(_status("auth", False, "empty token"))
    except FileNotFoundError as e:
        print(_status("auth", False, str(e)))
    except Exception as e:
        print(_status("auth", False, str(e)))

    codex_ok = False
    if auth_ok:
        codex = get_codex_usage()
        sn_codex = build_codex_snapshot(codex)
        if sn_codex["ok"]:
            pct = sn_codex["short_used_percent"]
            pct_str = f"{pct}%" if pct is not None else "?"
            detail = f"{sn_codex['short_label']} {pct_str} [{sn_codex['status']}]"
            print(_status("usage", True, detail))
            codex_ok = True
        else:
            print(_status("usage", False, sn_codex["raw_status"]))
    else:
        print(_status("usage", False, "no auth"))

    print()

    # ── Claude (OAuth API, with Claude CLI fallback) ───────────────────────
    print("Claude:")
    claude_ok = False
    claude = get_claude_usage()
    source = claude.get("source", "")
    if claude.get("ok"):
        if source == "oauth":
            print(_status("auth", True, "OAuth token loaded"))
        elif source == "cli":
            print(_status("auth", True, f"{CLAUDE_CLI} /usage"))
        else:
            print(_status("auth", True, "usage source available"))
    else:
        detail = claude.get("detail") or claude.get("status", "error")
        print(_status("auth", False, detail[:160]))

    sn_claude = build_claude_snapshot(claude)
    if sn_claude["ok"]:
        pct = sn_claude["short_used_percent"]
        pct_str = f"{pct}%" if pct is not None else "?"
        source_str = f" via {source}" if source else ""
        detail = f"{sn_claude['short_label']} {pct_str} [{sn_claude['status']}]{source_str}"
        print(_status("usage", True, detail))
        claude_ok = True
    else:
        print(_status("usage", False, sn_claude["raw_status"]))

    print()

    # ── Render ─────────────────────────────────────────────────────────────
    print("Render:")
    render_ok = False
    if codex_ok or claude_ok:
        try:
            snapshot = {
                "codex": build_codex_snapshot(get_codex_usage() if codex_ok else {"ok": False, "status": "n/a"}),
                "claude": build_claude_snapshot(get_claude_usage() if claude_ok else {"ok": False, "status": "n/a"}),
                "updated_at": datetime.now().strftime("%H:%M"),
            }
            png = render_image(snapshot)
            Path(QUOTE0_PREVIEW_PATH).write_bytes(png)
            print(_status("image", True, QUOTE0_PREVIEW_PATH))
            render_ok = True
        except Exception as e:
            print(_status("image", False, str(e)))
            failures += 1
    else:
        print(_status("image", False, "no data to render"))

    print()

    # ── Quote/0 ────────────────────────────────────────────────────────────
    print("Quote/0:")
    if QUOTE0_API_KEY and QUOTE0_DEVICE_ID:
        try:
            r = requests.get(
                f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/fixed/list",
                headers={"Authorization": f"Bearer {QUOTE0_API_KEY}"},
                timeout=10,
            )
            if r.ok:
                print(_status("endpoint", True, f"HTTP {r.status_code}"))
            else:
                print(_status("endpoint", False, f"HTTP {r.status_code}"))
        except Exception as e:
            print(_status("endpoint", False, str(e)))
            failures += 1

        refresh_label = "true" if QUOTE0_REFRESH_NOW else "false"
        print(_status("refreshNow", True, refresh_label))
    else:
        print(_status("endpoint", False, "QUOTE0_API_KEY or QUOTE0_DEVICE_ID missing"))
        failures += 1

    print()

    # ── Result ─────────────────────────────────────────────────────────────
    print("Result:")

    if not codex_ok:
        warnings += 1
    if not claude_ok:
        warnings += 1

    if failures == 0 and warnings == 0:
        print("  OK")
        return 0
    elif failures == 0 and warnings > 0:
        print(f"  WARNING ({warnings} non-critical issue(s))")
        if not codex_ok and not claude_ok:
            return 1
        return 0
    else:
        print(f"  FAIL ({failures} error(s), {warnings} warning(s))")
        return 1


# ── List tasks ────────────────────────────────────────────────────────────────

def list_tasks(task_type: str = "") -> int:
    """List Quote/0 task slots. task_type: '', 'fixed', 'loop'."""

    if not QUOTE0_API_KEY or not QUOTE0_DEVICE_ID:
        print("Error: QUOTE0_API_KEY and QUOTE0_DEVICE_ID are required", file=sys.stderr)
        return 1

    types = [task_type] if task_type else ["fixed", "loop"]

    for tt in types:
        try:
            r = requests.get(
                f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/{tt}/list",
                headers={"Authorization": f"Bearer {QUOTE0_API_KEY}"},
                timeout=10,
            )
            if not r.ok:
                print(f"{tt}:  HTTP {r.status_code}", file=sys.stderr)
                try:
                    body = r.json()
                    print(json.dumps(body, ensure_ascii=False, indent=2), file=sys.stderr)
                except Exception:
                    print(r.text, file=sys.stderr)
                continue

            data = r.json()
            if not isinstance(data, list):
                print(f"{tt}:  unexpected response (not a list):")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                continue

            print(f"{tt}:")
            if not data:
                print("  (empty)")
                continue

            for task in data:
                if not isinstance(task, dict):
                    print(f"  {task}")
                    continue
                t = task.get("type", "?")
                k = task.get("key", "?")
                title = task.get("title", task.get("name", ""))
                line = f"  {t:<12} {k}"
                if title:
                    line += f"  {title}"
                print(line)

        except Exception as e:
            print(f"{tt}:  error — {e}", file=sys.stderr)

        if task_type:
            continue
        if tt == "fixed" and "loop" in types:
            print()

    return 0


# ── Debug JSON ────────────────────────────────────────────────────────────────

def debug_json(layout: str | None = None):
    """Print snapshot as JSON, no push."""
    snapshot = build_snapshot(layout=layout)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Push AI usage to Quote/0 display"
    )
    parser.add_argument(
        "--preview", action="store_true",
        help=f"Save preview PNG to {QUOTE0_PREVIEW_PATH} and skip push"
    )
    parser.add_argument(
        "--text", action="store_true",
        help="Use Text API instead of Image API (v0.1 compat)"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Run self-check — tests env, deps, data, render, endpoints (no push)"
    )
    parser.add_argument(
        "--debug-json", action="store_true",
        help="Print snapshot JSON — fetch + normalize, no push, no render"
    )
    parser.add_argument(
        "--list-tasks", nargs="?", const="", metavar="TYPE",
        help="List task slots: no arg = fixed+loop, 'fixed', 'loop'"
    )
    parser.add_argument(
        "--layout", default=None,
        choices=["auto", "stack", "1+1", "1+2", "2+2"],
        help="Panel layout: auto (default — fit to configured providers) | stack | 1+1 | 1+2 | 2+2. Overrides LAYOUT env."
    )
    args = parser.parse_args()

    # ── --check ────────────────────────────────────────────────────────────
    if args.check:
        rc = check()
        sys.exit(rc)

    # ── --list-tasks ───────────────────────────────────────────────────────
    if args.list_tasks is not None:
        rc = list_tasks(args.list_tasks)
        sys.exit(rc)

    # ── --debug-json ───────────────────────────────────────────────────────
    if args.debug_json:
        ok = debug_json(layout=args.layout)
        sys.exit(0 if ok else 1)

    # ── default / --preview / --text ───────────────────────────────────────
    success = run(preview=args.preview, text_mode=args.text, layout=args.layout)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
