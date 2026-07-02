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
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from render import render_image

# ── Config (lazy — never crashes on missing env) ──────────────────────────────

_HERE = Path(__file__).parent

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

QUOTE0_API_KEY     = _env("QUOTE0_API_KEY")
QUOTE0_DEVICE_ID   = _env("QUOTE0_DEVICE_ID")
CLAUDE_ACCESS_TOKEN = _env("CLAUDE_ACCESS_TOKEN") or _env("CODEXBAR_CLAUDE_OAUTH_TOKEN")
QUOTE0_REFRESH_NOW = _env("QUOTE0_REFRESH_NOW", "false").lower() == "true"

QUOTE0_IMAGE_TASK_KEY = _env("QUOTE0_IMAGE_TASK_KEY")
QUOTE0_TEXT_TASK_KEY  = _env("QUOTE0_TEXT_TASK_KEY")
QUOTE0_PREVIEW_PATH   = _env("QUOTE0_PREVIEW_PATH", "/tmp/quote0_burnout_preview.png")

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
CLAUDE_AUTH_PATH = Path.home() / ".claude" / ".credentials.json"
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_BETA_HEADER = "oauth-2025-04-20"
CLAUDE_USER_AGENT = _env("CLAUDE_USER_AGENT", "claude-code/2.1.0")
CLAUDE_CLI = _env("CLAUDE_CLI", "claude")


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


def _load_claude_token() -> str:
    """Return Claude Code OAuth access token from env or ~/.claude/.credentials.json."""
    if CLAUDE_ACCESS_TOKEN.strip():
        return CLAUDE_ACCESS_TOKEN.strip()

    if not CLAUDE_AUTH_PATH.exists():
        raise FileNotFoundError(
            f"No Claude credentials at {CLAUDE_AUTH_PATH}. "
            "Run `claude` to authenticate first, or set CLAUDE_ACCESS_TOKEN in .env."
        )

    with open(CLAUDE_AUTH_PATH) as f:
        auth = json.load(f)

    oauth = auth.get("claudeAiOauth", {})
    token = oauth.get("accessToken", "")
    if not token:
        raise ValueError("Claude credentials file exists but has no claudeAiOauth.accessToken.")
    return token


