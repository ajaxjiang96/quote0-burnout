#!/usr/bin/env python3
"""Regenerate the layout gallery images in docs/images/.

Each image is a real render_image() output on representative mock data —
the same 296×152, 1-bit PNGs the Quote/0 device displays. Run from the
repo root:  .venv/bin/python scripts/render_layout_gallery.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render import render_image

OUT = Path(__file__).resolve().parent / ".." / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

TS = "16:40"


def _usage(short_lbl, short_used, short_reset, long_lbl="Week", long_used=None, long_reset=None):
    return {
        "ok": True,
        "short_label": short_lbl, "short_used_percent": short_used, "short_reset": short_reset,
        "long_label": long_lbl, "long_used_percent": long_used, "long_reset": long_reset,
        "status": "ok",
    }


def _codex():
    return _usage("5h", 11, "4h41m", "Week", 31, "5d23h")


def _claude():
    return _usage("5h", 58, "2h13m", "Week", 39, "3d4h")


def _deepseek():
    return {
        "ok": True,
        "balance": 18.42, "symbol": "¥",
        "window": "OFF", "price_in": 1.5, "price_out": 4.5,
        "next_window": "PEAK", "countdown": "1h50m",
        "status": "ok",
    }


def _opencode():
    return {
        "ok": True,
        "rolling": {"used_percent": 6, "reset": "2h"},
        "weekly": {"used_percent": 33, "reset": "3d"},
        "monthly": {"used_percent": 46, "reset": "12d"},
        "status": "ok",
    }


def _snap(layout, providers, cached=False):
    s = {
        "codex": _codex(), "claude": _claude(),
        "deepseek": _deepseek(), "opencode": _opencode(),
    }
    for name in ("codex", "claude", "deepseek", "opencode"):
        s[name] = s[name] if name in providers else {"ok": False, "status": "error", "raw_status": "dead"}
    s.update({
        "second_panel": "opencode",
        "layout": layout,
        "configured": list(providers),
        "updated_at": "16:40 (cached)" if cached else TS,
        "_cached": cached,
    })
    return s


SHOTS = [
    ("layout-2x2", _snap("2+2", ("codex", "claude", "deepseek", "opencode"))),
    ("layout-1x2", _snap("1+2", ("codex", "claude", "deepseek", "opencode"))),
    ("layout-1x1", _snap("1+1", ("codex", "claude"))),
    ("layout-stack", _snap("stack", ("codex", "claude", "deepseek", "opencode"))),
    ("layout-2x2-cached", _snap("2+2", ("codex", "claude", "deepseek", "opencode"), cached=True)),
]

for stem, snap in SHOTS:
    with open(OUT / f"{stem}.png", "wb") as f:
        f.write(render_image(snap))
    print(f"wrote {OUT / (stem + '.png')}")
