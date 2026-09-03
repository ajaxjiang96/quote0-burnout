# quote0-burnout

AI usage dashboard for MindReset Quote/0 e-ink display — OpenAI Codex + Claude.

[中文](README.md)

![Device photo](docs/preview.jpg)
![Example render](docs/example.png)

## Layout

```
                        16:40
◆ CODEX
5h  [████████████░░░░░] 89%  4h41m
Week [████████████░░░░░░] 69%  5d23h
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
◆ CLAUDE
5h  [████████████░░░░░] 42%  2h13m
Week [████████░░░░░░░░] 61%  3d4h
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
◆ DEEPSEEK   $18.42        OFF $0.22 1h50m
```

- **Codex / Claude**: matched-size dual-row panels (5h / Week) with inline dot-grid bars. Shows remaining% + reset countdown.
- **DeepSeek**: compact one-line panel — balance + current peak/off-peak billing tier (PEAK/OFF) with countdown to the next tier switch. Official rate card (2026-08); off-peak = 50% of peak.
- **Icons**: Codex and Claude both use 16×16 monochrome PNGs; Claude is an e-ink binary version of the Claude symbol.
- **Fonts**: PixelOperator 16px / Minecraftia 8px.
- Codex data via direct OAuth API — **no CLI dependency**.
- Claude data follows CodexBar's Claude Code OAuth usage API. Tokens are read from env, `~/.claude/.credentials.json`, or macOS Keychain, with `claude /usage` as a fallback.

> Full design spec, API reference, and rendering details in [`skill/`](skill/).

## Install

```bash
pip install -r requirements.txt
codex   # one-time authentication
```

## Configure

```bash
cp config.example.env .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `QUOTE0_API_KEY` | ✓ | Quote/0 API key |
| `QUOTE0_DEVICE_ID` | ✓ | Device ID |
| `CODEX_ACCESS_TOKEN` | | Override Codex token (default: ~/.codex/auth.json) |
| `CLAUDE_ACCESS_TOKEN` | | Override Claude token (default: ~/.claude/.credentials.json or macOS Keychain; fallback: `claude /usage`) |

## Usage

```bash
python display.py --preview   # local preview
python display.py             # push to device
python display.py --check     # self-check
```

## Scheduling (macOS launchd)

```bash
cp scripts/com.ajax.quote0-burnout.plist.example ~/Library/LaunchAgents/
# edit the Program path, then:
launchctl load ~/Library/LaunchAgents/com.ajax.quote0-burnout.plist
```

Runs every 5 minutes.

## Troubleshooting

```bash
python display.py --check
```

- **Codex "no auth"** — run `codex` to re-authenticate
- **Claude "no auth"** — run `claude` to re-authenticate, confirm macOS Keychain access, or set `CLAUDE_ACCESS_TOKEN`
- **Push 404** — delete and re-add the IMAGE_API card in Dot. App Content Studio
- **Schedule not updating** — `launchctl kickstart gui/$(id -u)/com.ajax.quote0-burnout`

## Skill

This repo includes [skill/SKILL.md](skill/SKILL.md) following the [Vercel Skills](https://github.com/nousresearch/hermes-agent) standard. Drop it into your Hermes Agent skills directory for AI-assisted dashboard development.
