"""
Render a 296×152 pure black/white PNG for Quote/0 e-ink display.

v0.8: matched Codex + Claude panels with shared row, bar, and icon sizing.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 296, 152
PAD = 10

FONT_PATH = "/System/Library/Fonts/Menlo.ttc"
PIXEL_FONT = Path(__file__).parent / "assets" / "fonts" / "Minecraftia-Regular.ttf"
OP_FONT    = Path(__file__).parent / "assets" / "fonts" / "PixelOperator.ttf"
LOGO_CODEX    = Image.open(Path(__file__).parent / "assets" / "logos" / "codex.png").convert("1")
LOGO_CLAUDE   = Image.open(Path(__file__).parent / "assets" / "logos" / "claude.png").convert("1")
LOGO_W = 16
LOGO_GAP = 4
LABEL_X = PAD + LOGO_W + LOGO_GAP  # text starts after logo + gap

BLACK = 0
WHITE = 255

# ── Font ─────────────────────────────────────────────────────────────────

def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)

_pixel_font_cache = None

def _pixel() -> ImageFont.FreeTypeFont:
    global _pixel_font_cache
    if _pixel_font_cache is None:
        _pixel_font_cache = ImageFont.truetype(str(PIXEL_FONT), 8)
    return _pixel_font_cache

_op_font_cache = None

def _op() -> ImageFont.FreeTypeFont:
    global _op_font_cache
    if _op_font_cache is None:
        _op_font_cache = ImageFont.truetype(str(OP_FONT), 16)
    return _op_font_cache

def _tsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# ── v0.8 E-Ink Dashboard (zellux-style) ──────────────────────────────────
# Matched dual-row panels: label + inline bar(dots) + remaining% + reset time

def _bar_dots(draw, x, y, w, h, used_pct):
    """Zellux-style bar: outline + filled portion + dot grid in empty area."""
    used_pct = max(0, min(100, used_pct or 0))
    draw.rectangle([x, y, x + w - 1, y + h - 1], outline=BLACK)
    filled = int((w - 2) * used_pct / 100)
    if filled > 0:
        draw.rectangle([x + 1, y + 1, x + filled, y + h - 2], fill=BLACK)
    # Dot grid in empty area (4px spacing)
    dot_spacing = 4
    empty_x0 = x + 1 + filled
    margin = dot_spacing // 2
    for dy in range(y + 1 + margin, y + h - 1 - margin + 1, dot_spacing):
        for dx in range(x + 1 + margin, x + w - 1 - margin + 1, dot_spacing):
            if dx >= empty_x0:
                draw.point((dx, dy), fill=BLACK)


PANEL_Y = 12
PANEL_HEADER_H = 18
PANEL_ROW_H = 18
PANEL_H = PANEL_HEADER_H + PANEL_ROW_H * 2
DIVIDER_GAP_TOP = 8
DIVIDER_GAP_BOTTOM = 10
BAR_H = 10
LABEL_W = 36


def _draw_usage_row(
    draw,
    y,
    label_text,
    used_pct,
    reset_str,
    note_font,
    row_label_font,
    note_x=None,
    row_h=PANEL_ROW_H,
    bar_h=BAR_H,
    label_w=LABEL_W,
):
    """Draw one usage row: label + bar(dots) + remaining% + reset."""
    bar_y = y + (row_h - bar_h) // 2

    # Label (e.g. "5h", "Week")
    _, lh = _tsize(draw, label_text, row_label_font)
    draw.text((PAD, bar_y + (bar_h - lh) // 2), label_text, font=row_label_font, fill=BLACK)

    # Right text: remaining% + reset
    remaining = 100 - used_pct if used_pct is not None else 0
    note = f"{remaining:.0f}%  {reset_str}" if reset_str and reset_str != "?" else f"{remaining:.0f}%"
    nw, nh = _tsize(draw, note, note_font)
    if note_x is None:
        note_x = W - PAD - nw
    draw.text((note_x, bar_y + (bar_h - nh) // 2), note, font=note_font, fill=BLACK)

    # Bar (filled = REMAINING)
    bar_x = PAD + label_w
    bar_w = note_x - 4 - bar_x
    if used_pct is not None and bar_w > 6:
        _bar_dots(draw, bar_x, bar_y, bar_w, bar_h, 100 - used_pct)
    return y + row_h


def _usage_note(draw, used, reset, font):
    remaining = 100 - used if used is not None else 0
    note = f"{remaining:.0f}%  {reset}" if reset and reset != "?" else f"{remaining:.0f}%"
    nw, _ = _tsize(draw, note, font)
    return note, nw


def _window_rows(sn: dict):
    return [
        (
            sn.get("short_label", "?"),
            sn.get("short_used_percent"),
            sn.get("short_reset", "?"),
        ),
        (
            sn.get("long_label", "?"),
            sn.get("long_used_percent"),
            sn.get("long_reset", "?"),
        ),
    ]


def _render_v5(img: Image.Image, draw: ImageDraw.ImageDraw, snap: dict):
    cx = snap.get("codex", {})
    cl = snap.get("claude", {})
    ts  = snap.get("updated_at", datetime.now().strftime("%H:%M"))

    label = _op()       # 16px PixelOperator — section labels, row text
    small = _pixel()    # 8px Minecraftia — timestamp

    def _logo(logo_img, y):
        """Paste a 16×16 logo at (PAD, y), blending B&W onto the image."""
        for dy in range(LOGO_W):
            for dx in range(LOGO_W):
                if logo_img.getpixel((dx, dy)) == 0:
                    img.putpixel((PAD + dx, y + dy), BLACK)

    def _draw_panel(y, logo_img, title, sn, note_x):
        _logo(logo_img, y)
        draw.text((LABEL_X, y), title, font=label, fill=BLACK)
        row_y = y + PANEL_HEADER_H

        if sn.get("ok"):
            rows = _window_rows(sn)
            row_y = _draw_usage_row(
                draw, row_y, rows[0][0], rows[0][1], rows[0][2],
                small, label, note_x, row_h=PANEL_ROW_H, bar_h=BAR_H)
            _draw_usage_row(
                draw, row_y, rows[1][0], rows[1][1], rows[1][2],
                small, label, note_x, row_h=PANEL_ROW_H, bar_h=BAR_H)
        else:
            status = sn.get("raw_status", "error")
            draw.text((LABEL_X, row_y), status, font=label, fill=BLACK)

        return y + PANEL_H

    note_widths = []
    for sn in (cx, cl):
        if not sn.get("ok"):
            continue
        for _, used, reset in _window_rows(sn):
            _, nw = _usage_note(draw, used, reset, small)
            note_widths.append(nw)
    note_x = W - PAD - max(note_widths or [0])

    # ── Timestamp ──────────────────────────────────────────────────────
    tsw, _ = _tsize(draw, ts, small)
    draw.text((W - PAD - tsw, PANEL_Y), ts, font=small, fill=BLACK)

    # ── CODEX ──────────────────────────────────────────────────────────
    y = _draw_panel(PANEL_Y, LOGO_CODEX, "CODEX", cx, note_x)

    # ── Divider (zellux-style: 6px dash / 4px gap) ─────────────────────
    y += DIVIDER_GAP_TOP
    dash_len, gap_len = 6, 4
    x = 0
    while x < W:
        draw.line([(x, y), (min(x + dash_len - 1, W), y)], fill=BLACK, width=1)
        x += dash_len + gap_len
    y += DIVIDER_GAP_BOTTOM

    # ── CLAUDE ──────────────────────────────────────────────────────────
    _draw_panel(y, LOGO_CLAUDE, "CLAUDE", cl, note_x)


# ── Legacy ────────────────────────────────────────────────────────────────

def _render_legacy(draw, codex_text, claude_text):
    tf, bf, sf = _font(16), _font(18), _font(12)
    title = "AI Usage"
    tw, th = _tsize(draw, title, tf)
    draw.text(((W - tw) // 2, PAD), title, font=tf, fill=BLACK)
    lw, lh = _tsize(draw, "Codex:", bf)
    y1 = PAD + th + 18
    draw.text((PAD, y1), "Codex:", font=bf, fill=BLACK)
    draw.text((PAD + lw + 12, y1), codex_text, font=bf, fill=BLACK)
    lw2, lh2 = _tsize(draw, "Claude:", bf)
    y2 = y1 + lh + 14
    draw.text((PAD, y2), "Claude:", font=bf, fill=BLACK)
    draw.text((PAD + lw2 + 12, y2), claude_text, font=bf, fill=BLACK)
    dy = y2 + lh2 + 16
    draw.rectangle([PAD, dy, W - PAD, dy + 1], fill=BLACK)
    now = datetime.now().strftime("%H:%M")
    tsw, _ = _tsize(draw, now, sf)
    draw.text((W - PAD - tsw, dy + 8), now, font=sf, fill=BLACK)


# ── API ───────────────────────────────────────────────────────────────────

def render_image(arg, claude_text=None):
    img = Image.new("L", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    if isinstance(arg, dict):
        _render_v5(img, draw, arg)
    else:
        _render_legacy(draw, arg, claude_text or "?")
    img = img.convert("1", dither=Image.Dither.NONE)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    snap = {
        "codex": {"ok": True, "short_label": "5h", "short_used_percent": 72,
                  "short_reset": "2h13m", "long_label": "Week",
                  "long_used_percent": 41, "long_reset": "123h3m",
                  "status": "ok"},
        "claude": {"ok": True, "short_label": "5h", "short_used_percent": 42,
                   "short_reset": "2h13m", "long_label": "Week",
                   "long_used_percent": 61, "long_reset": "3d4h",
                   "status": "ok"},
        "updated_at": "16:40",
    }
    png = render_image(snap)
    out = Path(__file__).parent / "test_render.png"
    out.write_bytes(png)
    print(f"Saved {out} ({len(png)} bytes)")
