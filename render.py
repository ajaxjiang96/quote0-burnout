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
LOGO_CODEX    = Image.open(Path(__file__).parent / "assets" / "logos" / "codex.png").convert("1")
LOGO_CLAUDE   = Image.open(Path(__file__).parent / "assets" / "logos" / "claude.png").convert("1")
LOGO_DEEPSEEK = Image.open(Path(__file__).parent / "assets" / "logos" / "deepseek.png").convert("1")
LOGO_OPENCODE = Image.open(Path(__file__).parent / "assets" / "logos" / "opencode.png").convert("1")
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
        rows = []
        for lbl, key in (("5h", "rolling"), ("Wk", "weekly"), ("Mo", "monthly")):
            w = sn.get(key) or {}
            if w.get("used_percent") is not None:
                rows.append((lbl, w["used_percent"], w.get("reset", "?")))
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
        bits = []
        for lbl, key in (("5h", "rolling"), ("Wk", "weekly"), ("Mo", "monthly")):
            w = sn.get(key) or {}
            if w.get("used_percent") is not None:
                bits.append(f"{lbl} {w['used_percent']}% {w.get('reset', '?')}")
        note = "  ".join(bits) or sn.get("status", "error")
        draw.text((LABEL_X, y + PANEL_HEADER_H), note, font=small, fill=BLACK)
        _, nh = _tsize(draw, note, small)
        return y + PANEL_HEADER_H + nh + 3

    def _draw_deepseek_row(y, logo_img, title, sn):
        """DeepSeek balance tier: balance + peak/off-peak badge on one line."""
        _logo(logo_img, y)
        draw.text((LABEL_X, y), title, font=label, fill=BLACK)
        bal = sn.get("balance")
        sym = sn.get("symbol", "$")
        bal_text = f"{sym}{bal:.2f}" if bal is not None else "?"
        dw, _ = _tsize(draw, title, label)
        draw.text((LABEL_X + dw + 6, y), bal_text, font=label, fill=BLACK)
        _, bh = _tsize(draw, bal_text, label)

        win = sn.get("window")
        p_in = sn.get("price_in")
        if win and p_in is not None:
            badge = f"{win} {sym}{p_in:.2f}"
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
        panels.append(("CODEX", LOGO_CODEX, cx, "usage"))
    if cl_ok:
        panels.append(("CLAUDE", LOGO_CLAUDE, cl, "usage"))
    if second == "opencode":
        layers = ["windows3"] if len(panels) + 1 <= 2 else ["windows3compact"]
        for layer in layers:
            panels.append(("OPENCODE-GO", LOGO_OPENCODE, oc, layer))
    elif second == "deepseek":
        panels.append(("DEEPSEEK", LOGO_DEEPSEEK, ds, "balance"))

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
CELL_PAD = 6


@dataclass(frozen=True)
class _Cell:
    x0: int
    y0: int
    w: int
    h: int
    kind: str  # "half" | "q"


LAYOUTS = {
    # 1+1: two stacked full-width halves
    "1+1": [_Cell(0, 0, 296, 76, "half"), _Cell(0, 76, 296, 76, "half")],
    # 1+2: half on TOP + two quarters on the BOTTOM
    "1+2": [
        _Cell(0, 0, 296, 76, "half"),
        _Cell(0, 76, 148, 76, "q"),
        _Cell(148, 76, 148, 76, "q"),
    ],
    # 2+2: four quarter cells
    "2+2": [
        _Cell(0, 0, 148, 76, "q"), _Cell(148, 0, 148, 76, "q"),
        _Cell(0, 76, 148, 76, "q"), _Cell(148, 76, 148, 76, "q"),
    ],
}

_PROVIDER_ORDER = ("codex", "claude", "deepseek", "opencode")
_TITLE_BY_NAME = {
    "codex": "CODEX", "claude": "CLAUDE",
    "deepseek": "DEEPSEEK", "opencode": "OPENCODE-GO",
}
_LOGO_BY_NAME = {
    "codex": LOGO_CODEX, "claude": LOGO_CLAUDE,
    "deepseek": LOGO_DEEPSEEK, "opencode": LOGO_OPENCODE,
}


