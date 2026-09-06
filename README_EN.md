# quote0-burnout

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Hardware](https://img.shields.io/badge/Hardware-MindReset%20Quote%2F0-FF6B00.svg)](https://mindreset.tech/)
[![Display](https://img.shields.io/badge/Display-296%C3%97152%201--bit%20E--Ink-000000.svg)](docs/layouts.md)
[![Tests](https://img.shields.io/badge/Tests-98%20passed-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![LLM Context](https://img.shields.io/badge/LLMs.txt-Standard-purple.svg)](llms.txt)

AI usage & rate-limit dashboard for MindReset Quote/0 e-ink display — OpenAI Codex + Claude Code + Google Antigravity (AGY) + DeepSeek + OpenCode Go, rendered at 296×152 in pure 1-bit B&W and pushed directly to the device.

[中文](README.md) · [LLMs.txt](llms.txt) · [Full Layout Spec](docs/layouts.md)

![Device photo](docs/preview.jpg)

## Layouts

`auto` (default) fits the number of working providers; `--layout` / `LAYOUT` pins one:

| `stack` full-width stack | `1+1` two halves | `1+2` half + 2 quarters | `2+2` four cells |
|---|---|---|---|
| ![stack](docs/images/layout-stack.png) | ![1+1](docs/images/layout-1x1.png) | ![1+2](docs/images/layout-1x2.png) | ![2+2](docs/images/layout-2x2.png) |

> Full spec — cell contracts, seams, fonts, panel ordering, the cached `*` marker — in [docs/layouts.md](docs/layouts.md).

## Features

- **Google AGY (Antigravity)**: 5h and weekly quota usage fetched via `agy --print /quota`, automatic remaining% conversion, reset countdowns, and official 16×16 bitmap arch logo
- **OpenAI Codex / Claude Code**: matched dual-row panels (5h / Week) with dot-grid bars, remaining% + reset countdown, plus Codex manual reset credits & expiry
- **DeepSeek**: hero balance (VCR 21px) + peak/off-peak billing tier (PEAK/OFF, official rate card 2026-08; off-peak = 50% discount) + countdown to the next tier switch
- **OpenCode Go**: Zen "Go" subscription usage (5h / Wk / Mo)
- **Dynamic Auto-Layout**: automatically selects `stack`, `1+1`, `1+2`, or `2+2` based on the count of active live providers
- **Recency-Based Ordering**: the provider whose data changed most recently gets the most prominent slot; unauthenticated or dead providers are silently hidden
- **Fail-Safe Cache Fallback**: when an upstream provider API experiences downtime, the last valid snapshot is displayed, tagged `*` in the title (e.g. `16:40*`)
- **Pixel-Perfect Typography**: PixelOperator 16px / Minecraftia 8px / VCR OSD 21px, rendered strictly at native bitmap sizes with zero anti-aliasing blur
- **Flexible Execution Modes**: supports single-shot push, local preview (`--preview`), self-scheduling loop (`--interval 5m`), macOS launchd daemon, and Docker deployment

## Install

```bash
pip install -r requirements.txt
# codex CLI for one-time auth: codex
```

## Configure

```bash
cp config.example.env .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `QUOTE0_API_KEY` | ✓ | Quote/0 API key |
| `QUOTE0_DEVICE_ID` | ✓ | Device ID |
| `CODEX_ACCESS_TOKEN` | | Override Codex token (default: `~/.codex/auth.json`) |
| `CLAUDE_ACCESS_TOKEN` | | Override Claude token (default: `~/.claude/.credentials.json` or macOS Keychain; fallback: `claude /usage`) |
| `DEEPSEEK_API_KEY` | | DeepSeek balance + rate card (`DEEPSEEK_MODEL` picks the pricing model) |
| `OPENCODE_GO_API_KEY` | | OpenCode Zen usage API |
| `AGY_API_KEY` | | Google AGY (Antigravity) quota API key (auto-discovers local `~/.gemini/antigravity-cli/`) |
| `LAYOUT` | | `auto` (default) / `stack` / `1+1` / `1+2` / `2+2` |
| `REFRESH_INTERVAL` | | self-scheduling loop interval (e.g. `60`, `5m`, `1h`; min 60s) |

## Usage

```bash
python display.py --preview    # local preview PNG (no push)
python display.py              # push to device
python display.py --interval 5m # self-scheduling loop (pushes every 5m, min 60s)
python display.py --layout 2+2 # pin a layout (overrides LAYOUT env)
python display.py --text       # Text API
python display.py --debug-json # print snapshot JSON
python display.py --check      # self-check
python display.py --list-tasks # list task slots
```

## Scheduling (macOS launchd, every 5 min)

```bash
cp scripts/com.example.quote0-burnout.plist.example ~/Library/LaunchAgents/
# Edit the Label / Program / log paths in the plist, then:
launchctl load ~/Library/LaunchAgents/com.example.quote0-burnout.plist
```

## Frequently Asked Questions (FAQ)

### Q: Which AI providers are supported?
`quote0-burnout` natively integrates with 5 major platforms:
1. **OpenAI Codex** (direct OAuth API / Codex CLI)
2. **Claude Code** (Anthropic Claude Code OAuth / `claude /usage` CLI fallback)
3. **Google Antigravity** (`agy` CLI slash command)
4. **DeepSeek** (official platform balance and dynamic rate card)
5. **OpenCode** (Zen "Go" subscription windows)

### Q: Why pure 1-bit monochrome without grayscale anti-aliasing?
The MindReset Quote/0 utilizes a 296×152 electronic paper display. Grayscale dithering introduces artifacts, ghosting, and blurry character edges at small sizes. By enforcing native pixel-font rendering (PixelOperator 16px, Minecraftia 8px, VCR 21px) with 1-bit dot rasterization, every character and progress bar remains ultra-sharp with maximum contrast.

### Q: What happens if an API token expires or an upstream service times out?
The system employs **failure isolation and silent omission**: unconfigured or failed providers are hidden from view, and the screen automatically reflows into the optimal geometry for the remaining healthy providers (e.g. 1+2 automatically reflows to 1+1). For transient network drops, cached data is served with a `*` marker instead of displaying error screens.

### Q: How do I run it automatically in the background?
- **macOS**: Load the `launchd` plist (executes `run.sh` every 5 minutes).
- **In-process daemon**: Run `python display.py --interval 5m` (includes a 60-second safety floor).
- **Docker**: Deploy with the provided `Dockerfile` and `docker-compose.yml`.

## Troubleshooting

- **Codex / Claude "no auth"** — run `codex` / `claude` to re-authenticate
- **Push 404** — delete and re-add the IMAGE_API card in Dot. App Content Studio
- **Schedule not updating** — `launchctl kickstart gui/$(id -u)/com.example.quote0-burnout`

## Development & Contributing

- Contributing Guide & Provider Contract: [CONTRIBUTING.md](CONTRIBUTING.md)
- `providers/`: provider implementations (fetch → snapshot → text)
- `render.py`: layout engine + rendering; `scripts/render_layout_gallery.py` regenerates preview images
- Testing: `python3 -m pytest`
- Pixel-level design spec: [skills/quote0-burnout-develop/references/eink-design.md](skills/quote0-burnout-develop/references/eink-design.md)

### Bundled Agent Skills

This repo ships two Hermes-compatible skills for an agent (e.g. Hermes Agent) to load in the matching scenario:

- [skills/quote0-burnout-develop/SKILL.md](skills/quote0-burnout-develop/SKILL.md) — **development**: architecture, provider contract (incl. AGY `--print /quota`), layout/rendering, pitfalls, verification. Load when changing code.
- [skills/quote0-burnout-deploy/SKILL.md](skills/quote0-burnout-deploy/SKILL.md) — **deployment**: deploy worktree, launchd kickstart, verifying the device. Load when publishing a release.

### Deploy via Agent

The device is driven by a launchd job that fetches and pushes periodically from a **dedicated deploy worktree** (separate from the dev checkout). To push latest `main`, have the agent load [skills/quote0-burnout-deploy/SKILL.md](skills/quote0-burnout-deploy/SKILL.md) and follow its "Release procedure": point the deploy worktree at latest `origin/main`, fire one `launchctl kickstart`, then confirm the device reports "内容已切换".

Worktree paths, launchd label, etc. are per-machine (the skill uses placeholders). This repo carries no server paths or personal device identifiers.
