#!/usr/bin/env python3
"""
quote0-burnout v0.5 — fetch usage, build snapshot, render dashboard, push to Quote/0.

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
import subprocess
import sys
import time
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

QUOTE0_IMAGE_TASK_KEY = _env("QUOTE0_IMAGE_TASK_KEY")
QUOTE0_TEXT_TASK_KEY  = _env("QUOTE0_TEXT_TASK_KEY")
QUOTE0_PREVIEW_PATH   = _env("QUOTE0_PREVIEW_PATH", str(_HERE / "tmp" / "preview.png"))
SNAPSHOT_CACHE_PATH   = _HERE / "tmp" / "last_snapshot.json"

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
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
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


_RETRYABLE_STATUSES = {"timeout", "error"}
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


def _is_retryable(result: dict) -> bool:
    status = result.get("status", "")
    if status in _RETRYABLE_STATUSES:
        return True
    if status and status.startswith("HTTP "):
        try:
            code = int(status.split(" ", 1)[1])
            return code in _RETRYABLE_HTTP_CODES
        except (ValueError, IndexError):
            pass
    return False


def get_codex_usage(retries: int = 4, delay: float = 3.0):
    """Fetch OpenAI Codex usage with retry on transient failures."""
    for attempt in range(1 + retries):
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
            result = {"ok": False, "status": "timeout"}
        except requests.HTTPError as e:
            code = e.response.status_code
            detail = ""
            try:
                detail = e.response.text[:200]
            except Exception:
                pass
            result = {"ok": False, "status": f"HTTP {code}", "detail": detail}
            if code not in _RETRYABLE_HTTP_CODES:
                return result
        except Exception as e:
            result = {"ok": False, "status": "error", "detail": str(e)[:200]}

        if attempt < retries and _is_retryable(result):
            time.sleep(delay)
            continue
        return result

    return result


def get_today_codex_tokens() -> dict | None:
    """Compute today's Codex token usage from local session JSONL files.

    For each of today's session files, read the cumulative ``total_token_usage``
    that Codex/OpenAI tracks per session and take (last − first) as that
    session's usage, then sum across all of today's sessions. This is the
    authoritative total (the JSONL ``last_token_usage`` field is only the
    per-turn delta and is less robust to parse).

    Timestamps are compared (UTC) against local-day bounds so cross-midnight
    and timezone offsets are handled correctly.
    Returns dict with token totals, or None if no events found.
    """
    import datetime as dtmod
    local_now = datetime.now()
    local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_today_end = local_today_start + dtmod.timedelta(days=1)
    utc_today_start = local_today_start.timestamp()
    utc_today_end = local_today_end.timestamp()

    KEYS = ("input_tokens", "cached_input_tokens", "output_tokens",
            "reasoning_output_tokens", "total_tokens")
    totals = {k: 0 for k in KEYS}
    totals["sessions"] = 0
    seen_sessions = set()

    if not CODEX_SESSIONS_DIR.is_dir():
        return None

    for year_dir in sorted(CODEX_SESSIONS_DIR.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            for day_dir in sorted(month_dir.iterdir()):
                if not day_dir.is_dir() or not day_dir.name.isdigit():
                    continue
                for fpath in sorted(day_dir.glob("*.jsonl")):
                    first_tv = None
                    last_tv = None
                    try:
                        for line in fpath.read_text(encoding="utf-8").splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            ts_str = obj.get("timestamp", "")
                            if not ts_str:
                                continue
                            try:
                                ts_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                ts_unix = ts_dt.timestamp()
                            except Exception:
                                continue
                            if not (utc_today_start <= ts_unix < utc_today_end):
                                continue
                            p = obj.get("payload", {})
                            if obj.get("type") == "event_msg" and p.get("type") == "token_count":
                                tv = p.get("info", {}).get("total_token_usage")
                                if tv:
                                    last_tv = tv
                                    if first_tv is None:
                                        first_tv = tv
                    except Exception:
                        continue

                    if first_tv and last_tv:
                        for k in KEYS:
                            totals[k] += last_tv.get(k, 0) - first_tv.get(k, 0)
                        seen_sessions.add(fpath.stem)

    totals["sessions"] = len(seen_sessions)
    return totals if totals["sessions"] > 0 else None


def _fmt_tokens(n: int) -> str:
    """Format token count for display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