def _logo_paste(img, logo_img, x, y):
    for dy in range(LOGO_W):
        for dx in range(LOGO_W):
            if logo_img.getpixel((dx, dy)) == 0:
                img.putpixel((x + dx, y + dy), BLACK)


_q_font_cache = None


def _qfont() -> ImageFont.FreeTypeFont:
    """12px PixelOperator — quarter-cell content face (readability pass)."""
    global _q_font_cache
    if _q_font_cache is None:
        _q_font_cache = ImageFont.truetype(str(OP_FONT), 12)
    return _q_font_cache


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
        _vdash(draw, CELL_W, 0, H)
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


def _select_panels(snapshot, live, n) -> list[str]:
    """Pick n providers: primaries (codex, claude) first, then secondaries
    (deepseek, opencode). When only one secondary slot is left, the
    second_panel preference arbitrates; a compatible auto layout never
    needs arbitration because slots fit the secondaries' count."""
    primaries = [p for p in ("codex", "claude") if p in live]
    secondaries = [p for p in ("deepseek", "opencode") if p in live]
    chosen = list(primaries[:n])
    room = n - len(chosen)
    if room >= len(secondaries):
        chosen += secondaries
    elif room > 0:
        pref = snapshot.get("second_panel")
        pick = pref if pref in secondaries else (
            "opencode" if "opencode" in secondaries else secondaries[0])
        chosen.append(pick)
    return chosen[:n]


def _plan_layout(snapshot) -> tuple[str, list]:
    """(mode, jobs) where jobs = [(provider_name, _Cell), ...].

    mode == "stack" → caller falls back to _render_v5."""
    raw = snapshot.get("layout") or "stack"
    if raw == "auto":
        raw = _resolve_auto(snapshot)
    if raw not in LAYOUTS:
        return "stack", []
    cells = LAYOUTS[raw]
    jobs = list(zip(_select_panels(snapshot, _live_providers(snapshot), len(cells)), cells))
    return raw, jobs


def _cell_note_x(draw, rows, small):
    notes = []
    for _, used, reset in rows:
        _, nw = _usage_note(draw, used, reset, small)
        notes.append(nw)
    return W - PAD - max(notes) if notes else None


def _q_title(draw, name, cell):
    """Quarter-cell header: 8px uppercase title."""
    draw.text((cell.x0 + CELL_PAD, cell.y0 + 4), _TITLE_BY_NAME.get(name, name.upper()),
              font=_pixel(), fill=BLACK)


def _q_lines(draw, cell, rows):
    """Two content lines from (label, used, reset) rows — remaining%,
    at 12px PixelOperator (readability pass: quarters had room for a
    larger face)."""
    qfont = _qfont()
    y = cell.y0 + 22
    for lbl, used, reset in rows[:2]:
        line = f"{lbl} {100 - used:.0f}% {reset}" if used is not None else f"{lbl} ?"
        line = _clip_text(draw, line, qfont, cell.w - 2 * CELL_PAD)
        draw.text((cell.x0 + CELL_PAD, y), line, font=qfont, fill=BLACK)
        y += 18


