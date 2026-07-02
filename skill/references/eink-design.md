# E-Ink Dashboard Design

296×152 B&W e-ink dashboards for Quote/0 devices.

## Layout (v0.8)

```
                        16:40
◆ CODEX
5h  [████████████░░░░░] 89%  4h41m
Week [████████░░░░░░░░] 69%  5d23h
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
◆ CLAUDE
5h  [████████████░░░░░] 42%  2h13m
Week [████████░░░░░░░░] 61%  3d4h
```

- **Codex / Claude**: matched dual-row panels. Each panel is header 18px + two 18px rows.
- **Bars**: inline dot-grid bar. Bar = remaining%, text = remaining% + reset.
- **Shared alignment**: compute one `note_x` from all visible notes; all four bars use the same width.
- **Divider**: 6px dash / 4px gap.

## Panel Geometry

```python
PANEL_Y = 12
PANEL_HEADER_H = 18
PANEL_ROW_H = 18
PANEL_H = PANEL_HEADER_H + PANEL_ROW_H * 2
DIVIDER_GAP_TOP = 8
DIVIDER_GAP_BOTTOM = 10
BAR_H = 10
LABEL_W = 36

def _draw_usage_row(draw, y, label, used_pct, reset, note_font, label_font, note_x):
    bar_y = y + (PANEL_ROW_H - BAR_H) // 2
    # Label left, right text (remaining% + reset), bar middle
    draw.text((PAD, …), label, font=label_font)
    note = f"{100-used_pct:.0f}%  {reset}"
    draw.text((note_x, …), note, font=note_font)
    _bar_dots(draw, PAD+LABEL_W, bar_y, note_x-4-(PAD+LABEL_W), BAR_H, 100-used_pct)
```

Pre-compute `note_x` from max note width across all Codex + Claude rows for equal bar widths.

## Bar Style (dot-grid)

```python
def _bar_dots(draw, x, y, w, h, used_pct):
    draw.rectangle([x, y, x+w-1, y+h-1], outline=BLACK)
    filled = int((w-2) * used_pct / 100)
    draw.rectangle([x+1, y+1, x+filled, y+h-2], fill=BLACK)
    # 4px dot grid in empty area
    for dy in range(y+2, y+h-2, 4):
        for dx in range(x+2, x+w-2, 4):
            if dx >= x+1+filled:
                draw.point((dx, dy), fill=BLACK)
```

## Font Stack

| Font | Size | File | Use |
|------|------|------|-----|
| PixelOperator | 16px | PixelOperator.ttf | Section labels and row labels |
| Minecraftia | 8px | Minecraftia-Regular.ttf | Timestamp and usage notes |

All in `assets/fonts/`.

## Logos

16×16 1-bit PNGs in `assets/logos/`. Pasted pixel-by-pixel (PIL `paste()` doesn't work for pure B&W blending).

- `codex.png`: Codex mark
- `claude.png`: Claude symbol, converted to monochrome for e-ink

```python
LOGO_W = 16
LOGO_GAP = 4
LABEL_X = PAD + LOGO_W + LOGO_GAP  # 30

def _logo(logo_img, y):
    for dy in range(LOGO_W):
        for dx in range(LOGO_W):
            if logo_img.getpixel((dx, dy)) == 0:
                img.putpixel((PAD + dx, y + dy), BLACK)
```

## Time Format

```python
def _time_until(val) -> str:
    # val: ISO string or unix timestamp
    delta = dt - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    h, m = divmod(secs, 3600)[0], (secs % 3600) // 60
    if h >= 24: return f"{h//24}d{h%24}h"
    if h > 0:   return f"{h}h{m:02d}m" if m else f"{h}h"
    return f"{m}m"
```

## Bottom Fit

Both panels use `PANEL_H=54`; top panel starts at y=12 and bottom panel ends around y=138, leaving safe bottom whitespace within 152px.
Use `textbbox()` to trace exact positions and avoid clipping.
