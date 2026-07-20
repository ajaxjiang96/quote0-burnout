"""
Render a 296×152 pure black/white PNG for Quote/0 e-ink display.

v0.7: Today's combined token total + per-software IN/OUT breakdown.
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


LOGO_CHATGPT   = _load_logo(Path(__file__).parent / "assets" / "logos" / "chatgpt.png")
LOGO_DEEPSEEK  = _load_logo(Path(__file__).parent / "assets" / "logos" / "deepseek.png")

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


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _fmt_cost(n: float) -> str:
    """Format dollar cost compactly."""
    if n >= 1000:
        return f"${n / 1000:.1f}k"
    if n >= 1:
        return f"${n:.2f}"
    return f"${n:.3f}"


_op_size_cache = {}


def _opsize(size: int):
    if size not in _op_size_cache:
        _op_size_cache[size] = ImageFont.truetype(str(OP_FONT), size)
    return _op_size_cache[size]


_op14_font = None

def _op14() -> ImageFont.FreeTypeFont:
    global _op14_font
    if _op14_font is None:
        _op14_font = ImageFont.truetype(str(OP_FONT), 14)
    return _op14_font


# ── Helpers ──────────────────────────────────────────────────────────────

def _logo_draw(img, logo_img, x, y):
    s = logo_img.width
    for dy in range(s):
        for dx in range(s):
            if logo_img.getpixel((dx, dy)) == 0:
                img.putpixel((x + dx, y + dy), BLACK)


def _divider(draw, cy):
    x, gap = 0, 4
    while x < W:
        draw.line([(x, cy), (min(x + 5, W), cy)], fill=BLACK)
        x += 5 + gap


def _leader(draw, x0, x1, y, step=4):
    """Draw a dotted leader (row of 1px dots) from x0 to x1 at height y."""
    x = x0
    while x < x1:
        draw.point((x, y), fill=BLACK)
        x += step


# ── Main render ──────────────────────────────────────────────────────────

def _render_v5(img: Image.Image, draw: ImageDraw.ImageDraw, snap: dict):
    cx = snap.get("codex", {})
    oc = snap.get("opencode", {})
    ds = snap.get("deepseek", {})
    ts = snap.get("updated_at", datetime.now().strftime("%H:%M"))

    big = _vcr()
    mid = _op()
    pix = _pixel()
    time_font = ImageFont.truetype(str(VCR_FONT), 18)

    # ── Compute combined totals + cost ──────────────────────────────────
    c_tok  = cx.get("today_tokens", 0)  if cx.get("ok") else 0
    c_in   = cx.get("today_input_tokens", 0)  if cx.get("ok") else 0
    c_out  = cx.get("today_output_tokens", 0) if cx.get("ok") else 0
    c_cost = cx.get("today_cost", 0) if cx.get("ok") else 0
    o_tok  = oc.get("today_tokens", 0)  if oc.get("ok") else 0
    o_in   = oc.get("today_input_tokens", 0)  if oc.get("ok") else 0
    o_out  = oc.get("today_output_tokens", 0) if oc.get("ok") else 0
    o_cost = oc.get("cost", 0) if oc.get("ok") else 0

    total    = c_tok + o_tok
    total_in = c_in + o_in
    total_out= c_out + o_out
    total_cost = c_cost + o_cost

    # ── Header with progress bar ────────────────────────────────────────
    header_zone = 22
    vcr18 = ImageFont.truetype(str(VCR_FONT), 18)
    vcr20 = ImageFont.truetype(str(VCR_FONT), 20)
    vcr16 = ImageFont.truetype(str(VCR_FONT), 16)
    GAP = 10
    ry = header_zone + 4

    def _b(text, x, y, font):
        draw.text((x, y), text, font=font, fill=BLACK)
        draw.text((x + 1, y), text, font=font, fill=BLACK)

    def _w(text, x, y, font):
        draw.text((x, y), text, font=font, fill=WHITE)
        draw.text((x + 1, y), text, font=font, fill=WHITE)

    def _vcy(text, font, y0, h):
        """Return anchor-y that centers the glyph's ink box in [y0, y0+h]."""
        bb = draw.textbbox((0, 0), text, font=font)
        # center of ink box = (bb[1]+bb[3])/2 from anchor; align to box center
        return round(y0 + (h - (bb[1] + bb[3])) / 2)

    # ── Header ───────────────────────────────────────────────────────
    tw, th = _tsize(draw, "Tokens", vcr18)
    _b("Tokens", PAD, (header_zone - th) // 2, vcr18)
    tsw, _ = _tsize(draw, ts, vcr18)
    _b(ts, W - PAD - tsw, (header_zone - th) // 2, vcr18)
    _divider(draw, header_zone)

    # ── Today hero (centered, always visible) ─────────────────────────
    ry += 6
    num_s = _fmt_tokens(total)
    nw, _ = _tsize(draw, num_s, vcr20)
    if total_cost > 0:
        cost_s = _fmt_cost(total_cost)
        cw, _ = _tsize(draw, cost_s, vcr20)
        gap = 44
        group_w = nw + gap + cw
        gx = (W - group_w) // 2
        _b(num_s, gx, ry, vcr20)
        _b(cost_s, gx + nw + gap, ry, vcr20)
    else:
        _b(num_s, (W - nw) // 2, ry, vcr20)
    ry += 20 + GAP

    # ── Progress bar (line 2) ───────────────────────────────────────────
    if cx.get("ok"):
        used = cx.get("short_used_percent", 0)
        reset = cx.get("short_reset", "?")
        remaining = 100 - used if used is not None else 0
        bar_h = 20
        bx = PAD
        bw = 200                      # leave clear space on the right for countdown
        draw.rectangle([bx, ry, bx + bw - 1, ry + bar_h - 1], outline=BLACK)
        fill_w = int((bw - 2) * remaining / 100) if remaining > 0 else 0
        # REMAINING portion = solid black (capacity left)
        if fill_w > 0:
            draw.rectangle([bx + 1, ry + 1, bx + fill_w, ry + bar_h - 2], fill=BLACK)
        # USED portion = white with diagonal dot hatch (consumed)
        for sy in range(ry + 3, ry + bar_h - 2, 3):
            for sx in range(bx + 1 + fill_w, bx + bw - 1, 3):
                draw.point((sx, sy), fill=BLACK)

        # Countdown: plain black text on white, to the RIGHT of the bar (no pill)
        cd_font = vcr20
        cd_x = bx + bw + 14
        cd_y = _vcy(reset, cd_font, ry, bar_h)
        _b(reset, cd_x, cd_y, cd_font)

        # % label = remaining%, white on black (inside filled region)
        # when remaining ≤ 20%, place label in the white used area instead
        pct_font = vcr20
        pct_label = f"{int(remaining)}%"
        pct_tw, pct_th = _tsize(draw, pct_label, pct_font)
        pct_y = _vcy(pct_label, pct_font, ry, bar_h)
        if remaining > 20:
            if fill_w == 0:
                _b(pct_label, bx + 2, pct_y, pct_font)
            elif fill_w >= pct_tw + 4:
                pct_x = bx + (fill_w - pct_tw) // 2
                _w(pct_label, pct_x, pct_y, pct_font)
            else:
                _b(pct_label, bx + 2, pct_y, pct_font)
        else:
            _b(pct_label, bx + fill_w + 2, pct_y, pct_font)
        ry += bar_h + GAP

    # ── Source ledger (typographic) ─────────────────────────────────────
    row_font = vcr16
    rgap = 10

    def _ledger_row(name, in_t, out_t, cost):
        nonlocal ry
        left = f"{name}  {_fmt_tokens(in_t)} / {_fmt_tokens(out_t)}"
        _b(left, PAD, ry, row_font)
        if cost > 0:
            cs = _fmt_cost(cost)
            cw, _ = _tsize(draw, cs, row_font)
            cx0 = W - PAD - cw
            _b(cs, cx0, ry, row_font)
            lw, _ = _tsize(draw, left, row_font)
            _leader(draw, PAD + lw + 3, cx0 - 3, ry + row_font.size // 2, step=4)
        ry += row_font.size + rgap

    if cx.get("ok") or total == 0:
        _ledger_row("Codex", c_in, c_out, c_cost)
    if oc.get("ok") or total == 0:
        _ledger_row("OpenC", o_in, o_out, o_cost)

    # ── Footer separator ──────────────────────────────────────────────
    _divider(draw, H - 6)


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
        "codex": {"ok": True, "short_label": "Week", "short_used_percent": 36,
                  "short_reset": "5d22h", "long_label": "5h",
                  "long_used_percent": None, "long_reset": "?",
                  "status": "ok", "today_tokens": 1520000},
        "deepseek": {"ok": False, "balance": None, "currency": "?",
                      "symbol": "?", "status": "error"},
        "updated_at": "16:40",
    }
    png = render_image(snap)
    out = Path(__file__).parent / "test_render.png"
    out.write_bytes(png)
    print(f"Saved {out} ({len(png)} bytes)")
