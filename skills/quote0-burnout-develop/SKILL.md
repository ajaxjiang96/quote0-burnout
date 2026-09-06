---
name: quote0-burnout-develop
description: Build or modify Quote/0 e-ink dashboard providers and layout.
version: 1.0.0
author: Jiacheng Jiang (ajaxjiang96), Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [quote0, e-ink, dashboard, providers, pillow]
    related_skills: [e-ink-rendering, quote0-burnout-deploy]
---

# Quote/0 Burnout Dashboard — Development

Render and push a 296×152 1-bit B&W AI usage dashboard (Codex, Claude, Google AGY,
DeepSeek, OpenCode Go) to MindReset Quote/0 devices. **This skill is for building
and modifying the dashboard.** To ship a version to a device, load
`quote0-burnout-deploy` instead.

## When to Use

- Adding or changing a provider (`providers/`)
- Modifying layout, rendering, fonts, or 1-bit output (`render.py`)
- Debugging a snapshot, status classification, or Quote/0 push 404
- Writing/updating tests for providers or layout

Don't use for: publishing a release to the device — that's `quote0-burnout-deploy`.

## Architecture

```
display.py     # CLI entry: orchestration, scheduling, snapshot cache, push
render.py      # Pillow 296×152 pure B&W PNG (grid layouts, tiers, fonts)
providers/     # One module per provider (fetch → snapshot → text)
  ├── core.py      # Shared helpers: env, countdowns, status clamping
  ├── codex.py     # OpenAI Codex OAuth usage + reset credits
  ├── claude.py    # Anthropic Claude OAuth / CLI usage
  ├── deepseek.py  # DeepSeek balance + billing-window pricing
  ├── opencode.py  # OpenCode Go (Zen) flat-rate subscription
  └── agy.py       # Google Antigravity quota via `agy --print /quota`
run.sh         # launchd wrapper (sets PATH, sources .env)
config.example.env
CONTRIBUTING.md # Provider contract, layout tiers, testing standards
```

### Data flow

