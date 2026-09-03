"""OpenAI Codex provider: token loading, usage fetch, snapshot builder."""

from __future__ import annotations

import json
from pathlib import Path

import requests

from .core import env as _env, pct_status as _pct_status, time_until as _time_until
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



# Canonical provider API (display.py shell + future panel contract use these).
get_usage = get_codex_usage
build_snapshot = build_codex_snapshot
format_text = format_codex_text
