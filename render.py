"""
Render a 296×152 pure black/white PNG for Quote/0 e-ink display.

v0.6: zellux-style dual-row Codex. Logo icons + aligned layout.
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
VCR_FONT   = Path(__file__).parent / "assets" / "fonts" / "VCR_OSD_MONO_1.001.ttf"
LOGO_CODEX    = Image.open(Path(__file__).parent / "assets" / "logos" / "codex.png").convert("1")
LOGO_DEEPSEEK = Image.open(Path(__file__).parent / "assets" / "logos" / "deepseek.png").convert("1")
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

_vcr_font_cache = None

def _vcr() -> ImageFont.FreeTypeFont:
    global _vcr_font_cache
    if _vcr_font_cache is None:
        _vcr_font_cache = ImageFont.truetype(str(VCR_FONT), 21)
    return _vcr_font_cache


def _tsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# ── v0.6 E-Ink Dashboard (zellux-style) ──────────────────────────────────
# Dual-row Codex: label + inline bar(dots) + remaining% + reset time

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


ROW_H = 22
BAR_H = 14
LABEL_W = 36


def _draw_codex_row(draw, y, label_text, used_pct, reset_str, note_font, row_label_font, note_x=None):
    """Draw one Codex row: label + bar(dots) + remaining% + reset."""
    bar_y = y + (ROW_H - BAR_H) // 2

    # Label (e.g. "5h", "Week")
    lh = row_label_font.size
    draw.text((PAD, bar_y + (BAR_H - lh) // 2), label_text, font=row_label_font, fill=BLACK)

    # Right text: remaining% + reset
    remaining = 100 - used_pct if used_pct is not None else 0
    note = f"{remaining:.0f}%  {reset_str}" if reset_str and reset_str != "?" else f"{remaining:.0f}%"
    nw, nh = _tsize(draw, note, note_font)
    if note_x is None:
        note_x = W - PAD - nw
    draw.text((note_x, bar_y + (BAR_H - nh) // 2), note, font=note_font, fill=BLACK)

    # Bar (filled = REMAINING)
    bar_x = PAD + LABEL_W
    bar_w = note_x - 4 - bar_x
    if used_pct is not None:
        _bar_dots(draw, bar_x, bar_y, bar_w, BAR_H, 100 - used_pct)
    return y + ROW_H


def _render_v5(img: Image.Image, draw: ImageDraw.ImageDraw, snap: dict):
    cx = snap.get("codex", {})
    ds = snap.get("deepseek", {})
    ts  = snap.get("updated_at", datetime.now().strftime("%H:%M"))

    label = _op()       # 16px PixelOperator — section labels, row text
    bal   = _vcr()      # 21px VCR OSD Mono — deepseek balance
    small = _pixel()    # 8px Minecraftia — timestamp

    def _logo(logo_img, y):
        """Paste a 12×12 logo at (PAD, y), blending B&W onto the image."""
        for dy in range(LOGO_W):
            for dx in range(LOGO_W):
                if logo_img.getpixel((dx, dy)) == 0:
                    img.putpixel((PAD + dx, y + dy), BLACK)

    # ── Timestamp ──────────────────────────────────────────────────────
    tsw, _ = _tsize(draw, ts, small)
    draw.text((W - PAD - tsw, 14), ts, font=small, fill=BLACK)

    # ── CODEX ──────────────────────────────────────────────────────────
    y = 14

    if cx.get("ok"):
        short_label = cx.get("short_label", "?")
        short_used  = cx.get("short_used_percent")
        short_reset = cx.get("short_reset", "?")
        long_label  = cx.get("long_label", "?")
        long_used   = cx.get("long_used_percent")
        long_reset  = cx.get("long_reset", "?")

        # Logo + section label
        _logo(LOGO_CODEX, y)
        draw.text((LABEL_X, y), "CODEX", font=label, fill=BLACK)
        y += 20

        # Pre-compute max note width so both bars are equal width
        def _note(used, reset):
            r = 100 - used if used is not None else 0
            return f"{r:.0f}%  {reset}" if reset and reset != "?" else f"{r:.0f}%"
        n1 = _note(short_used, short_reset)
        n2 = _note(long_used, long_reset)
        nw1, _ = _tsize(draw, n1, label)
        nw2, _ = _tsize(draw, n2, label)
        note_x = W - PAD - max(nw1, nw2)

        # Row 1: 5h + bar(dots) + remaining% + reset
        y = _draw_codex_row(draw, y, short_label, short_used, short_reset, label, label, note_x)

        # Row 2: Week + bar(dots) + remaining% + reset (skip if no secondary window)
        if long_used is not None and long_label:
            y = _draw_codex_row(draw, y, long_label, long_used, long_reset, label, label, note_x)
    else:
        _logo(LOGO_CODEX, y)
        draw.text((LABEL_X, y), "CODEX", font=label, fill=BLACK)
        status = cx.get("raw_status", "error")
        y += 18
        draw.text((LABEL_X, y), status, font=label, fill=BLACK)
        _, eh = _tsize(draw, status, label)
        y += eh + 6

    # ── Divider (zellux-style: 6px dash / 4px gap) ─────────────────────
    y += 10
    dash_len, gap_len = 6, 4
    x = 0
    while x < W:
        draw.line([(x, y), (min(x + dash_len - 1, W), y)], fill=BLACK, width=1)
        x += dash_len + gap_len
    y += 12

    # ── DEEPSEEK ────────────────────────────────────────────────────────
    _logo(LOGO_DEEPSEEK, y)
    draw.text((LABEL_X, y), "DEEPSEEK", font=label, fill=BLACK)
    y += 18

    if ds.get("ok"):
        bal_val = ds.get("balance")
        sym = ds.get("symbol", "$")
        bal_text = f"{sym}{bal_val:.2f}" if bal_val is not None else "?"

        draw.text((LABEL_X, y), bal_text, font=bal, fill=BLACK)
        _, bh = _tsize(draw, bal_text, bal)

        # Status badge — aligned to balance baseline
        status = ds.get("status", "ok").upper()
        sw, sh = _tsize(draw, status, label)
        draw.text((W - PAD - sw, y + bh - sh), status, font=label, fill=BLACK)
    else:
        status = ds.get("raw_status", "error")
        draw.text((LABEL_X, y), status, font=label, fill=BLACK)


# ── Legacy ────────────────────────────────────────────────────────────────

def _render_legacy(draw, codex_text, deepseek_text):
    tf, bf, sf = _font(16), _font(18), _font(12)
    title = "AI Usage"
    tw, th = _tsize(draw, title, tf)
    draw.text(((W - tw) // 2, PAD), title, font=tf, fill=BLACK)
    lw, lh = _tsize(draw, "Codex:", bf)
    y1 = PAD + th + 18
    draw.text((PAD, y1), "Codex:", font=bf, fill=BLACK)
    draw.text((PAD + lw + 12, y1), codex_text, font=bf, fill=BLACK)
    lw2, lh2 = _tsize(draw, "DeepSeek:", bf)
    y2 = y1 + lh + 14
    draw.text((PAD, y2), "DeepSeek:", font=bf, fill=BLACK)
    draw.text((PAD + lw2 + 12, y2), deepseek_text, font=bf, fill=BLACK)
    dy = y2 + lh2 + 16
    draw.rectangle([PAD, dy, W - PAD, dy + 1], fill=BLACK)
    now = datetime.now().strftime("%H:%M")
    tsw, _ = _tsize(draw, now, sf)
    draw.text((W - PAD - tsw, dy + 8), now, font=sf, fill=BLACK)


# ── API ───────────────────────────────────────────────────────────────────

def render_image(arg, deepseek_text=None):
    img = Image.new("L", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    if isinstance(arg, dict):
        _render_v5(img, draw, arg)
    else:
        _render_legacy(draw, arg, deepseek_text or "?")
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
        "deepseek": {"ok": True, "balance": 18.42, "currency": "USD",
                      "symbol": "$", "status": "ok"},
        "updated_at": "16:40",
    }
    png = render_image(snap)
    out = Path(__file__).parent / "test_render.png"
    out.write_bytes(png)
    print(f"Saved {out} ({len(png)} bytes)")
