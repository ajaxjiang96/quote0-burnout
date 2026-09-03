"""OpenCode Go (Zen) provider: flat-rate subscription usage fetch + snapshot."""

from __future__ import annotations

import requests

from .core import env as _env, pct_status as _pct_status, time_until as _time_until

# OpenCode Go (OpenCode Zen "Go" flat-rate subscription) — second-panel provider.
# Dollar limits: $12 per 5h, $30 per week, $60 per month. Usage API returns %
# of each window used + reset time.
OPENCODE_GO_API_KEY = _env("OPENCODE_GO_API_KEY")
OPENCODE_USAGE_URL  = "https://opencode.ai/zen/go/v1/usage"
def get_opencode_usage():
    """Fetch OpenCode Go usage. rolling/weekly/monthly percent + reset time."""
    if not OPENCODE_GO_API_KEY:
        return {"ok": False, "status": "no key"}
    try:
        r = requests.get(
            OPENCODE_USAGE_URL,
            headers={
                "Authorization": f"Bearer {OPENCODE_GO_API_KEY}",
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


def _oc_win(w: dict) -> dict:
    """Normalize one OpenCode usage window → {used_percent, reset}."""
    used = w.get("percent")
    try:
        used = int(float(used)) if used is not None else None
    except (ValueError, TypeError):
        used = None
    reset = _time_until(w.get("resetsAt")) if w.get("resetsAt") else "?"
    return {"used_percent": used, "reset": reset}


def build_opencode_snapshot(oc: dict) -> dict:
    """Build structured opencode snapshot from Zen usage response.

    Mirrors the codex snapshot shape (short=rolling 5h, long=weekly) so the
    renderer can be reused; monthly is kept for text/JSON completeness.
    """
    if not oc.get("ok"):
        return {
            "ok": False,
            "status": "error",
            "raw_status": oc.get("status", "error"),
            "rolling": {}, "weekly": {}, "monthly": {},
        }

    usage = oc.get("raw", {}).get("usage", {})
    rolling = _oc_win(usage.get("rolling") or {})
    weekly = _oc_win(usage.get("weekly") or {})
    monthly = _oc_win(usage.get("monthly") or {})

    percents = [x["used_percent"] for x in (rolling, weekly, monthly) if x["used_percent"] is not None]
    status = _pct_status(max(percents)) if percents else "unknown"

    return {
        "ok": True,
        "rolling": rolling,
        "weekly": weekly,
        "monthly": monthly,
        "short_label": "5h",
        "short_used_percent": rolling["used_percent"],
        "short_reset": rolling["reset"],
        "long_label": "Week",
        "long_used_percent": weekly["used_percent"],
        "long_reset": weekly["reset"],
        "status": status,
        "raw_status": "",
    }

def format_opencode_text(sn: dict) -> str:
    """Format opencode snapshot for Text API (compact multi-window)."""
    if not sn.get("ok"):
        return sn.get("raw_status", "error")
    parts = []
    for lbl, key in (("5h", "rolling"), ("Wk", "weekly"), ("Mo", "monthly")):
        w = sn.get(key)
        if w and w.get("used_percent") is not None:
            parts.append(f"{lbl} {w['used_percent']}% reset {w.get('reset', '?')}")
    return " · ".join(parts) if parts else sn.get("status", "unknown").upper()



# Canonical provider API (display.py shell + future panel contract use these).
get_usage = get_opencode_usage
build_snapshot = build_opencode_snapshot
format_text = format_opencode_text
