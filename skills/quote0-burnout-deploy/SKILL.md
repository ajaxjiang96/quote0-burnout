---
name: quote0-burnout-deploy
description: Ship latest main to the Quote/0 device via launchd.
version: 1.0.0
author: Jiacheng Jiang (ajaxjiang96), Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [quote0, e-ink, deploy, launchd]
    related_skills: [quote0-burnout-develop]
---

# Quote/0 Burnout Dashboard — Deployment

Ship the current `main` to a real Quote/0 device through a launchd job. **This
skill is for releasing**, not for editing code (that's `quote0-burnout-develop`).

Deployment runs `display.py` every 5 minutes from a **separate deploy worktree**
pinned to a release commit. Dev edits live in the main checkout; the device never
runs the dev checkout, so half-finished work can't hit the screen. Concrete paths
differ per machine — set the variables below for yours, then follow the procedure.

## Per-machine variables (configure once, adjust to your environment)

The commands below use these placeholders. Replace them with your own values (or
export them in your shell):

| Variable | Meaning | Example |
|----------|---------|---------|
| `$DEPLOY_DIR` | Deploy worktree path (a checkout separate from your dev tree) | `$HOME/Projects/quote0-burnout-deploy` |
| `$DEV_DIR` | Your dev checkout (source of `.env` / `.venv` symlinks) | `$HOME/Projects/quote0-burnout` |
| `$LABEL` | launchd job label | `com.example.quote0-burnout` |
| `$PLIST` | launchd plist path | `$HOME/Library/LaunchAgents/$LABEL.plist` |
| `$AGY_CLI` | Path to the `agy` CLI (if not on PATH) | `$HOME/.local/bin/agy` |

No secrets or account IDs live in this repo — set only machine-local paths.

## Prerequisites

- `git`, `gh` on PATH
- A `.env` with your Quote/0 key, device id, and provider keys — **symlinked**, not copied
- A `.venv` with `requests` + `Pillow` — **symlinked**
- `agy` CLI on PATH (or `$AGY_CLI`) for the AGY provider
- The launchd job registered (`$PLIST`, label `$LABEL`)

## Deploy worktree (one-time setup)

```bash
# Detached worktree so `main` can also be checked out elsewhere without conflict
git worktree add --detach "$DEPLOY_DIR" main
ln -sfn "$DEV_DIR/.env"  "$DEPLOY_DIR/.env"
ln -sfn "$DEV_DIR/.venv" "$DEPLOY_DIR/.venv"
```

Verify isolation: `git -C "$DEPLOY_DIR" rev-parse --show-toplevel` must return its
own path, not the dev checkout.

## Release procedure

1. **Fetch + pin the deploy worktree to latest main** (it's detached and does NOT
   auto-advance):
   ```bash
   git -C "$DEPLOY_DIR" fetch origin main
   git -C "$DEPLOY_DIR" checkout --detach origin/main
   ```

2. **Force a run now** (don't wait for the 5-min calendar tick):
   ```bash
   launchctl kickstart gui/$(id -u)/"$LABEL"
   ```

3. **Verify** — read the job's log for a successful push:
   ```bash
   tail "$LOG"   # $LOG = the log path in your plist, e.g. /tmp/quote0-burnout.log
   ```
   A successful push returns `"设备 <device> 图片 API 内容已切换。"` (your device id).
   Also confirm the snapshot is healthy from the deploy dir:
   ```bash
   cd "$DEPLOY_DIR" && set -a && source .env && set +a
   .venv/bin/python display.py --debug-json
   ```
   Healthy when a configured live provider reports `ok=True` (e.g. `agy ok=True,
   short=5h, ... [ok]`). Note: you must `source .env` — without it DeepSeek and
   OpenCode report `no key`.

## launchd lifecycle (macOS)

```bash
# Register (modern bootstrap) — ERRORS "5: Input/output error" if the job is DISABLED:
launchctl enable gui/$(id -u)/"$LABEL"    # must be enabled first
launchctl bootstrap gui/$(id -u) "$PLIST"

# Force run now (after any release):
launchctl kickstart gui/$(id -u)/"$LABEL"

# Remove:
launchctl bootout gui/$(id -u)/"$LABEL"
```

- The plist uses `StartCalendarInterval` (every 5 min), NOT `StartInterval`
  (unreliable on macOS). `Program` points at `$DEPLOY_DIR/run.sh`,
  `WorkingDirectory` at `$DEPLOY_DIR`.
- `run.sh` must `source .env` and export `$HOME/.local/bin` (for the `agy` CLI)
  and `/opt/homebrew/bin` (homebrew tools) on PATH. Without that, AGY and DeepSeek
  fail silently.
- `RunAtLoad` won't re-fire on a `load`→`unload` cycle if the plist didn't change —
  use `kickstart`.

## Pitfalls

- **The deploy worktree doesn't advance by itself.** It's detached+pinned. Always
  `git -C "$DEPLOY_DIR" checkout --detach origin/main` before kicking.
- **Bootstrap fails "5: Input/output error"** → the job is disabled. `launchctl
  enable` first, then bootstrap.
- **`launchctl list` shows `state = not running`** is normal between calendar ticks
  (it ran and exited, waiting for the next interval), not a failure.
- **Manual `display.py --debug-json` without `source .env`** shows `no key` for
  DeepSeek/OpenCode — a test artifact, not a real failure. `run.sh` sources `.env`.

## Verification Checklist

- [ ] `git -C "$DEPLOY_DIR" rev-parse --short HEAD` == the commit you want released
- [ ] `launchctl kickstart ...` returns 0
- [ ] The job log shows `图片 API 内容已切换` (or `已更新`) for your device
- [ ] `display.py --debug-json` shows all live providers `ok=True` (AGY included)
- [ ] `display.py --preview` renders the expected layout with the new panel(s)