def _parse_claude_cli_reset(value: str, now: datetime | None = None) -> str | None:
    """Parse Claude CLI reset text, e.g. 'Jul 2 at 12:29pm (Asia/Shanghai)'."""
    text = value.strip()
    tz = timezone.utc

    tz_match = re.search(r"\(([^)]+)\)\s*$", text)
    if tz_match:
        try:
            tz = ZoneInfo(tz_match.group(1))
        except Exception:
            tz = timezone.utc
        text = text[:tz_match.start()].strip()

    match = re.match(
        r"([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s+at\s+"
        r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    month_token, day, hour, minute, meridiem = match.groups()
    minute = minute or "00"
    try:
        month = datetime.strptime(month_token[:3].title(), "%b").month
    except ValueError:
        return None

    base = now or datetime.now(tz)
    if base.tzinfo is None:
        base = base.replace(tzinfo=tz)
    else:
        base = base.astimezone(tz)

    hour_i = int(hour) % 12
    if meridiem.lower() == "pm":
        hour_i += 12

    candidate = datetime(
        base.year,
        month,
        int(day),
        hour_i,
        int(minute),
        tzinfo=tz,
    )
    if candidate < base - timedelta(days=1):
        candidate = candidate.replace(year=base.year + 1)

    return candidate.isoformat()


def _parse_claude_cli_window(line: str, now: datetime | None = None) -> dict:
    pct_match = re.search(
        r":\s*(\d+(?:\.\d+)?)%\s*(used|left|remaining)?",
        line,
        re.IGNORECASE,
    )
    if not pct_match:
        return {}

    pct = float(pct_match.group(1))
    qualifier = (pct_match.group(2) or "used").lower()
    if qualifier in {"left", "remaining"}:
        pct = 100 - pct
    pct = max(0, min(100, pct))

    window = {"utilization": int(round(pct))}

    reset_match = re.search(r"\bresets\s+(.+)$", line, re.IGNORECASE)
    if reset_match:
        reset_at = _parse_claude_cli_reset(reset_match.group(1), now=now)
        if reset_at:
            window["resets_at"] = reset_at

    return window


def parse_claude_cli_usage(text: str, now: datetime | None = None) -> dict:
    """Parse `claude /usage` text into the OAuth-shaped usage windows we render."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lowered = [(line.lower(), line) for line in lines]

    def find_line(prefix: str) -> str | None:
        prefix_l = prefix.lower()
        for line_l, line in lowered:
            if line_l.startswith(prefix_l):
                return line
        return None

    session_line = find_line("Current session:")
    week_line = find_line("Current week (all models):") or find_line("Current week:")

    raw = {}
    if session_line:
        window = _parse_claude_cli_window(session_line, now=now)
        if window:
            raw["five_hour"] = window
    if week_line:
        window = _parse_claude_cli_window(week_line, now=now)
        if window:
            raw["seven_day"] = window

    return raw


def get_claude_usage_from_cli():
    """Fetch Claude subscription usage via `claude /usage` when OAuth credentials are absent."""
    try:
        result = subprocess.run(
            [CLAUDE_CLI, "/usage"],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "status": "no cli", "detail": f"`{CLAUDE_CLI}` not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout", "detail": f"`{CLAUDE_CLI} /usage` timed out"}
    except Exception as e:
        return {"ok": False, "status": "cli error", "detail": str(e)[:200]}

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:200]
        return {"ok": False, "status": f"cli exit {result.returncode}", "detail": detail}

    raw = parse_claude_cli_usage(result.stdout)
    if not raw:
        return {"ok": False, "status": "parse error", "detail": result.stdout.strip()[:200]}

    return {"ok": True, "raw": raw, "source": "cli"}


def get_claude_usage():
    """Fetch Claude subscription usage via OAuth API, falling back to Claude CLI."""
    try:
        access_token = _load_claude_token()

        r = requests.get(
            CLAUDE_USAGE_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "anthropic-beta": CLAUDE_BETA_HEADER,
                "User-Agent": CLAUDE_USER_AGENT,
            },
            timeout=15,
        )
        r.raise_for_status()
        return {"ok": True, "raw": r.json(), "source": "oauth"}

    except (FileNotFoundError, ValueError) as e:
        cli = get_claude_usage_from_cli()
        if cli.get("ok"):
            return cli
        return {
            "ok": False,
            "status": "no auth",
            "detail": f"{str(e)}; CLI fallback: {cli.get('status', 'error')}",
        }
    except requests.Timeout:
        cli = get_claude_usage_from_cli()
        return cli if cli.get("ok") else {"ok": False, "status": "timeout", "detail": cli.get("detail", "")}
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.text[:200]
        except Exception:
            pass
        cli = get_claude_usage_from_cli()
        if cli.get("ok"):
            return cli
        return {"ok": False, "status": f"HTTP {e.response.status_code}", "detail": detail}
    except Exception as e:
        cli = get_claude_usage_from_cli()
        return cli if cli.get("ok") else {"ok": False, "status": "error", "detail": str(e)[:200]}


# ── Snapshot builder (v0.4) ────────────────────────────────────────────────────

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

    primary = rate_limit.get("primary_window", {})
    secondary = rate_limit.get("secondary_window", {})

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

    return {
        "ok": True,
        "short_label": "5h",
        "short_used_percent": short_pct,
        "short_reset": _time_until(short_reset_ts) if short_reset_ts else "?",
        "long_label": "Week",
        "long_used_percent": long_pct,
        "long_reset": _time_until(long_reset_ts) if long_reset_ts else "?",
        "status": _pct_status(short_pct),
        "raw_status": "",
    }


def _coerce_percent(value) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (ValueError, TypeError):
        return None


def build_claude_snapshot(claude: dict) -> dict:
    """Build structured Claude subscription snapshot from OAuth usage response."""
    if not claude.get("ok"):
        status = claude.get("status", "error")
        return {
            "ok": False,
            "short_label": "?",
            "short_used_percent": None,
            "short_reset": "?",
            "long_label": "?",
            "long_used_percent": None,
            "long_reset": "?",
            "status": "error",
            "raw_status": status,
        }

    raw = claude.get("raw", {})
    short = raw.get("five_hour") or {}
    long = raw.get("seven_day") or raw.get("seven_day_oauth_apps") or {}

    short_pct = _coerce_percent(short.get("utilization"))
    long_pct = _coerce_percent(long.get("utilization"))
    short_reset = short.get("resets_at")
    long_reset = long.get("resets_at")

    return {
        "ok": True,
        "short_label": "5h",
        "short_used_percent": short_pct,
        "short_reset": _time_until(short_reset) if short_reset else "?",
        "long_label": "Week",
        "long_used_percent": long_pct,
        "long_reset": _time_until(long_reset) if long_reset else "?",
        "status": _pct_status(short_pct),
        "raw_status": "",
    }


def build_snapshot() -> dict:
    """Fetch and build full snapshot."""
    codex = get_codex_usage()
    claude = get_claude_usage()
    return {
        "codex": build_codex_snapshot(codex),
        "claude": build_claude_snapshot(claude),
        "updated_at": datetime.now().strftime("%H:%M"),
    }


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


def format_claude_text(sn: dict) -> str:
    """Format Claude snapshot for Text API."""
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
        cl_text = format_claude_text(snapshot["claude"])
        print(f"Codex:     {cx_text.replace(chr(10), ' / ')}")
        print(f"Claude:    {cl_text.replace(chr(10), ' / ')}")

        now = snapshot["updated_at"]
        payload = {
            "message": f"Codex {cx_text}\nClaude {cl_text}",
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
