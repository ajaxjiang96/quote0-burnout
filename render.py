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
def _load_logo(path):
    img = Image.open(path)
    if img.mode == "RGBA":
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    return img.convert("L").point(lambda x: 0 if x < 200 else 255, "1")

LOGO_CHATGPT    = _load_logo(Path(__file__).parent / "assets" / "logos" / "chatgpt.png")
LOGO_DEEPSEEK = _load_logo(Path(__file__).parent / "assets" / "logos" / "deepseek.png")
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

    big = _vcr()          # 21px VCR — CHATGPT, labels, percentages
    mid = _op()           # 16px OP — general text
    countdown_font = ImageFont.truetype(str(VCR_FONT), 20)  # 20px VCR — countdown (bold, clear)
    time_font = ImageFont.truetype(str(VCR_FONT), 20)  # 20px VCR — timestamp (bold, clear)

    LOGO_S = 20
    logo_big = LOGO_CHATGPT.resize((LOGO_S, LOGO_S), Image.BILINEAR)

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

    def _bar(dx, dy, dw, dh, pct, label=""):
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
        fs = 20
        fnt = ImageFont.truetype(str(VCR_FONT), fs)
        tw, _ = draw.textbbox((0, 0), label, font=fnt)[2:]
        if tw < fill:
            tx = dx + (fill - tw) // 2
            draw.text((tx, dy + (dh - fs) // 2 - 1), label, font=fnt, fill=WHITE)
        else:
            tx = dx + dw + 4
            draw.text((tx, dy + (dh - fs) // 2 - 1), label, font=fnt, fill=BLACK)

    # ── Header ──────────────────────────────────────────────────────────
    # Center header vertically in top zone
    header_zone = 28
    _logo_draw(logo_big, PAD, (header_zone - LOGO_S) // 2)
    draw.text((PAD + LOGO_S + 4, (header_zone - 21) // 2), "ChatGPT", font=big, fill=BLACK)
    tsw, _ = _tsize(draw, ts, time_font)
    draw.text((W - PAD - tsw, (header_zone - 18) // 2), ts, font=time_font, fill=BLACK)

    # ── Divider ─────────────────────────────────────────────────────────
    _divider(header_zone)

    # ── Codex rows ──────────────────────────────────────────────────────
    if cx.get("ok"):
        rows = [
            (cx.get("short_label", "?"), cx.get("short_used_percent"), cx.get("short_reset", "?")),
            (cx.get("long_label", "?"), cx.get("long_used_percent"), cx.get("long_reset", "?")),
        ]
        bx, bw = 64, 160
        rh = 32
        # Center two bars vertically in content zone
        content_top = header_zone + 1
        content_h = H - content_top
        total_bars_h = rh * 2 + 12
        bar_start_y = content_top + (content_h - total_bars_h) // 2
        ry = bar_start_y
        rx = bx + bw + 8

        for label, used, reset in rows:
            # Use baseline alignment for consistent visual centering
            ascent, descent = big.getmetrics()
            baseline_y = ry + (rh + ascent - descent) // 2
            draw.text((PAD, baseline_y - ascent), label, font=big, fill=BLACK)
            remaining = 100 - used if used is not None else 0
            _bar(bx, ry, bw, rh, remaining, f"{remaining:.0f}%")
            # Center countdown vertically with bar
            _, cd_h = _tsize(draw, reset, countdown_font)
            draw.text((rx, ry + (rh - cd_h) // 2), reset, font=countdown_font, fill=BLACK)
            ry += rh + 12
    else:
        draw.text((PAD, 56), "ChatGPT", font=big, fill=BLACK)
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