OPENCODE_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def get_today_opencode_tokens() -> dict | None:
    """Query opencode SQLite database for today's token usage.

    Sums per-assistant-message ``tokens`` from the ``message`` table, filtered
    by each message's ``time_created`` (when the tokens were actually
    generated). This correctly attributes usage from long-running sessions
    that span midnight, unlike summing per-session cumulative totals by
    ``session.time_created``.

    Input = prompt tokens (input + cache.read); Output = generated tokens
    (output + reasoning). Same UTC+8 day bounds as Codex.
    """
    import datetime as dtmod
    import sqlite3
    import json

    if not OPENCODE_DB_PATH.exists():
        return None

    local_now = datetime.now()
    local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_today_end = local_today_start + dtmod.timedelta(days=1)
    start_ms = int(local_today_start.timestamp() * 1000)
    end_ms = int(local_today_end.timestamp() * 1000)

    try:
        conn = sqlite3.connect(str(OPENCODE_DB_PATH))
        c = conn.cursor()
        c.execute(
            "SELECT session_id, data FROM message "
            "WHERE time_created >= ? AND time_created < ?",
            (start_ms, end_ms),
        )
        rows = c.fetchall()
        conn.close()

        in_tok = out_tok = reason = cache_read = 0
        cost = 0.0
        sessions = set()
        for sid, data in rows:
            try:
                d = json.loads(data)
            except Exception:
                continue
            if d.get("role") != "assistant":
                continue
            tk = d.get("tokens") or {}
            in_tok += tk.get("input", 0)
            cache_read += tk.get("cache", {}).get("read", 0)
            out_tok += tk.get("output", 0)
            reason += tk.get("reasoning", 0)
            try:
                cost += float(d.get("cost") or 0)
            except (ValueError, TypeError):
                pass
            sessions.add(sid)

        if not sessions:
            return None

        input_total = in_tok + cache_read
        output_total = out_tok + reason
        # Estimate cost at DeepSeek V4 Flash rates (user-specified model):
        # input $0.14/M, cache-hit input $0.0028/M, output $0.28/M.
        p = _OPENCODE_PRICE
        est_cost = (
            in_tok / 1e6 * p["input"]
            + cache_read / 1e6 * p["cached"]
            + output_total / 1e6 * p["output"]
        )
        return {
            "input_tokens": input_total,
            "output_tokens": output_total,
            "reasoning_tokens": reason,
            "cache_read_tokens": cache_read,
            "total_tokens": input_total + output_total,
            "sessions": len(sessions),
            "cost": est_cost,
            "cost_source": "est",
        }
    except Exception:
        return None


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

# Token pricing (USD per 1M tokens), current as of 2026-07.
# Codex uses GPT-5.6 Sol; Opencode uses DeepSeek V4 Flash.
_CODEX_PRICE = {"input": 5.0, "cached": 0.50, "output": 30.0}        # GPT-5.6 Sol
_OPENCODE_PRICE = {"input": 0.14, "cached": 0.0028, "output": 0.28}  # DeepSeek V4 Flash


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
    rate_limit = raw.get("rate_limit", {})

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

    result = {
        "ok": True,
        "short_label": "Week",
        "short_used_percent": short_pct,
        "short_reset": _time_until(short_reset_ts) if short_reset_ts else "?",
        "long_label": "5h",
        "long_used_percent": long_pct,
        "long_reset": _time_until(long_reset_ts) if long_reset_ts else "?",
        "status": _pct_status(short_pct),
        "raw_status": "",
    }

    today_tokens = get_today_codex_tokens()
    if today_tokens:
        result["today_tokens"] = today_tokens["total_tokens"]
        result["today_input_tokens"] = today_tokens["input_tokens"]
        result["today_output_tokens"] = today_tokens["output_tokens"]
        result["today_sessions"] = today_tokens["sessions"]
        # Estimate cost at GPT-5.6 Sol rates (user-specified model):
        # input $5/M, cached input $0.50/M, output $30/M.
        in_tok  = today_tokens["input_tokens"]
        cached  = today_tokens["cached_input_tokens"]
        out_tok = today_tokens["output_tokens"]
        reason  = today_tokens["reasoning_output_tokens"]
        p = _CODEX_PRICE
        result["today_cost"] = (
            (in_tok - cached) / 1e6 * p["input"]
            + cached / 1e6 * p["cached"]
            + (out_tok + reason) / 1e6 * p["output"]
        )
        result["today_cost_source"] = "est"

    return result


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


