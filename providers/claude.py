"""Claude provider: OAuth token loading (env / file / Keychain / CLI), usage fetch."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .core import (
    coerce_percent as _coerce_percent,
    env as _env,
    pct_status as _pct_status,
    time_until as _time_until,
)

# Claude Code OAuth usage — secrets loaded lazily, never crash on missing env.
CLAUDE_ACCESS_TOKEN = _env("CLAUDE_ACCESS_TOKEN") or _env("CODEXBAR_CLAUDE_OAUTH_TOKEN")
CLAUDE_AUTH_PATH = Path.home() / ".claude" / ".credentials.json"
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_BETA_HEADER = "oauth-2025-04-20"
CLAUDE_USER_AGENT = _env("CLAUDE_USER_AGENT", "claude-code/2.1.0")
CLAUDE_CLI = _env("CLAUDE_CLI", "claude")
CLAUDE_KEYCHAIN_SERVICE = "Claude Code-credentials"
def _extract_claude_access_token(payload: str) -> str:
    """Extract Claude Code OAuth access token from a credentials JSON payload."""
    auth = json.loads(payload)
    oauth = auth.get("claudeAiOauth", {})
    token = oauth.get("accessToken") or oauth.get("access_token") or ""
    if isinstance(token, str):
        return token.strip()
    return ""


def _claude_keychain_services() -> list[str]:
    """Return likely Claude Code Keychain service names, with the canonical name first."""
    services = [CLAUDE_KEYCHAIN_SERVICE]
    try:
        result = subprocess.run(
            ["/usr/bin/security", "dump-keychain"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return services

    if result.returncode != 0:
        return services

    for service in re.findall(r'"svce"<blob>="(Claude Code-credentials[^"]*)"', result.stdout):
        if service not in services:
            services.append(service)
    return services


def _load_claude_token_from_keychain() -> str:
    """Return Claude Code OAuth access token from macOS Keychain."""
    accounts = []
    for account in (os.environ.get("USER", ""), os.environ.get("LOGNAME", ""), Path.home().name):
        account = account.strip()
        if account and account not in accounts:
            accounts.append(account)
    accounts.append("")

    for service in _claude_keychain_services():
        for account in accounts:
            cmd = ["/usr/bin/security", "find-generic-password", "-s", service]
            if account:
                cmd.extend(["-a", account])
            cmd.append("-w")

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=4, check=False)
            except Exception:
                continue
            if result.returncode != 0 or not result.stdout.strip():
                continue

            try:
                token = _extract_claude_access_token(result.stdout)
            except (json.JSONDecodeError, TypeError):
                continue
            if token:
                return token

    raise FileNotFoundError("No Claude OAuth token found in macOS Keychain.")


def _load_claude_token() -> str:
    """Return Claude Code OAuth access token from env, credentials file, or Keychain."""
    if CLAUDE_ACCESS_TOKEN.strip():
        return CLAUDE_ACCESS_TOKEN.strip()

    file_error: Exception | None = None
    if CLAUDE_AUTH_PATH.exists():
        try:
            with open(CLAUDE_AUTH_PATH) as f:
                token = _extract_claude_access_token(f.read())
        except (json.JSONDecodeError, TypeError) as e:
            file_error = e
        else:
            if token:
                return token
            file_error = ValueError("Claude credentials file exists but has no claudeAiOauth.accessToken.")

    try:
        return _load_claude_token_from_keychain()
    except FileNotFoundError as e:
        if file_error:
            raise file_error
        raise FileNotFoundError(
            f"No Claude credentials at {CLAUDE_AUTH_PATH} or macOS Keychain. "
            "Run `claude` to authenticate first, or set CLAUDE_ACCESS_TOKEN in .env."
        ) from e


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



# Canonical provider API (display.py shell + future panel contract use these).
get_usage = get_claude_usage
build_snapshot = build_claude_snapshot
format_text = format_claude_text