1. `display.py` calls `configured_providers()` (credential-gated, no network)
2. Each provider's `get_usage()` fetches its quota/balance
3. `build_snapshot()` normalizes into the standard snapshot dict
4. `display.py` fingerprints each provider against cache for recency ordering (#10)
5. `render.py::render_image()` emits the 296×152 1-bit PNG
6. `push_image()` sends it to the Quote/0 Image API

For the provider contract, see [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Provider Data Sources

### Codex (direct OAuth API)
Token from the Codex CLI's local auth file (or `CODEX_ACCESS_TOKEN` env var).
```
GET https://chatgpt.com/backend-api/wham/usage   (Authorization: Bearer; ChatGPT-Account-Id)
```
`rate_limit.primary_window` → "5h", `secondary_window` → "Week". Reset-credit
fields (`resets_available`, `reset_expiry`) feed an extra Codex-only row.

### Claude (Claude Code OAuth / CLI)
Token from the Claude Code CLI's local credentials (or `CLAUDE_ACCESS_TOKEN`).
Falls back to `claude /usage` CLI. `five_hour` → "5h", `seven_day` → "Week"
(`utilization` = percent used).

### DeepSeek (balance + billing window)
`DEEPSEEK_API_KEY` (balance) + `DEEPSEEK_MODEL` for the pricing window
(`deepseek-v4-flash` / `-pro` / `-flash-vision-exp`). Renders balance as a hero
value with an in/out price badge and a peak/off countdown. Never hardcode the
currency symbol — read `currency` (CNY/USD/EUR).

### OpenCode Go (Zen "Go")
`OPENCODE_GO_API_KEY` → `GET https://opencode.ai/zen/go/v1/usage`. Three windows
(rolling 5h / weekly / monthly), each `{percent, resetsAt, status}`.

### Google AGY (Antigravity) — **CLI, not REST**
AGY has **no public REST quota endpoint** (`https://antigravity.google/api/v1/quota`
404s — that URL is only used if the user overrides `AGY_USAGE_URL`). The real
source is the `agy` CLI slash command:
```
agy --print /quota    # human also: /usage
```
which prints tab-separated records:
```
Gemini Models           Five Hour Limit Remaining    83%    2026-09-06T18:23:36Z
Gemini Models           Weekly Limit Remaining       97%    2026-09-13T13:23:36Z
Claude and GPT models   Five Hour Limit Remaining    100%   ...
```
`providers/agy.py` shells out via `subprocess` (`_find_agy_cli()` resolves the
binary via `$AGY_CLI`, then `PATH`, then common install dirs), parses the records,
takes the **gemini** group by default, and maps `used% = 100 − remaining%`;
five_hour → short label "5h", weekly → "Week". `is_configured()` is true when any
token source (`AGY_API_KEY`, `GOOGLE_AGY_API_KEY`, or the Antigravity CLI's local
OAuth token) **or** the `agy` CLI binary is available. CLI run ≈6.4s — fine for
the 5-min launchd cadence.

## Snapshot Format

```python
snapshot = {
    "codex":    {"ok": True, "short_label": "5h", "short_used_percent": 72,
                 "short_reset": "4h41m", "long_label": "Week",
                 "long_used_percent": 41, "long_reset": "5d22h", "status": "warn"},
    "deepseek": {"ok": True, "balance": 18.42, "currency": "USD", "symbol": "$",
                 "window": "OFF", "status": "ok"},
    "agy":      {"ok": True, "short_label": "5h", "short_used_percent": 35,
                 "short_reset": "3h47m", "long_label": "Week",
                 "long_used_percent": 6, "long_reset": "6d", "status": "ok"},
    "layout": "auto", "second_panel": "opencode", "updated_at": "16:40",
}
```

Status rules: `short_used_percent`/`long_used_percent` `<70%` → ok, `70-89%` → warn,
`≥90%` → hot. DeepSeek `≥10` balance → ok, `3-10` → warn, `<3`/unavailable → hot.
Providers with `ok=False` (no auth, timeout, HTTP error) are **hidden**, not shown
as error cells.

## Layout & Rendering

- `LAYOUT` env or `--layout {auto,stack,1+1,1+2,2+2}`; `auto` fits the live-provider
  count (`0/1`→stack, `2`→1+1, `3`→1+2, `4`→2+2).
- Grid engine (`_render_grid`) draws quarter (148×76) and half (296×76) cells;
  `stack` falls back to the legacy `_render_v5` column layout.
- **Recency ordering**: `_order_panels` sorts live providers by `updated_at` desc
  (the LAST data-change time via fingerprinting), ties fall back to the canonical
  order (`codex, claude, deepseek, opencode, agy`). Top-left is most visible.
- **Cached `*`**: a provider served from cache gets `*` on its title (e.g. `CODEX*`).
- Fonts: PixelOperator 16px (titles/labels), Minecraftia 8px (timestamp/notes),
  VCR OSD 21px (DeepSeek balance). See `references/eink-design.md` for the full
  layout/tier spec.
- Progress bars show **REMAINING** (`100 − used`), never used — this was corrected
  twice on the device.

## Quote/0 API Push

See `references/quote0-api.md`. Key rules:
- Single IMAGE_API card → push **without** `taskKey`
- Dither `DIFFUSION` / `FLOYD_STEINBERG`, `border: 0`; all five image fields required
- `refreshNow: true` for immediate display; `false` for fixed-content scheduled slots
- **HTTP 404 is a business-logic error** when content isn't assigned to a device
  task — check the body's Chinese message, don't assume the device is missing.

## Quick Reference

```bash
python display.py --preview            # render PNG, no push
python display.py                      # push to device (needs .env)
python display.py --check              # self-check, no push
python display.py --debug-json         # print snapshot JSON
python display.py --layout 2+2         # force layout
python3 -m pytest                      # test suite
```

## Pitfalls

1. **Bar shows used instead of remaining.** Text AND bar must both reflect remaining
   (`100 − used_pct`).
2. **Equal bar widths.** Precompute max note width across all visible rows and pass a
   consistent `note_x` down all panels.
3. **Pixel font metrics.** Use `textbbox()` after any font change — pixel fonts have
   very different metrics from system fonts.
4. **Quote/0 404 "未找到图像 API 内容".** Delete and re-add the IMAGE_API card in
   Dot. App Content Studio.
5. **Dead providers don't error on screen.** A provider that fails auth/timeout is
   hidden; verify with `--debug-json` (a `status: no auth`/`HTTP 404` there is
   expected for a genuinely unconfigured provider, not a render bug).
6. **AGY is CLI-bound.** Don't "fix" AGY by switching to a REST endpoint — the API
   doesn't exist. Ensure the `agy` binary resolves (`~/.local/bin` must be on PATH
   or `AGY_CLI` set).

## Verification Checklist

- [ ] `python3 -m pytest` passes
- [ ] `python display.py --debug-json` shows every configured live provider `ok=True`
- [ ] `python display.py --preview` renders a clean 296×152 PNG
- [ ] Progress bars equal width, all show REMAINING
- [ ] No text overlap/clipping (`textbbox()`)
- [ ] `python display.py --check` passes critical sections
