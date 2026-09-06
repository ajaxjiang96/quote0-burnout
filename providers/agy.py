"""Google AGY (Antigravity) provider: quota fetch + snapshot via `agy` CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import requests

from .core import coerce_percent as _coerce_percent
from .core import env as _env
from .core import pct_status as _pct_status
from .core import time_until as _time_until

AGY_API_KEY   = _env("AGY_API_KEY") or _env("GOOGLE_AGY_API_KEY")
AGY_USAGE_URL = _env("AGY_USAGE_URL", "https://antigravity.google/api/v1/quota")
AGY_AUTH_PATH = Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
AGY_CLI       = _env("AGY_CLI", "agy")


def _find_agy_cli() -> str | None:
    """Return path to `agy` CLI executable if available."""
    cli = os.environ.get("AGY_CLI", "").strip() or AGY_CLI
    if cli and shutil.which(cli):
        return cli
    candidates = [
        Path.home() / ".local" / "bin" / "agy",
        Path("/usr/local/bin/agy"),
        Path("/opt/homebrew/bin/agy"),
    ]
    for p in candidates:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def _load_token() -> tuple[str, str]:
    """Return access token / cli identifier and source (env / token file / cli)."""
    env_token = os.environ.get("AGY_API_KEY") or os.environ.get("GOOGLE_AGY_API_KEY") or AGY_API_KEY
    if env_token:
        return env_token.strip(), "env"
    if AGY_AUTH_PATH.exists():
        try:
            data = json.loads(AGY_AUTH_PATH.read_text(encoding="utf-8"))
            tok = data.get("token", {}).get("access_token") or data.get("access_token") or ""
            if tok.strip():
                return tok.strip(), "token file"
        except Exception:
            pass
    cli = _find_agy_cli()
    if cli:
        return cli, "cli"
    return "", ""


def parse_agy_cli_output(text: str) -> dict:
    """Parse `agy --print /quota` output into structured window dictionaries.

    Format (tab-separated records):
      Gemini Models           Weekly Limit Remaining    97%    2026-09-13T13:23:36Z
      Gemini Models           Five Hour Limit Remaining 83%    2026-09-06T18:23:36Z
      Claude and GPT models   Weekly Limit Remaining    100%   2026-09-13T13:58:49Z
      Claude and GPT models   Five Hour Limit Remaining 100%   2026-09-06T18:58:49Z
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    groups: dict[str, dict] = {}
    for line in lines:
        cols = [c.strip() for c in line.split("\t") if c.strip()]
        if len(cols) < 3:
            cols = [c.strip() for c in re.split(r"\t+|\s{2,}", line) if c.strip()]
        if len(cols) < 3:
            continue

        group_name = cols[0]
        desc = cols[1]
        pct_raw = cols[2]
        resets_at = cols[3].strip() if len(cols) > 3 else None

        pct_match = re.search(r"(\d+(?:\.\d+)?)%", pct_raw)
        if not pct_match:
            continue
        remaining = float(pct_match.group(1))
        used = max(0, min(100, 100.0 - remaining))

        desc_l = desc.lower()
        if any(k in desc_l for k in ("five", "5h", "hour", "day", "daily")):
            win_key = "five_hour"
            win_label = "Day" if "day" in desc_l else "5h"
        elif "week" in desc_l:
            win_key = "weekly"
            win_label = "Week"
        else:
            win_key = desc_l
            win_label = desc

        win_data = {
            "label": win_label,
            "remaining": int(round(remaining)),
            "used_percent": int(round(used)),
            "resets_at": resets_at,
        }

        g_l = group_name.lower()
        if "gemini" in g_l:
            g_key = "gemini"
        elif any(k in g_l for k in ("claude", "gpt")):
            g_key = "claude_gpt"
        else:
            g_key = g_l

        if g_key not in groups:
            groups[g_key] = {}
        groups[g_key][win_key] = win_data

    return groups


def get_agy_usage_from_cli() -> dict:
    """Fetch AGY quota usage via `agy --print /quota`."""
    cli = _find_agy_cli()
    if not cli:
        return {"ok": False, "status": "no cli", "detail": "agy CLI not found"}
    try:
        result = subprocess.run(
            [cli, "--print", "/quota"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "status": "no cli", "detail": f"`{cli}` not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout", "detail": f"`{cli} --print /quota` timed out"}
    except Exception as e:
        return {"ok": False, "status": "cli error", "detail": str(e)[:200]}

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:200]
        return {"ok": False, "status": f"cli exit {result.returncode}", "detail": detail}

    raw = parse_agy_cli_output(result.stdout)
    if not raw:
        return {"ok": False, "status": "parse error", "detail": result.stdout.strip()[:200]}

    return {"ok": True, "raw": raw, "source": "cli"}


