#!/bin/bash
set -euo pipefail

export HOME="${HOME:-$(eval echo ~)}"
export USER="${USER:-$(id -un)}"
export LOGNAME="${LOGNAME:-$USER}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
cd "$(dirname "$0")"
source .env

if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="${PYTHON:-python3}"
fi

exec "$PYTHON_BIN" display.py
