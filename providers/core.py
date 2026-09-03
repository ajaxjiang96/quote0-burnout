"""Shared helpers for all providers (no provider-specific logic)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

CURRENCY_SYMBOLS = {"USD": "$", "CNY": "¥", "EUR": "€", "GBP": "£"}


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def pct_status(pct: int | None) -> str:
    """Used-percent → ok / warn / hot / unknown."""
    if pct is None:
        return "unknown"
    if pct >= 90:
        return "hot"
    if pct >= 70:
        return "warn"
    return "ok"


def coerce_percent(value) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (ValueError, TypeError):
        return None


def window_label(minutes: int | None) -> str:
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


def time_until(val) -> str:
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