def _get_agy_usage_http() -> dict:
    """Fallback: fetch Google AGY quota via HTTP if custom endpoint configured."""
    token, _ = _load_token()
    if not token or token == "cli":
        return {"ok": False, "status": "no key"}
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "quote0-burnout",
        }
        if "retrieveUserQuotaSummary" in AGY_USAGE_URL or _env("AGY_METHOD").upper() == "POST":
            headers["Content-Type"] = "application/json"
            r = requests.post(AGY_USAGE_URL, headers=headers, json={}, timeout=15)
        else:
            r = requests.get(AGY_USAGE_URL, headers=headers, timeout=15)
        r.raise_for_status()
        return {"ok": True, "raw": r.json(), "source": "http"}
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


def get_agy_usage() -> dict:
    """Fetch Google AGY quota usage, preferring `agy --print /quota`."""
    if AGY_USAGE_URL and AGY_USAGE_URL != "https://antigravity.google/api/v1/quota":
        res = _get_agy_usage_http()
        if res.get("ok"):
            return res

    cli_res = get_agy_usage_from_cli()
    if cli_res.get("ok"):
        return cli_res

    if AGY_USAGE_URL:
        http_res = _get_agy_usage_http()
        if http_res.get("ok"):
            return http_res

    return cli_res


def build_agy_snapshot(agy: dict) -> dict:
    """Build structured Google AGY snapshot from CLI or REST raw response.

    Standard shape:
    - short_label: "5h" (or "Day")
    - short_used_percent, short_reset
    - long_label: "Week"
    - long_used_percent, long_reset
    - status: "ok" | "warn" | "hot"
    """
    if not agy.get("ok"):
        return {
            "ok": False,
            "status": "error",
            "raw_status": agy.get("status", "error"),
            "short_label": "5h",
            "short_used_percent": None,
            "short_reset": None,
            "long_label": "Week",
            "long_used_percent": None,
            "long_reset": None,
        }

    raw = agy.get("raw", {})
    if isinstance(raw, str):
        raw = parse_agy_cli_output(raw)

    # Primary model group: gemini preferred, or first group found
    group = raw.get("gemini") or raw.get("quotas") or raw
    if isinstance(group, dict) and not any(k in group for k in ("five_hour", "weekly", "daily", "day", "short", "long")):
        for v in raw.values():
            if isinstance(v, dict) and any(k in v for k in ("five_hour", "weekly", "daily", "day", "short", "long")):
                group = v
                break

    short_raw = (
        group.get("five_hour")
        or group.get("short")
        or group.get("daily")
        or group.get("day")
        or {}
    )
    long_raw = (
        group.get("weekly")
        or group.get("long")
        or group.get("week")
        or {}
    )

    def _norm(w: dict, default_lbl: str) -> tuple[str, int | None, str | None]:
        if not isinstance(w, dict) or not w:
            return default_lbl, None, None
        lbl = w.get("label") or default_lbl
        if "used_percent" in w and w["used_percent"] is not None:
            used = _coerce_percent(w["used_percent"])
        elif "remaining" in w and w["remaining"] is not None:
            used = max(0, min(100, 100 - _coerce_percent(w["remaining"])))
        elif "percent" in w:
            used = _coerce_percent(w["percent"])
        elif "utilization" in w:
            used = _coerce_percent(w["utilization"])
        else:
            used = None

        resets_at = w.get("resets_at") or w.get("resetsAt") or w.get("reset_at")
        reset = _time_until(resets_at) if resets_at else "?"
        return lbl, used, reset

    default_short_lbl = "Day" if ("daily" in group or "day" in group) else "5h"
    short_lbl, short_used, short_reset = _norm(short_raw, default_short_lbl)
    long_lbl, long_used, long_reset = _norm(long_raw, "Week")

    percents = [x for x in (short_used, long_used) if x is not None]
    status = _pct_status(max(percents)) if percents else "unknown"

    return {
        "ok": True,
        "short_label": short_lbl,
        "short_used_percent": short_used,
        "short_reset": short_reset,
        "long_label": long_lbl,
        "long_used_percent": long_used,
        "long_reset": long_reset,
        "status": status,
        "raw_status": "",
    }


def format_agy_text(sn: dict) -> str:
    """Format AGY snapshot for Text API mode."""
    if not sn.get("ok"):
        return sn.get("raw_status", "error")
    parts = []
    if sn.get("short_used_percent") is not None:
        parts.append(f"{sn.get('short_label', '5h')} {sn['short_used_percent']}% reset {sn.get('short_reset', '?')}")
    if sn.get("long_used_percent") is not None:
        parts.append(f"{sn.get('long_label', 'Week')} {sn['long_used_percent']}% reset {sn.get('long_reset', '?')}")
    return " · ".join(parts) if parts else sn.get("status", "unknown").upper()


get_usage = get_agy_usage
build_snapshot = build_agy_snapshot
format_text = format_agy_text


def is_configured() -> bool:
    """Return True if AGY token exists, env is set, or agy CLI binary is available."""
    return bool(
        os.environ.get("AGY_API_KEY", "").strip()
        or os.environ.get("GOOGLE_AGY_API_KEY", "").strip()
        or AGY_API_KEY
        or AGY_AUTH_PATH.exists()
        or _find_agy_cli()
    )

