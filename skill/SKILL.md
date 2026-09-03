---
name: quote0-burnout
description: Build and maintain Quote/0 e-ink dashboards — Codex + Claude usage on 296×152 B&W display.
version: 1.0.0
author: Ajax
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [quote0, e-ink, dashboard, codex, claude, pillow]
    related_skills: [e-ink-rendering]
---

# Quote/0 Burnout Dashboard

Render and push a 296×152 B&W AI usage dashboard to MindReset Quote/0 devices.

## When to Use

- Building or modifying a Quote/0 e-ink dashboard
- Pushing image content to Quote/0 via the HTTP API
- Debugging rendering or layout issues (Pillow, pixel fonts)
- Setting up launchd scheduling for periodic updates
- Fetching OpenAI Codex plan usage via OAuth API

## Architecture

```
display.py     # CLI entry: fetch → snapshot → render → push
render.py      # Pillow 296×152 pure B&W PNG
run.sh         # launchd wrapper (sets PATH, sources .env)
config.example.env
```

### Data flow

1. `display.py` → `_load_codex_token()` reads `~/.codex/auth.json`
2. `GET https://chatgpt.com/backend-api/wham/usage` → `rate_limit.primary_window`, `secondary_window`
3. Claude: `GET https://api.anthropic.com/api/oauth/usage`
4. `build_snapshot()` → structured dict
5. `render.py::render_image()` → Pillow → pure B&W PNG
6. `push_image()` → Quote/0 Image API

## Codex Data (Direct OAuth API)

No CLI dependency. Token from `~/.codex/auth.json` or `CODEX_ACCESS_TOKEN` env var.

```python
GET https://chatgpt.com/backend-api/wham/usage
Authorization: Bearer <token>
ChatGPT-Account-Id: <account_id>
```

Response shape:
```python
{
    "plan_type": "pro",
    "rate_limit": {
        "primary_window": {"used_percent": 72.0, "reset_at": 1717000000},
        "secondary_window": {"used_percent": 41.0, "reset_at": 1717600000},
    }
}
```

- `used_percent` → float (72.0 = 72% used)
- `reset_at` → unix timestamp (int)
- Labels hardcoded: primary → "5h", secondary → "Week"

## Claude Data (Claude Code OAuth API)

Token from `~/.claude/.credentials.json` or `CLAUDE_ACCESS_TOKEN` env var.
If OAuth credentials are unavailable, `display.py` falls back to `claude /usage`
and parses the current session/week rows.

```python
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <token>
anthropic-beta: oauth-2025-04-20
User-Agent: claude-code/<version>
```

Response shape:
```python
{
    "five_hour": {"utilization": 42, "resets_at": "2026-07-02T12:00:00Z"},
    "seven_day": {"utilization": 61, "resets_at": "2026-07-05T12:00:00Z"},
}
```

- `utilization` → percent used
- `resets_at` → ISO timestamp
- Labels hardcoded: `five_hour` → "5h", `seven_day` → "Week"

## Snapshot Format

```python
snapshot = {
    "codex": {
        "ok": True,
        "short_label": "5h",
        "short_used_percent": 72,
        "short_reset": "4h41m",
        "long_label": "Week",
        "long_used_percent": 41,
        "long_reset": "5d22h",
        "status": "warn",
    },
    "claude": {
        "ok": True,
        "short_label": "5h",
        "short_used_percent": 42,
        "short_reset": "2h13m",
        "long_label": "Week",
        "long_used_percent": 61,
        "long_reset": "3d4h",
        "status": "ok",
    },
    "updated_at": "16:40",
}
```

Status rules: Codex/Claude `<70%` ok, `70-89%` warn, `≥90%` hot.

## E-Ink Rendering

See `references/eink-design.md` for full layout, font stack, and spacing.

Key points:
- 296×152 pure B&W. `Image.new("L", …).convert("1", dither=NONE)`
- **Fonts**: PixelOperator 16px (section labels and row labels), Minecraftia 8px (timestamp and usage notes)
- **Logos**: 16×16 1-bit PNGs in `assets/logos/`
- **Matched Codex + Claude panels**: each panel is header 18px + two 18px rows
- **Shared bar geometry**: all four rows use the same `note_x`, so bar widths align across both panels
- **Bar**: outline + dot-grid empty area. Filled = REMAINING.
- **Divider**: 6px dash / 4px gap
- **Time format**: ≥24h → `XdXXh`

## Quote/0 API

See `references/quote0-api.md` for endpoint details.

```python
POST https://dot.mindreset.tech/api/authV2/open/device/{id}/image
```

Key rules:
- Single IMAGE_API card → push WITHOUT `taskKey`
- Dither: `DIFFUSION` / `FLOYD_STEINBERG`, border 0
- `refreshNow: true` for immediate display

## launchd Scheduling

`scripts/com.ajax.quote0-burnout.plist.example` → `~/Library/LaunchAgents/`

- `StartCalendarInterval` every 5 minutes at :00, :05...
- `run.sh` exports `PATH="/opt/homebrew/bin:$PATH"` for homebrew deps
- Kickstart: `launchctl kickstart gui/$(id -u)/com.ajax.quote0-burnout`

## Quick Reference

```bash
# Preview (no push)
python display.py --preview

# Push to device
source .env && python display.py

# Self-check
python display.py --check

# Debug snapshot JSON
python display.py --debug-json
```

## Common Pitfalls

1. **Bar shows used instead of remaining.** Text and bar MUST both reflect remaining (100 - used_pct).
2. **Equal bar widths.** Pre-compute max note width across all visible rows and pass consistent `note_x` to both panels.
3. **Pixel font spacing.** Use `textbbox()` after every font change — pixel fonts have very different metrics from system fonts.
4. **Quote/0 404 "未找到图像 API 内容".** Delete and re-add the IMAGE_API card in Dot. App Content Studio.
5. **Device shows stale content.** Set `refreshNow=true` or wait for next content cycle.

## Verification Checklist

- [ ] `python display.py --check` passes all sections
- [ ] `python display.py --preview` renders clean 296×152 PNG
- [ ] Progress bars equal width, both show REMAINING
- [ ] No text overlap or clipping (verify with `textbbox()`)
- [ ] Codex and Claude panels use matching 5h/Week row geometry with no clipping
- [ ] Push succeeds: `python display.py`
