"""
Render a 296×152 pure black/white PNG for Quote/0 e-ink display.

v0.8: matched Codex + Claude panels with shared row, bar, and icon sizing.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
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
LOGO_CLAUDE   = Image.open(Path(__file__).parent / "assets" / "logos" / "claude.png").convert("1")
LOGO_DEEPSEEK = Image.open(Path(__file__).parent / "assets" / "logos" / "deepseek.png").convert("1")
LOGO_OPENCODE = Image.open(Path(__file__).parent / "assets" / "logos" / "opencode.png").convert("1")
LOGO_AGY      = Image.open(Path(__file__).parent / "assets" / "logos" / "agy.png").convert("1")
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
    """VCR OSD Mono at its native 21px — the original DeepSeek balance face.
    A larger primary value than PixelOperator 16, still pixel-perfect."""
    global _vcr_font_cache
    if _vcr_font_cache is None:
        _vcr_font_cache = ImageFont.truetype(str(VCR_FONT), 21)
    return _vcr_font_cache

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
PANEL_HEADER_H = 16
PANEL_ROW_H = 16
PANEL_H = PANEL_HEADER_H + PANEL_ROW_H * 2
DIVIDER_GAP_TOP = 5
DIVIDER_GAP_BOTTOM = 7
BAR_H = 10
LABEL_W = 36


def _divider(draw, y, dash_len=6, gap_len=4):
    """Zellux-style dashed divider: 6px dash / 4px gap."""
    x = 0
    while x < W:
        draw.line([(x, y), (min(x + dash_len - 1, W), y)], fill=BLACK, width=1)
        x += dash_len + gap_len
    return y + 1


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
        row
        for row in [
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
        if row[1] is not None  # skip windows the API didn't return (e.g. no secondary)
    ]


def _opencode_rows(sn: dict) -> list:
    """OpenCode 5h/Wk/Mo rows — same collector for stack, halves, quarters."""
    rows = []
    for lbl, key in (("5h", "rolling"), ("Wk", "weekly"), ("Mo", "monthly")):
        w = sn.get(key) or {}
        if w.get("used_percent") is not None:
            rows.append((lbl, w["used_percent"], w.get("reset", "?")))
    return rows


def _balance_text(sn: dict) -> str:
    """DeepSeek balance with symbol, or '?' when the API didn't return one."""
    sym = sn.get("symbol", "$")
    bal = sn.get("balance")
    return f"{sym}{bal:.2f}" if bal is not None else "?"