def build_opencode_snapshot() -> dict:
    """Build structured opencode snapshot from local SQLite DB."""
    today = get_today_opencode_tokens()
    if not today:
        return {"ok": False, "raw_status": "no data"}

    return {
        "ok": True,
        "today_tokens": today["total_tokens"],
        "today_input_tokens": today["input_tokens"],
        "today_output_tokens": today["output_tokens"],
        "today_sessions": today["sessions"],
        "cost": today["cost"],
        "status": "ok",
    }


def build_snapshot() -> dict:
    """Fetch and build full snapshot, falling back to cache on failure."""
    codex_raw = get_codex_usage()
    ds_raw = get_deepseek_balance()
    codex = build_codex_snapshot(codex_raw)
    deepseek = build_deepseek_snapshot(ds_raw)
    opencode = build_opencode_snapshot()
    now = datetime.now().strftime("%H:%M")

    if codex.get("ok"):
        snap = {"codex": codex, "deepseek": deepseek, "opencode": opencode, "updated_at": now, "_cached": False}
        SNAPSHOT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            SNAPSHOT_CACHE_PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        except Exception:
            pass
        return snap

    try:
        cached = json.loads(SNAPSHOT_CACHE_PATH.read_text(encoding="utf-8"))
        if cached.get("codex", {}).get("ok"):
            cached["updated_at"] = now + " (cached)"
            cached["_cached"] = True
            if deepseek.get("ok"):
                cached["deepseek"] = deepseek
            if opencode.get("ok"):
                cached["opencode"] = opencode
            return cached
    except Exception:
        pass

    return {"codex": codex, "deepseek": deepseek, "opencode": opencode, "updated_at": now, "_cached": False}


# ── Legacy normalize (v0.2–v0.3 compat) ───────────────────────────────────────

def _time_until(val) -> str:
    """Human-readable countdown from ISO string or unix timestamp (int/float)."""
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
        return f"{d}d{h}h" if h > 0 else f"{d}d"
    if h > 0:
        return f"{h}h{m:02d}m" if m > 0 else f"{h}h"
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


# ── Run (push) ────────────────────────────────────────────────────────────────

def run(preview: bool = False, text_mode: bool = False):
    snapshot = build_snapshot()

    if text_mode:
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
            oc = snapshot["opencode"]
            if cx["ok"]:
                print(f"Codex:     {cx['short_label']} {cx['short_used_percent']}% reset {cx['short_reset']} [{cx['status']}]")
                if cx["long_used_percent"] is not None:
                    print(f"          {cx['long_label']} {cx['long_used_percent']}%")
                tok = cx.get("today_tokens")
                if tok is not None:
                    print(f"Tokens:    {_fmt_tokens(tok)} today")
            else:
                print(f"Codex:     {cx['raw_status']}")
            if oc.get("ok"):
                print(f"Opencode:  {_fmt_tokens(oc['today_tokens'])} total ({_fmt_tokens(oc['today_input_tokens'])} in / {_fmt_tokens(oc['today_output_tokens'])} out)")
            else:
                print(f"Opencode:  {oc.get('raw_status', 'no data')}")
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

        tokens = get_today_codex_tokens()
        if tokens:
            print(_status("today tokens", True, f"{_fmt_tokens(tokens['total_tokens'])} across {tokens['sessions']} session(s)"))
        else:
            print(_status("today tokens", True, "no sessions yet"))
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

    # ── Opencode ──────────────────────────────────────────────────────────
    print("Opencode:")
    oc_ok = False
    oc = get_today_opencode_tokens()
    if oc:
        print(_status("today tokens", True, f"{_fmt_tokens(oc['total_tokens'])} total ({_fmt_tokens(oc['input_tokens'])} in / {_fmt_tokens(oc['output_tokens'])} out) across {oc['sessions']} session(s)"))
        oc_ok = True
    else:
        print(_status("today tokens", True, "no sessions today"))

    print()

    # ── Render ─────────────────────────────────────────────────────────────
    print("Render:")
    render_ok = False
    if codex_ok or ds_ok or oc_ok:
        try:
            snapshot = {
                "codex": build_codex_snapshot(get_codex_usage() if codex_ok else {"ok": False, "status": "n/a"}),
                "deepseek": build_deepseek_snapshot(get_deepseek_balance() if ds_ok else {"ok": False, "status": "n/a"}),
                "opencode": build_opencode_snapshot(),
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

    # ── default / --preview / --text ───────────────────────────────────────
    success = run(preview=args.preview, text_mode=args.text)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
