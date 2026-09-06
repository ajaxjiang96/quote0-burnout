"""Google AGY (Antigravity) provider: quota fetch + snapshot."""

from __future__ import annotations

import requests

from .core import coerce_percent as _coerce_percent
from .core import env as _env
from .core import pct_status as _pct_status
from .core import time_until as _time_until

AGY_API_KEY   = _env("AGY_API_KEY") or _env("GOOGLE_AGY_API_KEY")
AGY_USAGE_URL = _env("AGY_USAGE_URL", "https://antigravity.google/api/v1/quota")


def get_agy_usage() -> dict:
    """Fetch Google AGY quota usage (daily and weekly quotas)."""
    if not AGY_API_KEY:
        return {"ok": False, "status": "no key"}
    try:
        r = requests.get(
            AGY_USAGE_URL,
            headers={
                "Authorization": f"Bearer {AGY_API_KEY}",
                "Accept": "application/json",
                "User-Agent": "quote0-burnout",
            },
            timeout=15,
        )
        r.raise_for_status()
        return {"ok": True, "raw": r.json()}
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


def _normalize_window(w: dict) -> dict:
    used = _coerce_percent(w.get("used_percent", w.get("percent", w.get("utilization"))))
    resets_at = w.get("resets_at", w.get("resetsAt", w.get("reset_at")))
    reset = _time_until(resets_at) if resets_at else "?"
    return {"used_percent": used, "reset": reset}


def build_agy_snapshot(agy: dict) -> dict:
    """Build structured Google AGY snapshot from raw quota response.

    Standard shape:
    - short_label: "Day"
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
            "short_label": "Day",
            "short_used_percent": None,
            "short_reset": None,
            "long_label": "Week",
            "long_used_percent": None,
            "long_reset": None,
        }

    raw = agy.get("raw", {})
    quotas = raw.get("quotas", raw)

    day_raw = quotas.get("daily", quotas.get("day", quotas.get("primary_window", {})))
    week_raw = quotas.get("weekly", quotas.get("week", quotas.get("secondary_window", {})))

    day = _normalize_window(day_raw)
    week = _normalize_window(week_raw)

    percents = [x for x in (day["used_percent"], week["used_percent"]) if x is not None]
    status = _pct_status(max(percents)) if percents else "unknown"

    return {
        "ok": True,
        "short_label": "Day",
        "short_used_percent": day["used_percent"],
        "short_reset": day["reset"],
        "long_label": "Week",
        "long_used_percent": week["used_percent"],
        "long_reset": week["reset"],
        "status": status,
        "raw_status": "",
    }


def format_agy_text(sn: dict) -> str:
    """Format AGY snapshot for Text API mode."""
    if not sn.get("ok"):
        return sn.get("raw_status", "error")
    parts = []
    if sn.get("short_used_percent") is not None:
        parts.append(f"{sn.get('short_label', 'Day')} {sn['short_used_percent']}% reset {sn.get('short_reset', '?')}")
    if sn.get("long_used_percent") is not None:
        parts.append(f"{sn.get('long_label', 'Week')} {sn['long_used_percent']}% reset {sn.get('long_reset', '?')}")
    return " · ".join(parts) if parts else sn.get("status", "unknown").upper()


get_usage = get_agy_usage
build_snapshot = build_agy_snapshot
format_text = format_agy_text


def is_configured() -> bool:
    return bool(AGY_API_KEY)