def _price_text(sym: str, v):
    """Price string with symbol, or None when the API didn't return one."""
    return f"{sym}{v:.2f}" if v is not None else None


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
            for row in rows:
                row_y = _draw_usage_row(
                    draw, row_y, row[0], row[1], row[2],
                    small, label, note_x, row_h=PANEL_ROW_H, bar_h=BAR_H)
        else:
            status = sn.get("raw_status", "error")
            draw.text((LABEL_X, row_y), status, font=label, fill=BLACK)

        return y + PANEL_H

    def _draw_windows3_panel(y, logo_img, title, sn):
        """OpenCode Go full tier: header + 5h/Wk/Mo rows with equal-width bars."""
        _logo(logo_img, y)
        draw.text((LABEL_X, y), title, font=label, fill=BLACK)
        rows = _opencode_rows(sn)
        note_w = []
        for _, used, reset in rows:
            _, nw = _usage_note(draw, used, reset, small)
            note_w.append(nw)
        n_x = W - PAD - max(note_w or [0])
        row_y = y + PANEL_HEADER_H
        for row in rows:
            row_y = _draw_usage_row(
                draw, row_y, row[0], row[1], row[2],
                small, label, n_x, row_h=PANEL_ROW_H, bar_h=BAR_H)
        return y + PANEL_HEADER_H + PANEL_ROW_H * len(rows)

    def _draw_windows3_compact(y, logo_img, title, sn):
        """OpenCode Go compact tier: title line + note line when crowded."""
        _logo(logo_img, y)
        draw.text((LABEL_X, y), title, font=label, fill=BLACK)
        bits = [f"{lbl} {used}% {reset}" for lbl, used, reset in _opencode_rows(sn)]
        note = "  ".join(bits) or sn.get("status", "error")
        draw.text((LABEL_X, y + PANEL_HEADER_H), note, font=small, fill=BLACK)
        _, nh = _tsize(draw, note, small)
        return y + PANEL_HEADER_H + nh + 3

    def _draw_deepseek_row(y, logo_img, title, sn):
        """DeepSeek balance tier: balance + peak/off-peak badge on one line."""
        _logo(logo_img, y)
        draw.text((LABEL_X, y), title, font=label, fill=BLACK)
        sym = sn.get("symbol", "$")
        bal_text = _balance_text(sn)
        dw, _ = _tsize(draw, title, label)
        draw.text((LABEL_X + dw + 6, y), bal_text, font=label, fill=BLACK)
        _, bh = _tsize(draw, bal_text, label)

        win = sn.get("window")
        p_in = _price_text(sym, sn.get("price_in"))
        if win and p_in is not None:
            badge = f"{win} {p_in}"
            cd = sn.get("countdown")
            if cd:
                badge += f" {cd}"
        else:
            badge = sn.get("status", "ok").upper()
        sw, sh = _tsize(draw, badge, small)
        draw.text((W - PAD - sw, y + (bh - sh) // 2), badge, font=small, fill=BLACK)
        return y + PANEL_HEADER_H

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

    # ── Panels: only providers with live data; dashed divider between ──
    cx_ok = cx.get("ok")
    cl_ok = cl.get("ok")
    ds = snap.get("deepseek", {})
    oc = snap.get("opencode", {})
    second = snap.get("second_panel")
    if second not in ("deepseek", "opencode"):
        second = "deepseek" if ds.get("ok") else ("opencode" if oc.get("ok") else "none")
    if second == "opencode" and not oc.get("ok"):
        second = "deepseek" if ds.get("ok") else "none"
    if second == "deepseek" and not ds.get("ok"):
        second = "opencode" if oc.get("ok") else "none"

    # (title, logo, snapshot, layer) — layer: usage | windows3 | compact | balance
    panels = []
    if cx_ok:
        t = "CODEX*" if cx.get("_cached") else "CODEX"
        panels.append((t, LOGO_CODEX, cx, "usage"))
    if cl_ok:
        t = "CLAUDE*" if cl.get("_cached") else "CLAUDE"
        panels.append((t, LOGO_CLAUDE, cl, "usage"))
    if second == "opencode":
        layers = ["windows3"] if len(panels) + 1 <= 2 else ["windows3compact"]
        t = "OPENCODE-GO*" if oc.get("_cached") else "OPENCODE-GO"
        for layer in layers:
            panels.append((t, LOGO_OPENCODE, oc, layer))
    elif second == "deepseek":
        t = "DEEPSEEK*" if ds.get("_cached") else "DEEPSEEK"
        panels.append((t, LOGO_DEEPSEEK, ds, "balance"))

    if not panels:
        return

    y = PANEL_Y
    gap_top = DIVIDER_GAP_TOP if len(panels) <= 2 else 3
    gap_bot = DIVIDER_GAP_BOTTOM if len(panels) <= 2 else 4
    for i, (title, logo_img, sn, layer) in enumerate(panels):
        if i > 0:
            y += gap_top
            y = _divider(draw, y)
            y += gap_bot
        if layer == "usage":
            y = _draw_panel(y, logo_img, title, sn, note_x)
        elif layer == "windows3":
            y = _draw_windows3_panel(y, logo_img, title, sn)
        elif layer == "windows3compact":
            y = _draw_windows3_compact(y, logo_img, title, sn)
        else:  # balance
            y = _draw_deepseek_row(y, logo_img, title, sn)


# ── Grid layout engine (1+1 / 1+2 / 2+2) ────────────────────────────────────
# Screen = 2 rows × 76px. ½ panel = one full-width row (296×76); ¼ cell = 148×76.

CELL_W, CELL_H = 148, 76
_TS_STRIP_SAFE = 26  # 8px '16:40' measures ≈26px — narrower strips can't reach the TR title


@dataclass(frozen=True)
class _Cell:
    x0: int
    y0: int
    w: int
    kind: str  # "half" | "q"


LAYOUTS = {
    # 1+1: two stacked full-width halves
    "1+1": [_Cell(0, 0, 296, "half"), _Cell(0, 76, 296, "half")],
    # 1+2: half on TOP + two quarters on the BOTTOM
    "1+2": [
        _Cell(0, 0, 296, "half"),
        _Cell(0, 76, 148, "q"),
        _Cell(148, 76, 148, "q"),
    ],
    # 2+2: four quarter cells
    "2+2": [
        _Cell(0, 0, 148, "q"), _Cell(148, 0, 148, "q"),
        _Cell(0, 76, 148, "q"), _Cell(148, 76, 148, "q"),
    ],
}

_PROVIDER_ORDER = ("codex", "claude", "deepseek", "opencode", "agy")
_TITLE_BY_NAME = {
    "codex": "CODEX", "claude": "CLAUDE",
    "deepseek": "DEEPSEEK", "opencode": "OPENCODE-GO",
    "agy": "GOOGLE AGY",
}
_LOGO_BY_NAME = {
    "codex": LOGO_CODEX, "claude": LOGO_CLAUDE,
    "deepseek": LOGO_DEEPSEEK, "opencode": LOGO_OPENCODE,
    "agy": LOGO_AGY,
}


def _logo_paste(img, logo_img, x, y):
    for dy in range(LOGO_W):
        for dx in range(LOGO_W):
            if logo_img.getpixel((dx, dy)) == 0:
                img.putpixel((x + dx, y + dy), BLACK)


def _clip_text(draw, text, font, max_w):
    """Truncate text to fit max_w; no ellipsis (pixel fonts lack the glyph)."""
    if _tsize(draw, text, font)[0] <= max_w:
        return text
    while text and _tsize(draw, text, font)[0] > max_w:
        text = text[:-1]
    return text


def _hdash(draw, y, x0, x1, dash_len=6, gap_len=4):
    x = x0
    while x < x1:
        draw.line([(x, y), (min(x + dash_len - 1, x1), y)], fill=BLACK, width=1)
        x += dash_len + gap_len


def _vdash(draw, x, y0, y1, dash_len=6, gap_len=4):
    y = y0
    while y < y1:
        draw.line([(x, y), (x, min(y + dash_len - 1, y1))], fill=BLACK, width=1)
        y += dash_len + gap_len


def _junction(draw, x, y, arms):
    """Solid 1px junction: 2px arms per direction (l/r/u/d)."""
    if "l" in arms:
        draw.line([(x - 2, y), (x, y)], fill=BLACK)
    if "r" in arms:
        draw.line([(x, y), (x + 2, y)], fill=BLACK)
    if "u" in arms:
        draw.line([(x, y - 2), (x, y)], fill=BLACK)
    if "d" in arms:
        draw.line([(x, y), (x, y + 2)], fill=BLACK)


def _draw_seams(draw, layout):
    y = CELL_H
    if layout == "2+2":
        _hdash(draw, y, 0, W)
        # Re-phase the vertical dashes at the junction, as the 1+2 bottom
        # row does: the crossing's 2px arms are too short to bridge a 4px
        # gap, so a 0-anchored phase leaves a 1px hole under the junction
        # (rows 70-75 dash, gap 76-79: row 79 white).
        _vdash(draw, CELL_W, 0, y)
        _vdash(draw, CELL_W, y, H)
        _junction(draw, CELL_W, y, ("l", "r", "u", "d"))  # ┼
    elif layout == "1+2":
        _hdash(draw, y, 0, W)
        _vdash(draw, CELL_W, y, H)  # bottom row only
        _junction(draw, CELL_W, y, ("l", "r", "d"))       # ┴
    elif layout == "1+1":
        _hdash(draw, y, 0, W)


def _live_providers(snapshot) -> list[str]:
    """Providers whose last fetch succeeded (ok=True) — dead providers
    (no auth, timeouts) are hidden, not shown as error cells."""
    return [k for k in _PROVIDER_ORDER if snapshot.get(k, {}).get("ok")]


def _resolve_auto(snapshot) -> str:
    n = len(_live_providers(snapshot))
    return {0: "stack", 1: "stack", 2: "1+1", 3: "1+2"}.get(n, "2+2")


def _order_panels(snapshot, live, n) -> list[str]:
    """Recency order: most-recently-changed provider first.

    Each provider's updated_at is its LAST DATA-CHANGE time (computed in
    display.build_snapshot by fingerprinting against the previous cached
    snapshot; an unchanged provider keeps its older stamp and drifts back
    in priority). Ties — first run, or several providers changed in the
    same cycle — fall back to canonical order. The first n live providers
    fill the layout's cells in order (top-left = most visible)."""
    return sorted(
        live,
        key=lambda p: (
            snapshot.get(p, {}).get("updated_at", ""),
            -_PROVIDER_ORDER.index(p),
        ),
        reverse=True,
    )[:n]


def _plan_layout(snapshot) -> tuple[str, list]:
    """(mode, jobs) where jobs = [(provider_name, _Cell), ...].

    mode == "stack" → caller falls back to _render_v5."""
    raw = snapshot.get("layout") or "stack"
    if raw == "auto":
        raw = _resolve_auto(snapshot)
    if raw not in LAYOUTS:
        return "stack", []
    cells = LAYOUTS[raw]
    jobs = list(zip(_order_panels(snapshot, _live_providers(snapshot), len(cells)), cells))
    return raw, jobs


def _cell_note_x(draw, rows, small):
    notes = []
    for _, used, reset in rows:
        _, nw = _usage_note(draw, used, reset, small)
        notes.append(nw)
    return W - PAD - max(notes) if notes else None


def _q_title(img, draw, name, cell, reserve_ts=0, cached=False):
    """Quarter-cell header: 16px logo + 16px PixelOperator title — identical
    faces AND geometry (PAD / LABEL_X) to the half cards so all panels
    share one left edge. reserve_ts (>0) clips the title so it never runs
    into the global refresh time on the top-right cell's header row."""
    logo = _LOGO_BY_NAME.get(name)
    if logo is not None:
        _logo_paste(img, logo, cell.x0 + PAD, cell.y0 + 2)
    title = _TITLE_BY_NAME.get(name, name.upper())
    if cached:
        title += "*"
    if reserve_ts:
        # Title starts at cell.x0+LABEL_X and must end before the ts strip's
        # left edge (W - PAD - reserve_ts) — that bound is the exact gap.
        max_w = (W - PAD - reserve_ts) - (cell.x0 + LABEL_X)
        title = _clip_text(draw, title, _op(), max_w)
    draw.text((cell.x0 + LABEL_X, cell.y0 + 2), title, font=_op(), fill=BLACK)


def _q_lines(draw, cell, rows):
    """Content lines from (label, used, reset) rows — remaining%.

    Two rows breathe at a 24px pitch; opencode's third (5h/Wk/Mo all show)
    compresses to 15px so the monthly tier stays visible in the cell.
    Face: PixelOperator at its NATIVE 16px (pixel grid — scaling a pixel
    font breaks glyphs, e.g. the '.'; see the 12px regressions). Same face
    as half-tier labels; widest string 'Week 59% 123h3m' measured 105px
    against the 128px content width of a 148px cell."""
    qfont = _op()
    y = cell.y0 + 26
    pitch = 24 if len(rows) <= 2 else 15
    for lbl, used, reset in rows:
        line = _q_line(lbl, used, reset)
        line = _clip_text(draw, line, qfont, cell.w - 2 * PAD)
        draw.text((cell.x0 + PAD, y), line, font=qfont, fill=BLACK)
        y += pitch


def _q_line(lbl, used, reset) -> str:
    """One quarter content line. A missing/unknown reset is elided — the
    APIs can return None (e.g. codex long_reset) and printing the Python
    repr on the e-ink screen is the bug the guard exists for."""
    if lbl == "Reset":
        # codex reset row: 'Reset 1 · 29d' (credits · reset-credit expiry)
        return f"Reset {reset}"
    if used is None:
        return f"{lbl} ?"
    reset = reset if reset and reset != "?" else ""
    return f"{lbl} {100 - used:.0f}% {reset}".strip()


def _reset_note(sn: dict) -> str | None:
    """Codex extra row: manual reset credits + the reset credit's expiry.

    Values only ('1 · 29d') — the row's own label carries the Reset wording.
    The expiry is the CREDIT's (from wham/rate-limit-reset-credits), not any
    usage window's reset. None when the API returned neither (only codex has
    reset credits, so claude/others naturally get None)."""
    n = sn.get("resets_available")
    expiry = sn.get("reset_expiry")
    if n is None and not expiry:
        return None
    parts = [str(n)] if n is not None else []
    if expiry:
        parts.append(expiry)
    return " · ".join(parts)


def _draw_reset_row(draw, y, note, note_font, label_font, note_x,
                    row_h=PANEL_ROW_H, bar_h=BAR_H):
    """Bar-less Reset row: 16px label + 8px note, same pitch and right edge
    as the usage rows so the panel reads as one unit."""
    bar_y = y + (row_h - bar_h) // 2
    _, lh = _tsize(draw, "Reset", label_font)
    draw.text((PAD, bar_y + (bar_h - lh) // 2), "Reset", font=label_font, fill=BLACK)
    nw, nh = _tsize(draw, note, note_font)
    draw.text((note_x, bar_y + (bar_h - nh) // 2), note, font=note_font, fill=BLACK)
    return y + row_h


def _draw_cell(img, draw, name, sn, cell, reserve_ts=0):
    label = _op()
    small = _pixel()

    if cell.kind == "q":
        _q_title(img, draw, name, cell, reserve_ts, cached=bool(sn.get("_cached")))
        if name in ("codex", "claude", "agy"):
            rows = _window_rows(sn)
            note = _reset_note(sn) if name == "codex" else None
            if note:
                # third row at the same 16px face as the window lines (the
                # compressed 15px pitch, like opencode's Mo row) — not a
                # smaller note line.
                rows = rows + [("Reset", None, note)]
            _q_lines(draw, cell, rows)
        elif name == "opencode":
            _q_lines(draw, cell, _opencode_rows(sn))
        elif name == "deepseek":
            sym = sn.get("symbol", "$")
            bal = _balance_text(sn)
            # balance = PRIMARY value of the cell: VCR 21px (native face,
            # same as the pre-#1 stack design), badge below at 16px
            bal = _clip_text(draw, bal, _vcr(), cell.w - 2 * PAD)
            draw.text((cell.x0 + PAD, cell.y0 + 26), bal, font=_vcr(), fill=BLACK)
            win = sn.get("window")
            price_in = _price_text(sym, sn.get("price_in"))
            if win:
                extra = f" {sn.get('countdown', '')}" if sn.get("countdown") else ""
                badge = f"{win} {price_in}{extra}" if price_in is not None else f"{win}{extra}"
                badge = _clip_text(draw, badge, label, cell.w - 2 * PAD)
                draw.text((cell.x0 + PAD, cell.y0 + 48), badge, font=label, fill=BLACK)
        return

    # ── half tier ─────────────────────────────────────────────────────────
    # DeepSeek lifts its header 4px so the 21px hero + 16px info row both
    # fit the 76px cell; the usage halves keep the shared PANEL_Y row so
    # their headers line up with each other.
    y_top = cell.y0 + (8 if name == "deepseek" else PANEL_Y)
    logo = _LOGO_BY_NAME.get(name)
    if logo is not None:
        _logo_paste(img, logo, cell.x0 + PAD, y_top)
    half_title = _TITLE_BY_NAME.get(name, name.upper())
    if sn.get("_cached"):
        half_title += "*"
    draw.text((LABEL_X, y_top), half_title, font=label, fill=BLACK)

    if name in ("codex", "claude", "agy"):
        rows = _window_rows(sn)
        reset_note = _reset_note(sn) if name == "codex" else None
        notes_w = [_usage_note(draw, used, reset, small)[1] for _, used, reset in rows]
        if reset_note:
            notes_w.append(_tsize(draw, reset_note, small)[0])
        n_x = W - PAD - max(notes_w) if notes_w else None
        row_y = _half_row_y(cell, y_top, len(rows) + (1 if reset_note else 0))
        for row in rows:
            row_y = _draw_usage_row(
                draw, row_y, row[0], row[1], row[2],
                small, label, n_x, row_h=PANEL_ROW_H, bar_h=BAR_H)
        if reset_note:
            row_y = _draw_reset_row(draw, row_y, reset_note, small, label, n_x)
    elif name == "opencode":
        rows = _opencode_rows(sn)
        n_x = _cell_note_x(draw, rows, small)
        row_y = _half_row_y(cell, y_top, len(rows))
        for row in rows:
            row_y = _draw_usage_row(
                draw, row_y, row[0], row[1], row[2],
                small, label, n_x, row_h=PANEL_ROW_H, bar_h=BAR_H)
    elif name == "deepseek":
        # Hero tier: balance + tier badge on one 21px row (VCR, native face
        # like the quarter's headline), then one 16px info row — the
        # countdown → next tier on the left, the in/out prices on the right.
        # The header is lifted 4px (see y_top above) so cap-height text
        # clears the hero without a dead band. (The old design crammed the
        # balance inline with the title and left a dead middle band.)
        sym = sn.get("symbol", "$")
        bal = _clip_text(draw, _balance_text(sn), _vcr(), cell.w - 2 * PAD)
        # Same anchor as the badge — both VCR strings share the bbox metrics
        # ((0,4,…,19)), so equal anchors = perfectly aligned baselines.
        draw.text((cell.x0 + PAD, cell.y0 + 24), bal, font=_vcr(), fill=BLACK)
        win = sn.get("window")
        if win:
            bw, _ = _tsize(draw, win, _vcr())
            draw.text((cell.x0 + cell.w - PAD - bw, cell.y0 + 24), win,
                      font=_vcr(), fill=BLACK)
            if sn.get("countdown") and sn.get("next_window"):
                # » is the transition glyph — PixelOperator has no real →
                # (it renders as a tofu box; Minecraftia's 8px → is fine).
                left = f"{sn['countdown']} » {sn['next_window']}"
            else:
                left = f"window {win}"
            p_in = _price_text(sym, sn.get("price_in"))
            p_out = _price_text(sym, sn.get("price_out"))
            parts = []
            if p_in is not None:
                parts.append(f"in {p_in}")
            if p_out is not None:
                parts.append(f"out {p_out}")
            right = " ".join(parts)
            rw = _tsize(draw, right, label)[0] if right else 0
            left = _clip_text(draw, left, label, cell.w - 2 * PAD - rw - 8)
            draw.text((cell.x0 + PAD, cell.y0 + 48), left, font=label, fill=BLACK)
            if right:
                draw.text((cell.x0 + cell.w - PAD - rw, cell.y0 + 48), right,
                          font=label, fill=BLACK)


def _half_row_y(cell, y_top, n_rows) -> int:
    """Row-block baseline: bottom-anchor so a 1-row panel hangs at the same
    seam-adjacent level as a 2-row one (no floating dead space), but clamp
    so the last row's ink stays off the screen border in the bottom half.
    The 16px label ink ends one pixel inside its pitch, so the block itself
    ends 3px short of the cell bottom — without the clamp, opencode's 3-row
    block lands flush against the screen edge."""
    row_y = max(y_top + PANEL_HEADER_H, cell.y0 + 62 - PANEL_ROW_H * n_rows)
    return min(row_y, cell.y0 + CELL_H - PANEL_ROW_H * n_rows - 3)


def _grid_ts(snap) -> str:
    """Grid-mode refresh-time label. A cache fallback sets updated_at to
    '16:40 (cached)' — too wide for the header strip (it collides with the
    top-right cell title); shorten to '16:40*' (the '*' stale marker was
    reserved by #12 anyway)."""
    ts = snap.get("updated_at", "")
    if snap.get("_cached") and " " in ts:
        return ts.split()[0] + "*"
    return ts


def _render_grid(img: Image.Image, draw: ImageDraw.ImageDraw, snap: dict):
    mode, jobs = _plan_layout(snap)
    if mode == "stack":
        _render_v5(img, draw, snap)
        return
    _draw_seams(draw, mode)
    # One global refresh time, top-right — cells don't duplicate it. The
    # top-right quarter's header row shares this line: when the ts is wide
    # (cached '*'), its title is clipped to the strip's left edge (see
    # _q_title) so the two can never collide.
    ts = _grid_ts(snap)
    reserve = 0
    if ts:
        tsw, _ = _tsize(draw, ts, _pixel())
        reserve = tsw if tsw > _TS_STRIP_SAFE else 0
        draw.text((W - PAD - tsw, 4), ts, font=_pixel(), fill=BLACK)
    for name, cell in jobs:
        _draw_cell(img, draw, name, snap.get(name, {}), cell,
                   reserve if (cell.x0 == CELL_W and cell.y0 == 0) else 0)


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
        mode, _ = _plan_layout(arg)  # validates; unknown/absent → stack
        if mode == "stack":
            _render_v5(img, draw, arg)
        else:
            _render_grid(img, draw, arg)
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
        "deepseek": {"ok": True, "balance": 18.42, "currency": "USD",
                     "symbol": "$", "status": "ok",
                     "model": "deepseek-v4-flash", "window": "OFF",
                     "factor": 0.5, "price_in": 0.22, "price_out": 0.66,
                     "ends_in": 6600, "countdown": "1h50m",
                     "next_window": "PEAK"},
        "opencode": {"ok": True,
                     "rolling": {"used_percent": 6, "reset": "2h13m"},
                     "weekly": {"used_percent": 8, "reset": "4d2h"},
                     "monthly": {"used_percent": 4, "reset": "17d"},
                     "short_label": "5h", "short_used_percent": 6,
                     "short_reset": "2h13m", "long_label": "Week",
                     "long_used_percent": 8, "long_reset": "4d2h",
                     "status": "ok"},
        "second_panel": "opencode",
        "updated_at": "16:40",
        "layout": "2+2",
        "configured": ["codex", "claude", "deepseek", "opencode"],
    }
    png = render_image(snap)
    out = Path(__file__).parent / "test_render.png"
    out.write_bytes(png)
    print(f"Saved {out} ({len(png)} bytes)")
