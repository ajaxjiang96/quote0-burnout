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


_op14_font = None

def _op14() -> ImageFont.FreeTypeFont:
    global _op14_font
    if _op14_font is None:
        _op14_font = ImageFont.truetype(str(OP_FONT), 14)
    return _op14_font


def _render_v5(img: Image.Image, draw: ImageDraw.ImageDraw, snap: dict):
    cx = snap.get("codex", {})
    ds = snap.get("deepseek", {})
    ts = snap.get("updated_at", datetime.now().strftime("%H:%M"))

    big = _vcr()          # 21px VCR — CODEX, labels, percentages
    mid = _op()           # 16px OP — general text
    small = _op14()       # 14px OP — countdown text
    time_font = ImageFont.truetype(str(OP_FONT), 18)  # 18px OP — timestamp

    LOGO_S = 20
    logo_big = LOGO_CODEX.resize((LOGO_S, LOGO_S), Image.NEAREST)

    def _logo_draw(logo_img, x, y):
        for dy in range(LOGO_S):
            for dx in range(LOGO_S):
                if logo_img.getpixel((dx, dy)) == 0:
                    img.putpixel((x + dx, y + dy), BLACK)

    def _divider(cy):
        x, gap = 0, 4
        while x < W:
            draw.line([(x, cy), (min(x + 5, W), cy)], fill=BLACK)
            x += 5 + gap

    def _bar(dx, dy, dw, dh, pct):
        pct = max(0, min(100, pct or 0))
        draw.rectangle([dx, dy, dx + dw - 1, dy + dh - 1], outline=BLACK)
        fill = int((dw - 2) * pct / 100)
        if fill > 0:
            draw.rectangle([dx + 1, dy + 1, dx + fill, dy + dh - 2], fill=BLACK)
        sp = 2
        sx = dx + 1 + fill
        for ry in range(dy + 1 + sp, dy + dh - 1 - sp + 1, 4):
            for rx in range(dx + 1 + sp, dx + dw - 1 - sp + 1, 4):
                if rx >= sx:
                    draw.point((rx, ry), fill=BLACK)

    # ── Header ──────────────────────────────────────────────────────────
    _logo_draw(logo_big, PAD, 12)
    draw.text((PAD + LOGO_S + 6, 14), "CODEX", font=big, fill=BLACK)
    tsw, _ = _tsize(draw, ts, time_font)
    draw.text((W - PAD - tsw, 14), ts, font=time_font, fill=BLACK)
    if snap.get("_cached"):
        cw, _ = _tsize(draw, "cache", small)
        draw.text((W - PAD - cw, 36), "cache", font=small, fill=BLACK)

    # ── Divider ─────────────────────────────────────────────────────────
    _divider(44)

    # ── Codex rows ──────────────────────────────────────────────────────
    if cx.get("ok"):
        rows = [
            (cx.get("short_label", "?"), cx.get("short_used_percent"), cx.get("short_reset", "?")),
            (cx.get("long_label", "?"), cx.get("long_used_percent"), cx.get("long_reset", "?")),
        ]
        bx, bw = 64, 160
        rh = 28
        ry = 56
        rx = bx + bw + 8

        for label, used, reset in rows:
            draw.text((PAD, ry + 6), label, font=big, fill=BLACK)
            _bar(bx, ry, bw, rh, 100 - used if used is not None else 0)
            remaining = 100 - used if used is not None else 0
            draw.text((rx, ry - 2), f"{remaining:.0f}%", font=big, fill=BLACK)
            rw2, _ = _tsize(draw, reset, small)
            draw.text((rx, ry + rh - 6), reset, font=small, fill=BLACK)
            ry += rh + 16
    else:
        draw.text((PAD, 56), "CODEX", font=big, fill=BLACK)
        status = cx.get("raw_status", "error")
        draw.text((PAD, 80), status, font=mid, fill=BLACK)

    # ── DeepSeek ─────────────────────────────────────────────────────────
    if ds.get("ok"):
        _divider(ry + 4)
        ry += 16
        dlogo = LOGO_DEEPSEEK.resize((LOGO_S, LOGO_S), Image.NEAREST)
        _logo_draw(dlogo, PAD, ry)
        draw.text((PAD + LOGO_S + 6, ry + 2), "DEEPSEEK", font=mid, fill=BLACK)
        ry += 24
        bal_val = ds.get("balance")
        sym = ds.get("symbol", "$")
        draw.text((PAD, ry), f"{sym}{bal_val:.2f}" if bal_val is not None else "?", font=big, fill=BLACK)
        _, bh = _tsize(draw, "0", big)
        status = ds.get("status", "ok").upper()
        sw, _ = _tsize(draw, status, small)
        draw.text((W - PAD - sw, ry + bh - 6), status, font=small, fill=BLACK)


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