def _draw_cell(img, draw, name, sn, cell):
    label = _op()
    small = _pixel()

    if cell.kind == "q":
        _q_title(draw, name, cell)
        if not sn.get("ok"):
            status = _clip_text(draw, sn.get("raw_status", "error"), small, cell.w - 2 * CELL_PAD)
            draw.text((cell.x0 + CELL_PAD, cell.y0 + 24), status, font=small, fill=BLACK)
            return
        if name in ("codex", "claude"):
            _q_lines(draw, cell, _window_rows(sn))
        elif name == "opencode":
            rows = []
            for lbl, key in (("5h", "rolling"), ("Wk", "weekly"), ("Mo", "monthly")):
                w = sn.get(key) or {}
                if w.get("used_percent") is not None:
                    rows.append((lbl, w["used_percent"], w.get("reset", "?")))
            _q_lines(draw, cell, rows)
        elif name == "deepseek":
            sym = sn.get("symbol", "$")
            bal = f"{sym}{sn.get('balance', 0):.2f}" if sn.get("balance") is not None else "?"
            draw.text((cell.x0 + CELL_PAD, cell.y0 + 18), bal, font=label, fill=BLACK)
            win = sn.get("window")
            if win:
                extra = f" {sn.get('countdown', '')}" if sn.get("countdown") else ""
                badge = f"{win} {sym}{sn.get('price_in', 0):.2f}{extra}"
                badge = _clip_text(draw, badge, _qfont(), cell.w - 2 * CELL_PAD)
                draw.text((cell.x0 + CELL_PAD, cell.y0 + 42), badge, font=_qfont(), fill=BLACK)
        return

    # ── half tier ─────────────────────────────────────────────────────────
    y_top = cell.y0 + PANEL_Y
    logo = _LOGO_BY_NAME.get(name)
    if logo is not None:
        _logo_paste(img, logo, cell.x0 + PAD, y_top)
    draw.text((LABEL_X, y_top), _TITLE_BY_NAME.get(name, name.upper()), font=label, fill=BLACK)

    if not sn.get("ok"):
        status = _clip_text(draw, sn.get("raw_status", "error"), small, cell.w - 2 * PAD - LABEL_X)
        draw.text((LABEL_X, y_top + 24), status, font=small, fill=BLACK)
        return

    if name in ("codex", "claude"):
        rows = _window_rows(sn)
        n_x = _cell_note_x(draw, rows, small)
        row_y = y_top + PANEL_HEADER_H
        for row in rows:
            row_y = _draw_usage_row(
                draw, row_y, row[0], row[1], row[2],
                small, label, n_x, row_h=PANEL_ROW_H, bar_h=BAR_H)
    elif name == "opencode":
        rows = []
        for lbl, key in (("5h", "rolling"), ("Wk", "weekly"), ("Mo", "monthly")):
            w = sn.get(key) or {}
            if w.get("used_percent") is not None:
                rows.append((lbl, w["used_percent"], w.get("reset", "?")))
        n_x = _cell_note_x(draw, rows, small)
        row_y = y_top + PANEL_HEADER_H
        for row in rows:
            row_y = _draw_usage_row(
                draw, row_y, row[0], row[1], row[2],
                small, label, n_x, row_h=PANEL_ROW_H, bar_h=BAR_H)
    elif name == "deepseek":
        sym = sn.get("symbol", "$")
        bal = f"{sym}{sn.get('balance', 0):.2f}" if sn.get("balance") is not None else "?"
        dw, _ = _tsize(draw, _TITLE_BY_NAME.get(name, name.upper()), label)
        draw.text((LABEL_X + dw + 6, y_top), bal, font=label, fill=BLACK)
        win = sn.get("window")
        if win:
            lines = [f"next {sn.get('next_window', '?')} in {sn.get('countdown', '?')}"
                     if sn.get("countdown") else f"window {win}",
                     f"in {sym}{sn.get('price_in', 0):.2f} out {sym}{sn.get('price_out', 0):.2f}"]
            vy = y_top + 40
            for line in lines:
                line = _clip_text(draw, line, small, cell.w - 2 * PAD - LABEL_X)
                draw.text((LABEL_X, vy), line, font=small, fill=BLACK)
                vy += 14


def _render_grid(img: Image.Image, draw: ImageDraw.ImageDraw, snap: dict, layout: str):
    mode, jobs = _plan_layout(snap)
    if mode == "stack":
        _render_v5(img, draw, snap)
        return
    _draw_seams(draw, mode)
    # One global refresh time, top-right — cells don't duplicate it.
    ts = snap.get("updated_at", "")
    if ts:
        tsw, _ = _tsize(draw, ts, _pixel())
        draw.text((W - PAD - tsw, 4), ts, font=_pixel(), fill=BLACK)
    for name, cell in jobs:
        _draw_cell(img, draw, name, snap.get(name, {}), cell)


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
        layout = arg.get("layout")
        if layout in (None, "stack"):
            _render_v5(img, draw, arg)
        else:
            _render_grid(img, draw, arg, layout)
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
