"""DeepSeek provider: balance fetch + peak/off-peak billing window pricing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from .core import CURRENCY_SYMBOLS, env as _env

# DeepSeek billing window (peak / off-peak)
# Official pricing: https://api-docs.deepseek.com/quick_start/pricing
# (fetched 2026-08-21, en + zh-cn). Peak hours: 01:00–04:00 and 06:00–10:00
# UTC (= 北京 9:00–12:00, 14:00–18:00); ALL other hours are off-peak at 50%.
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL   = _env("DEEPSEEK_MODEL", "deepseek-v4-flash")
# UTC (= 北京 9:00–12:00, 14:00–18:00); ALL other hours are off-peak at 50%.
DEEPSEEK_PRICING = {
    "deepseek-v4-flash": {
        "label": "DeepSeek-V4-Flash",
        # USD per 1M tokens (cache-miss input / output)
        "USD": {
            "in":  {"peak": 0.44, "off": 0.22},
            "out": {"peak": 1.32, "off": 0.66},
        },
        # CNY per 1M tokens (cache-miss input / output)
        "CNY": {
            "in":  {"peak": 3.0, "off": 1.5},
            "out": {"peak": 9.0, "off": 4.5},
        },
    },
    "deepseek-v4-pro": {
        "label": "DeepSeek-V4-Pro",
        "USD": {
            "in":  {"peak": 1.32, "off": 0.66},
            "out": {"peak": 3.96, "off": 1.98},
        },
        "CNY": {
            "in":  {"peak": 9.0, "off": 4.5},
            "out": {"peak": 27.0, "off": 13.5},
        },
    },
}
# deepseek-v4-flash-vision-exp (launched 2026-08-21): multimodal model billed
# at the same token prices as deepseek-v4-flash — images convert to tokens
# (≤384 tokens/image, resized to ~800×800), billed together with text tokens.
DEEPSEEK_PRICING["deepseek-v4-flash-vision-exp"] = DEEPSEEK_PRICING["deepseek-v4-flash"]


def deepseek_window(now_utc: datetime | None = None, currency: str = "USD") -> dict:
    """Current DeepSeek billing window for DEEPSEEK_MODEL.

    Peak = full price, off-peak = 50%. Returns the window label, factor,
    the current per-1M-token rates (cache-miss input / output) in the
    account's currency (USD or CNY, falls back to USD), plus how long the
    current window lasts (`ends_in` seconds, `countdown` human string) and
    which window comes next (`next_window`).

    Peak windows: [01:00,04:00) and [06:00,10:00) UTC → next transition at
    04:00 / 10:00. Off-peak: [00:00,01:00) → 01:00; [04:00,06:00) → 06:00;
    [10:00,24:00) → 01:00 next day.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    h = now_utc.hour
    peak = (1 <= h < 4) or (6 <= h < 10)

    if 1 <= h < 4:
        end_h, end_d, next_win = 4, 0, "OFF"
    elif 4 <= h < 6:
        end_h, end_d, next_win = 6, 0, "PEAK"
    elif 6 <= h < 10:
        end_h, end_d, next_win = 10, 0, "OFF"
    elif 10 <= h < 24:
        end_h, end_d, next_win = 1, 1, "PEAK"
    else:  # 00:00 ≤ h < 01:00
        end_h, end_d, next_win = 1, 0, "PEAK"

    ends = now_utc.replace(hour=end_h, minute=0, second=0, microsecond=0) + timedelta(days=end_d)
    ends_in = max(0, int((ends - now_utc).total_seconds()))

    factor = 1.0 if peak else 0.5
    p = DEEPSEEK_PRICING.get(DEEPSEEK_MODEL, DEEPSEEK_PRICING["deepseek-v4-flash"])
    cur = p.get(currency, p["USD"])
    key = "peak" if peak else "off"
    return {
        "model": DEEPSEEK_MODEL,
        "peak": peak,
        "window": "PEAK" if peak else "OFF",
        "factor": factor,
        "price_in": cur["in"][key],
        "price_out": cur["out"][key],
        "ends_in": ends_in,
        "countdown": _countdown(ends_in),
        "next_window": next_win,
    }


def _countdown(seconds: int) -> str:
    """Compact countdown: 2h22m / 45m / 15h. Rounds down to the minute."""
    secs = max(0, int(seconds))
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h >= 24:
        d, h = divmod(h, 24)
        return f"{d}d{h}h" if h else f"{d}d"
    if h > 0:
        return f"{h}h{m:02d}m" if m else f"{h}h"
    return f"{m}m"


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
    win = deepseek_window(currency=currency)

    return {
        "ok": True,
        "balance": amount,
        "currency": currency,
        "symbol": CURRENCY_SYMBOLS.get(currency, "$"),
        "status": _balance_status(amount, available),
        "raw_status": "",
        "model": win["model"],
        "window": win["window"],
        "factor": win["factor"],
        "price_in": win["price_in"],
        "price_out": win["price_out"],
        "ends_in": win["ends_in"],
        "countdown": win["countdown"],
        "next_window": win["next_window"],
    }

def format_deepseek_text(sn: dict) -> str:
    """Format deepseek snapshot for Text API."""
    if not sn.get("ok"):
        return sn.get("raw_status", "error")

    bal = sn.get("balance")
    if bal is None:
        return "unknown"

    parts = [f"{sn['symbol']}{bal:.2f}"]
    win = sn.get("window")
    if win:
        f_str = f" x{sn['factor']:g}" if sn.get("factor") else ""
        rate = ""
        if sn.get("price_in") is not None and sn.get("price_out") is not None:
            sym = sn["symbol"]
            rate = f" in {sym}{sn['price_in']:.2f} out {sym}{sn['price_out']:.2f}"
        cd = sn.get("countdown")
        parts.append(f"{win}{f_str}{rate}" + (f" {sn.get('next_window', '')} in {cd}" if cd else ""))
    parts.append(sn["status"].upper())
    return " ".join(parts)



# Canonical provider API (display.py shell + future panel contract use these).
get_balance = get_deepseek_balance
build_snapshot = build_deepseek_snapshot
format_text = format_deepseek_text


def is_configured() -> bool:
    return bool(DEEPSEEK_API_KEY)
