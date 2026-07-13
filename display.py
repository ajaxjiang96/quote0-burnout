#!/usr/bin/env python3
"""
quote0-burnout v0.7 — fetch usage, build snapshot, push to Quote/0.

Modes:
  Image API (default): render PNG locally → push via Image API
  Canvas API (--canvas): build windowData JSON → push via Canvas API (server-rendered)
  Text API  (--text):   plain text card

Usage:
  python display.py                     # Image API (default)
  python display.py --canvas            # Canvas API (server-rendered dashboard)
  python display.py --canvas --preview  # Save Canvas JSON preview, skip push
  python display.py --preview           # Save PNG preview, skip push
  python display.py --text              # Text API fallback (v0.1 compat)
  python display.py --check             # Self-check, no push
  python display.py --debug-json        # Print snapshot JSON, no push
  python display.py --list-tasks        # List fixed + loop task slots
  python display.py --list-tasks fixed
  python display.py --list-tasks loop
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from render import render_image

# ── Config (lazy — never crashes on missing env) ──────────────────────────────

_HERE = Path(__file__).parent

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

QUOTE0_API_KEY     = _env("QUOTE0_API_KEY")
QUOTE0_DEVICE_ID   = _env("QUOTE0_DEVICE_ID")
DEEPSEEK_API_KEY   = _env("DEEPSEEK_API_KEY")
QUOTE0_REFRESH_NOW = _env("QUOTE0_REFRESH_NOW", "false").lower() == "true"

QUOTE0_IMAGE_TASK_KEY  = _env("QUOTE0_IMAGE_TASK_KEY")
QUOTE0_TEXT_TASK_KEY   = _env("QUOTE0_TEXT_TASK_KEY")
QUOTE0_CANVAS_TASK_KEY = _env("QUOTE0_CANVAS_TASK_KEY")
QUOTE0_PREVIEW_PATH    = _env("QUOTE0_PREVIEW_PATH", "/tmp/quote0_burnout_preview.png")

API_BASE = "https://dot.mindreset.tech"

# ── Status helpers ────────────────────────────────────────────────────────────

def _pct_status(pct: int | None) -> str:
    """Codex used-percent → ok / warn / hot / unknown."""
    if pct is None:
        return "unknown"
    if pct >= 90:
        return "hot"
    if pct >= 70:
        return "warn"
    return "ok"


def _balance_status(balance: float | None, is_available: bool | None) -> str:
    """DeepSeek balance → ok / warn / hot / unknown / error."""
    if balance is None:
        return "unknown"
    if is_available is False:
        return "hot"
    if balance < 3:
        return "hot"
    if balance < 10:
        return "warn"
    return "ok"


def _window_label(minutes: int | None) -> str:
    """windowMinutes → human label."""
    if minutes is None:
        return "Now"
    if minutes <= 360:
        return "5h"
    if minutes <= 1440:
        return "Day"
    if minutes >= 10080:
        return "Week"
    return "Now"


# ── Fetch ─────────────────────────────────────────────────────────────────────

CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


def _load_codex_token():
    """Return (access_token, account_id). Env var takes priority over auth.json."""
    env_token = os.environ.get("CODEX_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token, os.environ.get("CODEX_ACCOUNT_ID", "").strip()

    if not CODEX_AUTH_PATH.exists():
        raise FileNotFoundError(
            f"No Codex credentials at {CODEX_AUTH_PATH}. "
            "Run `codex` to authenticate first, or set CODEX_ACCESS_TOKEN in .env."
        )
    with open(CODEX_AUTH_PATH) as f:
        auth = json.load(f)
    tokens = auth.get("tokens", {})
    return tokens.get("access_token", ""), tokens.get("account_id", "")


def get_codex_usage():
    """Fetch OpenAI Codex usage via direct API (no codexbar dependency)."""
    try:
        access_token, account_id = _load_codex_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "quote0-burnout",
        }
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        r = requests.get(CODEX_USAGE_URL, headers=headers, timeout=15)
        r.raise_for_status()
        return {"ok": True, "raw": r.json()}

    except FileNotFoundError as e:
        return {"ok": False, "status": "no auth", "detail": str(e)}
    except requests.Timeout:
        return {"ok": False, "status": "timeout"}
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.text[:200]
        except Exception:
            pass
        return {"ok": False, "status": f"HTTP {e.response.status_code}", "detail": detail}
    except Exception as e:
        return {"ok": False, "status": "error", "detail": str(e)[:200]}


def get_deepseek_balance():
    if not DEEPSEEK_API_KEY:
        return {"ok": False, "status": "no key"}

    try:
        r = requests.get(
            "https://api.deepseek.com/user/balance",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Accept": "application/json",
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()

        infos = data.get("balance_infos", [])
        usd = next(
            (x for x in infos if x.get("currency") == "USD"),
            infos[0] if infos else None,
        )

        if not usd:
            return {"ok": False, "status": "no balance"}

        return {
            "ok": True,
            "amount": usd.get("total_balance"),
            "currency": usd.get("currency", "USD"),
            "available": data.get("is_available"),
            "raw": data,
        }

    except Exception:
        return {"ok": False, "status": "error"}


# ── Snapshot builder (v0.4) ────────────────────────────────────────────────────

CURRENCY_SYMBOLS = {"USD": "$", "CNY": "¥", "EUR": "€", "GBP": "£"}


def build_codex_snapshot(codex: dict) -> dict:
    """Build structured codex snapshot from wham API response."""
    if not codex.get("ok"):
        status = codex.get("status", "error")
        return {
            "ok": False,
            "short_label": "?",
            "short_used_percent": None,
            "short_reset": "?",
            "long_label": "?",
            "long_used_percent": None,
            "status": "error",
            "raw_status": status,
        }

    raw = codex.get("raw", {})
    rate_limit = raw.get("rate_limit") or {}

    primary = rate_limit.get("primary_window") or {}
    secondary = rate_limit.get("secondary_window") or {}

    short_pct = primary.get("used_percent")
    short_reset_ts = primary.get("reset_at")

    long_pct = secondary.get("used_percent")
    long_reset_ts = secondary.get("reset_at")

    # percent is float from API; normalize to int
    try:
        short_pct = int(float(short_pct)) if short_pct is not None else None
    except (ValueError, TypeError):
        short_pct = None
    try:
        long_pct = int(float(long_pct)) if long_pct is not None else None
    except (ValueError, TypeError):
        long_pct = None

    has_secondary = long_pct is not None
    short_label = "5h"  # default

    # Label: derive from window seconds if secondary is missing
    if not has_secondary:
        secs = primary.get("limit_window_seconds")
        if secs and secs >= 86400:
            short_label = "Week"
        elif secs and secs >= 3600:
            hours = secs // 3600
            short_label = f"{hours}h"
        else:
            short_label = "Now"

    return {
        "ok": True,
        "short_label": short_label,
        "short_used_percent": short_pct,
        "short_reset": _time_until(short_reset_ts) if short_reset_ts else "?",
        "long_label": "Week" if has_secondary else None,
        "long_used_percent": long_pct if has_secondary else None,
        "long_reset": _time_until(long_reset_ts) if long_reset_ts and has_secondary else None,
        "status": _pct_status(short_pct if short_pct is not None else long_pct),
        "raw_status": "",
    }


def build_deepseek_snapshot(ds: dict) -> dict:
    """Build structured deepseek snapshot from balance API response."""
    if not ds.get("ok"):
        status = ds.get("status", "error")
        return {
            "ok": False,
            "balance": None,
            "currency": "?",
            "symbol": "?",
            "status": "error",
            "raw_status": status,
        }

    amount = ds.get("amount")
    try:
        amount = float(amount) if amount is not None else None
    except (ValueError, TypeError):
        amount = None

    currency = ds.get("currency", "USD")
    available = ds.get("available")

    return {
        "ok": True,
        "balance": amount,
        "currency": currency,
        "symbol": CURRENCY_SYMBOLS.get(currency, "$"),
        "status": _balance_status(amount, available),
        "raw_status": "",
    }


def build_snapshot() -> dict:
    """Fetch and build full snapshot."""
    codex = get_codex_usage()
    deepseek = get_deepseek_balance()
    return {
        "codex": build_codex_snapshot(codex),
        "deepseek": build_deepseek_snapshot(deepseek),
        "updated_at": datetime.now().strftime("%H:%M"),
    }


# ── Legacy normalize (v0.2–v0.3 compat) ───────────────────────────────────────

def _time_until(val) -> str:
    """Human-readable countdown from ISO string or unix timestamp (int/float).
    Hours are always zero-padded: 6d04h, 2h45m."""
    if val is None:
        return "?"
    try:
        if isinstance(val, (int, float)):
            dt = datetime.fromtimestamp(val, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except Exception:
        return "?"
    delta = dt - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "now"
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h >= 24:
        d = h // 24
        h = h % 24
        return f"{d}d{h:02d}h" if h > 0 else f"{d}d"
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def normalize_codex(codex):
    """Legacy string formatter (v0.2–v0.3)."""
    if not codex.get("ok"):
        return codex.get("status", "unknown")

    raw = codex.get("raw", {})
    rate_limit = raw.get("rate_limit", {})

    primary = rate_limit.get("primary_window", {})
    pct = primary.get("used_percent")
    resets = primary.get("reset_at")

    secondary = rate_limit.get("secondary_window", {})
    sec_pct = secondary.get("used_percent")

    if pct is None:
        return "OK"

    parts = [f"{float(pct):.0f}%"]
    if resets:
        parts.append(_time_until(resets))
    if sec_pct is not None:
        parts.append(f"Wk {float(sec_pct):.0f}%")

    return " · ".join(parts)


def normalize_deepseek(ds):
    """Legacy string formatter (v0.2–v0.3)."""
    if not ds.get("ok"):
        return ds.get("status", "unknown")

    amount = ds.get("amount")
    if amount is None:
        return "unknown"

    symbol = CURRENCY_SYMBOLS.get(ds.get("currency", ""), "$")

    try:
        return f"{symbol}{float(amount):.2f}"
    except Exception:
        return str(amount)


def format_codex_text(sn: dict) -> str:
    """Format codex snapshot for Text API."""
    if not sn.get("ok"):
        return sn.get("raw_status", "error")

    pct = sn.get("short_used_percent")
    pct_str = f"{pct}%" if pct is not None else "?"
    reset = sn.get("short_reset", "?")

    line = f"{sn['short_label']} {pct_str} reset {reset}"

    long_pct = sn.get("long_used_percent")
    if long_pct is not None:
        line += f"\n{sn['long_label']} {long_pct}%"

    return line


def format_deepseek_text(sn: dict) -> str:
    """Format deepseek snapshot for Text API."""
    if not sn.get("ok"):
        return sn.get("raw_status", "error")

    bal = sn.get("balance")
    if bal is None:
        return "unknown"

    return f"{sn['symbol']}{bal:.2f} {sn['status'].upper()}"


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


# ── Canvas API (v0.7) ──────────────────────────────────────────────────────────

# Base64 logo — Codex only (Canvas API has a 1-img limit per screen)
CODEX_LOGO_DATA_URI = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQAQAAAAA3iMLMAAAAO0lEQVR4nAEwAM//"
    "Af8ABPmHAvsIAecMAugIAtAAAhwAAv4CAgAAANsdAd+6AN/zBPAIAhLoAP4fAf8AeAkP3QHlRD8AAAAASUVORK5CYII="
)

# Font classes (Dot. chillduansans — cleaner than pixel fonts on e-ink)
FONT_SMALL  = "text-10-chillduansans"   # timestamp
FONT_LABEL  = "text-14-chillduansans"   # section labels, bar text
FONT_BOLD   = "text-14-chillduansans font-bold"  # section headers
FONT_BALANCE = "text-22-chillduansans"  # deepseek balance

BAR_H = 14  # bar height in px


def _bar_element(remaining_pct: float) -> dict:
    """Build a Canvas bar: bordered outline + two flex children (filled/empty)."""
    if remaining_pct is None:
        remaining_pct = 0
    remaining_pct = max(0, min(100, remaining_pct))
    return {
        "type": "div",
        "props": {
            "tw": "flex flex-row flex-1",
            "style": {
                "height": f"{BAR_H}px",
                "border": "1px solid black",
            },
            "children": [
                {
                    "type": "div",
                    "props": {
                        "tw": "bg-black",
                        "style": {
                            "width": f"{remaining_pct:.0f}%",
                            "height": "100%",
                        },
                    },
                },
                {
                    "type": "div",
                    "props": {
                        "style": {
                            "width": f"{100 - remaining_pct:.0f}%",
                            "height": "100%",
                        },
                    },
                },
            ],
        },
    }


def build_canvas_payload(snapshot: dict) -> dict:
    """Build Canvas API request payload from a snapshot dict.

    Translates the PIL-rendered dashboard (render.py _render_v5) into
    Canvas API windowData: div/span/img elements with Dot. Tailwind styling.

    NOTE: Canvas API has a 1-img limit per screen. Only the Codex logo
    uses an img element; DEEPSEEK section uses text-only header.
    """
    cx = snapshot.get("codex", {})
    ds = snapshot.get("deepseek", {})
    ts = snapshot.get("updated_at", datetime.now().strftime("%H:%M"))

    children = []

    # ── CODEX header: logo + "CODEX" (left) ... timestamp (right) ─────
    children.append({
        "type": "div",
        "props": {
            "tw": "flex flex-row items-center justify-between",
            "children": [
                {
                    "type": "div",
                    "props": {
                        "tw": "flex flex-row items-center gap-[4px]",
                        "children": [
                            {
                                "type": "img",
                                "props": {
                                    "src": CODEX_LOGO_DATA_URI,
                                    "style": {"width": "16px", "height": "16px"},
                                },
                            },
                            {
                                "type": "span",
                                "props": {
                                    "tw": FONT_BOLD,
                                    "children": "CODEX",
                                },
                            },
                        ],
                    },
                },
                {
                    "type": "span",
                    "props": {
                        "tw": f"{FONT_SMALL} min-w-[38px]",
                        "style": {"textAlign": "right"},
                        "children": ts,
                    },
                },
            ],
        },
    })

    if cx.get("ok"):
        short_label = cx.get("short_label", "5h")
        short_used = cx.get("short_used_percent") or 0
        short_reset = cx.get("short_reset", "?")
        long_label = cx.get("long_label", "Week")
        long_used = cx.get("long_used_percent") or 0
        long_reset = cx.get("long_reset", "?")

        def _fmt_note(used, reset):
            r = 100 - int(used) if used else 0
            return f"{r:.0f}%  {reset}" if reset and reset != "?" else f"{r:.0f}%"

        # Row 1: label + bar + note
        children.append({
            "type": "div",
            "props": {
                "tw": "flex flex-row items-center gap-[4px]",
                "children": [
                    {
                        "type": "span",
                        "props": {
                            "tw": f"{FONT_LABEL} shrink-0 w-[40px]",
                            "children": short_label,
                        },
                    },
                    _bar_element(100 - short_used),
                    {
                        "type": "span",
                        "props": {
                            "tw": f"{FONT_LABEL} shrink-0 min-w-[80px]",
                            "style": {"textAlign": "right", "whiteSpace": "nowrap"},
                            "children": _fmt_note(short_used, short_reset),
                        },
                    },
                ],
            },
        })

        # Row 2: label + bar + note (skip if no secondary window)
        if long_used is not None and long_label:
            children.append({
                "type": "div",
                "props": {
                    "tw": "flex flex-row items-center gap-[4px]",
                    "children": [
                        {
                            "type": "span",
                            "props": {
                                "tw": f"{FONT_LABEL} shrink-0 w-[40px]",
                                "children": long_label,
                            },
                        },
                        _bar_element(100 - long_used),
                        {
                            "type": "span",
                            "props": {
                                "tw": f"{FONT_LABEL} shrink-0 min-w-[80px]",
                                "style": {"textAlign": "right", "whiteSpace": "nowrap"},
                                "children": _fmt_note(long_used, long_reset),
                            },
                        },
                    ],
                },
            })
    else:
        status = cx.get("raw_status", "error")
        children.append({
            "type": "div",
            "props": {
                "tw": "flex flex-row",
                "children": {
                    "type": "span",
                    "props": {
                        "tw": FONT_LABEL,
                        "children": status,
                    },
                },
            },
        })

    # ── Divider ────────────────────────────────────────────────────────
    children.append({
        "type": "div",
        "props": {
            "style": {
                "height": "1px",
                "backgroundColor": "black",
            },
        },
    })

    # ── DEEPSEEK section (text-only — 1-img Canvas limit) ──────────────
    children.append({
        "type": "div",
        "props": {
            "tw": "flex flex-row",
            "children": {
                "type": "span",
                "props": {
                    "tw": FONT_BOLD,
                    "children": "DEEPSEEK",
                },
            },
        },
    })

    if ds.get("ok"):
        bal = ds.get("balance")
        sym = ds.get("symbol", "$")
        bal_text = f"{sym}{bal:.2f}" if bal is not None else "?"
        status = ds.get("status", "ok").upper()

        children.append({
            "type": "div",
            "props": {
                "tw": "flex flex-row items-end justify-between",
                "children": [
                    {
                        "type": "span",
                        "props": {
                            "tw": FONT_BALANCE,
                            "children": bal_text,
                        },
                    },
                    {
                        "type": "span",
                        "props": {
                            "tw": FONT_LABEL,
                            "children": status,
                        },
                    },
                ],
            },
        })
    else:
        status = ds.get("raw_status", "error")
        children.append({
            "type": "div",
            "props": {
                "tw": "flex flex-row",
                "children": {
                    "type": "span",
                    "props": {
                        "tw": FONT_LABEL,
                        "children": status,
                    },
                },
            },
        })

    # ── Assemble ────────────────────────────────────────────────────────
    window_data = {
        "default": [
            {
                "type": "div",
                "props": {
                    "tw": "flex flex-col w-full h-full bg-white text-black gap-[2px] p-[12px]",
                    "children": children,
                },
            }
        ]
    }

    payload: dict = {
        "refreshNow": QUOTE0_REFRESH_NOW,
        "windowData": window_data,
        "border": 0,
    }

    if QUOTE0_CANVAS_TASK_KEY:
        payload["taskKey"] = QUOTE0_CANVAS_TASK_KEY

    return payload


def push_canvas(payload: dict) -> dict:
    """Push canvas payload to Quote/0 device via Canvas API."""
    url = f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/canvas"
    r = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {QUOTE0_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=20,
    )
    if not r.ok:
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text}
        return {"ok": False, "status": r.status_code, "body": body}
    return {"ok": True, "body": r.json()}


# ── Run (push) ────────────────────────────────────────────────────────────────

def run(preview: bool = False, text_mode: bool = False, canvas_mode: bool = False):
    snapshot = build_snapshot()

    if canvas_mode:
        payload = build_canvas_payload(snapshot)

        if preview is True:
            preview_path = Path(QUOTE0_PREVIEW_PATH).with_suffix(".canvas.json")
            preview_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            print(f"Canvas payload saved to {preview_path}")
            print("--preview only, skipping push")
            # Print summary
            cx = snapshot["codex"]
            ds = snapshot["deepseek"]
            if cx["ok"]:
                print(f"Codex:     {cx['short_label']} {cx['short_used_percent']}% reset {cx['short_reset']} [{cx['status']}]")
                if cx["long_used_percent"] is not None:
                    print(f"          {cx['long_label']} {cx['long_used_percent']}%")
            else:
                print(f"Codex:     {cx['raw_status']}")
            if ds["ok"]:
                print(f"DeepSeek:  {ds['symbol']}{ds['balance']:.2f} [{ds['status']}]")
            else:
                print(f"DeepSeek:  {ds['raw_status']}")
            return True

        result = push_canvas(payload)
    elif text_mode:
        cx_text = format_codex_text(snapshot["codex"])
        ds_text = format_deepseek_text(snapshot["deepseek"])
        print(f"Codex:     {cx_text.replace(chr(10), ' / ')}")
        print(f"DeepSeek:  {ds_text}")

        now = snapshot["updated_at"]
        payload = {
            "message": f"Codex {cx_text}\nDeepSeek {ds_text}",
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
            ds = snapshot["deepseek"]
            if cx["ok"]:
                print(f"Codex:     {cx['short_label']} {cx['short_used_percent']}% reset {cx['short_reset']} [{cx['status']}]")
                if cx["long_used_percent"] is not None:
                    print(f"          {cx['long_label']} {cx['long_used_percent']}%")
            else:
                print(f"Codex:     {cx['raw_status']}")
            if ds["ok"]:
                print(f"DeepSeek:  {ds['symbol']}{ds['balance']:.2f} [{ds['status']}]")
            else:
                print(f"DeepSeek:  {ds['raw_status']}")
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
        ("DEEPSEEK_API_KEY",      DEEPSEEK_API_KEY,      False),
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

    # ── DeepSeek ───────────────────────────────────────────────────────────
    print("DeepSeek:")
    ds_ok = False
    if DEEPSEEK_API_KEY:
        ds = get_deepseek_balance()
        sn_ds = build_deepseek_snapshot(ds)
        if sn_ds["ok"]:
            bal = sn_ds["balance"]
            bal_str = f"{sn_ds['symbol']}{bal:.2f}" if bal is not None else "?"
            detail = f"{bal_str} [{sn_ds['status']}]"
            print(_status("balance", True, detail))
            ds_ok = True
        else:
            print(_status("balance", False, sn_ds["raw_status"]))
    else:
        print(_status("balance", False, "no API key"))

    print()

    # ── Render ─────────────────────────────────────────────────────────────
    print("Render:")
    render_ok = False
    if codex_ok or ds_ok:
        try:
            snapshot = {
                "codex": build_codex_snapshot(get_codex_usage() if codex_ok else {"ok": False, "status": "n/a"}),
                "deepseek": build_deepseek_snapshot(get_deepseek_balance() if ds_ok else {"ok": False, "status": "n/a"}),
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
    if not ds_ok:
        warnings += 1

    if failures == 0 and warnings == 0:
        print("  OK")
        return 0
    elif failures == 0 and warnings > 0:
        print(f"  WARNING ({warnings} non-critical issue(s))")
        if not codex_ok and not ds_ok:
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

def debug_json():
    """Print snapshot as JSON, no push."""
    snapshot = build_snapshot()
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
        "--canvas", action="store_true",
        help="Use Canvas API instead of Image API (server-side rendering)"
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
        ok = debug_json()
        sys.exit(0 if ok else 1)

    # ── default / --preview / --text / --canvas ────────────────────────────────
    success = run(preview=args.preview, text_mode=args.text, canvas_mode=args.canvas)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
