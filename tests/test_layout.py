"""Layout engine tests: planning/selection (pure) + grid render smoke + seams.

Selection is LIVE-based: providers whose snapshot is ok get cells; dead
providers (no auth, timeouts) are hidden. Auto maps live count → layout.
Reuses the mock snapshot helpers from test_render.py.
"""

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root for `python tests/test_layout.py`

from PIL import Image

import render
from render import render_image

from test_render import _claude, _codex, _deepseek, _opencode

_NOT_OK = {"ok": False, "status": "error", "raw_status": "dead"}


def _full_snap(layout="2+2", live=None, codex=None, claude=None, deepseek=None, opencode=None):
    codex = codex if codex is not None else _codex()
    claude = claude if claude is not None else _claude(ok=True)
    deepseek = deepseek if deepseek is not None else _deepseek()
    opencode = opencode if opencode is not None else _opencode()
    values = {"codex": codex, "claude": claude, "deepseek": deepseek, "opencode": opencode}
    if live is not None:  # ok flags drive selection; non-live providers are dead
        for name in values:
            if name not in live:
                values[name] = _NOT_OK
    snap = dict(values)
    snap.update({
        "second_panel": "opencode", "layout": layout,
        "configured": ["codex", "claude", "deepseek", "opencode"],
        "updated_at": "16:40",
    })
    return snap


def _dark(img, x, y):
    return img.getpixel((x, y)) < 128


class PlanLayoutTests(unittest.TestCase):
    def test_auto_mapping_from_live_count(self):
        for n, layout in ((0, "stack"), (1, "stack"), (2, "1+1"), (3, "1+2"), (4, "2+2")):
            snap = _full_snap(layout="auto", live=["codex", "claude", "deepseek", "opencode"][:n])
            mode, jobs = render._plan_layout(snap)
            self.assertEqual(mode, layout, f"live N={n}")

    def test_dead_provider_lowers_auto_layout(self):
        # claude dead → 3 live → 1+2, claude hidden (user-verified behavior)
        snap = _full_snap(layout="auto", live=["codex", "deepseek", "opencode"])
        mode, jobs = render._plan_layout(snap)
        self.assertEqual(mode, "1+2")
        self.assertEqual([name for name, _ in jobs], ["codex", "deepseek", "opencode"])

    def test_auto_3_shows_both_secondaries(self):
        snap = _full_snap(layout="auto", live=["codex", "deepseek", "opencode"])
        mode, jobs = render._plan_layout(snap)
        self.assertEqual([name for name, _ in jobs], ["codex", "deepseek", "opencode"])

    def test_2x2_shows_all_four(self):
        mode, jobs = render._plan_layout(_full_snap("2+2"))
        self.assertEqual([name for name, _ in jobs], ["codex", "claude", "deepseek", "opencode"])

    def test_single_secondary_slot_ties_fall_back_to_canonical(self):
        # #32's "one slot → opencode first" was the stopgap until #10: with
        # no change signal (no per-provider stamps) the tie falls back to
        # canonical order; a real recency signal outranks it — the whole
        # point of recency ordering.
        snap = _full_snap("1+1", live=["codex", "deepseek", "opencode"])
        mode, jobs = render._plan_layout(snap)
        self.assertEqual([name for name, _ in jobs], ["codex", "deepseek"])
        snap["second_panel"] = "deepseek"
        mode, jobs = render._plan_layout(snap)
        self.assertEqual([name for name, _ in jobs], ["codex", "deepseek"])
        # recency beats the tiebreak: deepseek changed → it takes the slot
        for name, p_sn in snap.items():
            if isinstance(p_sn, dict) and p_sn.get("ok"):
                p_sn["updated_at"] = "2026-09-04 07:00:00"
        snap["deepseek"]["updated_at"] = "2026-09-04 09:00:00"
        mode, jobs = render._plan_layout(snap)
        self.assertEqual([name for name, _ in jobs], ["deepseek", "codex"])

    def test_single_secondary_slot_falls_back_to_deepseek(self):
        snap = _full_snap("1+1", live=["codex", "deepseek"])
        mode, jobs = render._plan_layout(snap)
        self.assertEqual([name for name, _ in jobs], ["codex", "deepseek"])

    def test_2x2_with_3_live_leaves_one_cell_blank(self):
        snap = _full_snap("2+2", live=["codex", "claude", "deepseek"])
        mode, jobs = render._plan_layout(snap)
        self.assertEqual(mode, "2+2")
        self.assertEqual([name for name, _ in jobs], ["codex", "claude", "deepseek"])
        self.assertEqual(len(jobs), 3)  # 4th cell intentionally blank

    def test_dead_provider_hidden_even_in_explicit_layout(self):
        snap = _full_snap("2+2", live=["codex", "claude", "opencode"])
        mode, jobs = render._plan_layout(snap)
        names = [name for name, _ in jobs]
        self.assertNotIn("deepseek", names)
        self.assertEqual(names, ["codex", "claude", "opencode"])

    def test_stack_and_invalid(self):
        for layout in ("stack", "bogus", None):
            snap = _full_snap()
            snap["layout"] = layout
            mode, jobs = render._plan_layout(snap)
            self.assertEqual(mode, "stack")
            self.assertEqual(jobs, [])


class DeepSeekHalfTests(unittest.TestCase):
    """½-tier DeepSeek hero layout: VCR balance + tier badge, one info row."""

    def _render(self):
        snap = _full_snap("1+1", live=["codex", "deepseek"])
        return Image.open(io.BytesIO(render_image(snap)))

    def test_hero_row_balance_left_badge_right(self):
        px = self._render().load()
        # hero band = balance (left) + tier badge (right), VCR 21px
        left = sum(1 for x in range(8, 90) for y in range(96, 126) if px[x, y] < 128)
        self.assertGreater(left, 20, "balance hero should paint the left band")
        right = sum(1 for x in range(240, 288) for y in range(96, 126) if px[x, y] < 128)
        self.assertGreater(right, 10, "tier badge should sit at the right edge")

    def test_info_row_paints_both_sides(self):
        px = self._render().load()
        # 16px info row: countdown » next tier (left) + in/out prices (right)
        ink = sum(1 for x in range(8, 296) for y in range(126, 146) if px[x, y] < 128)
        self.assertGreater(ink, 30, "info row should paint")


class ResetRowTests(unittest.TestCase):
    """Codex RESET row/line: manual reset credits + closest window expiry."""

    def _snap_1x1(self):
        snap = _full_snap("1+1", live=["codex", "deepseek"])
        snap["codex"] = {"ok": True, "short_label": "Week", "short_used_percent": 100,
                         "short_reset": "3d11h", "resets_available": 1,
                         "closest_reset": "5h", "status": "hot"}
        return snap

    def test_half_reset_row_paints(self):
        img = Image.open(io.BytesIO(render_image(self._snap_1x1())))
        px = img.load()
        # RESET label (16px, left) + note (8px, right-aligned) in the row block
        left = sum(1 for x in range(8, 70) for y in range(44, 66) if px[x, y] < 128)
        self.assertGreater(left, 10, "RESET label should paint the left band")
        right = sum(1 for x in range(190, 290) for y in range(44, 66) if px[x, y] < 128)
        self.assertGreater(right, 10, "reset note should be right-aligned")

    def test_quarter_reset_line_paints(self):
        snap = _full_snap("2+2")
        snap["codex"].update({"resets_available": 1, "closest_reset": "5h"})
        img = Image.open(io.BytesIO(render_image(snap)))
        px = img.load()
        ink = sum(1 for x in range(8, 148) for y in range(62, 74) if px[x, y] < 128)
        self.assertGreater(ink, 5, "8px reset line should paint in the codex quadrant")

    def test_no_reset_data_no_row(self):
        # no resets/closest keys → no second band ink differences: the panel
        # must not crash and stays within the usage rows only
        img = Image.open(io.BytesIO(render_image(_full_snap("1+1", live=["codex", "deepseek"]))))
        self.assertEqual(img.size, (296, 152))


class GridRenderTests(unittest.TestCase):
    def _render(self, snap):
        png = render_image(snap)
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.size, (296, 152))
        dark = sum(1 for px in img.getdata() if px < 128)
        self.assertGreater(dark, 100)
        return img

    def test_2x2_junction_is_4way_plus(self):
        img = self._render(_full_snap("2+2"))
        # (148, 78) ends the junction's 2px d-arm; (148, 79) pins the
        # re-phased dash below — a 0-anchored phase left a 1px hole there.
        for pt in ((148, 76), (146, 76), (150, 76), (148, 74), (148, 78), (148, 79)):
            self.assertTrue(_dark(img, *pt), f"{pt} should be dark (junction)")

    def test_1x2_seams_and_bottom_t_junction(self):
        img = self._render(_full_snap("1+2", live=["codex", "claude", "opencode"]))
        self.assertTrue(_dark(img, 60, 76))       # horizontal seam
        self.assertTrue(_dark(img, 148, 100))     # vertical seam only in bottom row
        self.assertTrue(_dark(img, 148, 79))      # T junction arm down
        self.assertFalse(_dark(img, 148, 5))      # no vertical in top row (above content)
        self.assertFalse(_dark(img, 148, 74))     # no up arm (plain T, not plus)

    def test_1x1_no_vertical_no_junction(self):
        img = self._render(_full_snap("1+1", live=["codex", "claude"]))
        self.assertTrue(_dark(img, 60, 76))       # horizontal seam
        self.assertFalse(_dark(img, 148, 5))      # no vertical top (above content)
        self.assertFalse(_dark(img, 148, 74))     # no junction

    def test_quadrants_each_contain_content(self):
        img = self._render(_full_snap("2+2"))
        px = img.load()
        for x0, y0 in ((0, 0), (148, 0), (0, 76), (148, 76)):
            count = sum(1 for x in range(x0 + 4, x0 + 144)
                        for y in range(y0 + 4, y0 + 72) if px[x, y] < 128)
            self.assertGreater(count, 10, f"quadrant ({x0},{y0}) should have content")

    def test_refresh_time_rendered_once_top_right(self):
        snap = _full_snap("2+2")
        snap["updated_at"] = "09:15"
        img = self._render(snap)
        px = img.load()
        # top-right strip of the whole screen → painted (the one global ts)
        strip = sum(1 for x in range(262, 290) for y in range(4, 16) if px[x, y] < 128)
        self.assertGreater(strip, 0, "global refresh time should be at the top-right")
        # top-left cell corner → EMPTY (no per-cell duplicates)
        strip2 = sum(1 for x in range(104, 142) for y in range(4, 16) if px[x, y] < 128)
        self.assertEqual(strip2, 0, "no per-cell timestamps")

    def test_dead_provider_renders_blank_region_without_crash(self):
        snap = _full_snap("2+2", live=["codex", "claude", "opencode"])
        img = self._render(snap)
        px = img.load()
        # 3 live → cells TL/TR/BL; the unused 4th cell is BR — only seam ink there
        count = sum(1 for x in range(154, 290) for y in range(82, 146) if px[x, y] < 128)
        self.assertLess(count, 20, "dead provider's unused cell should stay blank")

    def test_backcompat_stack_identical_bytes(self):
        plain = _full_snap()
        del plain["layout"]
        stacked = _full_snap("stack")
        stacked["configured"] = ["codex", "claude", "deepseek", "opencode"]
        p1 = render_image(plain)
        self.assertEqual(p1, render_image(plain))                    # deterministic
        self.assertEqual(p1, render_image(stacked))                  # absent == stack
        self.assertEqual(p1, render_image(dict(plain, layout="bogus")))  # invalid == stack

    def test_missing_layout_is_stack(self):
        snap = _full_snap()
        del snap["layout"]
        img = Image.open(io.BytesIO(render_image(snap)))
        self.assertEqual(img.size, (296, 152))

    def test_opencode_quarter_shows_all_three_rows(self):
        # 5h/Wk/Mo in the BR quarter: the monthly row compresses to a 15px
        # pitch and must stay inside the cell.
        img = self._render(_full_snap("2+2"))
        px = img.load()
        third = sum(1 for x in range(154, 290) for y in range(130, 145) if px[x, y] < 128)
        self.assertGreater(third, 5, "monthly row should render in the BR quarter")
        below = sum(1 for x in range(154, 290) for y in range(148, 152) if px[x, y] < 128)
        self.assertEqual(below, 0, "quarter content must stay above the screen edge")

    def test_opencode_three_rows_in_half_do_not_touch_screen_edge(self):
        # 1+1 with opencode in the bottom half: 3 rows clamped so no ink
        # within 3px of the screen's bottom edge.
        img = self._render(_full_snap("1+1", live=["claude", "opencode"]))
        px = img.load()
        edge = sum(1 for x in range(0, 296) for y in (149, 150, 151) if px[x, y] < 128)
        self.assertEqual(edge, 0, "no ink on the bottom three rows of the screen")
        third = sum(1 for x in range(4, 292) for y in range(132, 148) if px[x, y] < 128)
        self.assertGreater(third, 5, "third row should still render, clamped")

    def test_deepseek_without_prices_renders_in_quarter_and_half(self):
        # price_in/price_out arrive as None (cache or API gap): the badge
        # and rate lines must skip rather than format None (TypeError).
        ds = _deepseek()
        ds["price_in"] = None
        ds["price_out"] = None
        img = self._render(_full_snap("2+2", deepseek=ds))
        px = img.load()
        q_count = sum(1 for x in range(4, 144) for y in range(100, 126) if px[x, y] < 128)
        self.assertGreater(q_count, 5, "deepseek quarter should still render its balance")
        img2 = self._render(_full_snap("1+1", live=["codex", "deepseek"], deepseek=ds))
        px2 = img2.load()
        h_count = sum(1 for x in range(4, 292) for y in range(88, 148) if px2[x, y] < 128)
        self.assertGreater(h_count, 5, "deepseek half should still render its balance")


class QuarterLineTests(unittest.TestCase):
    """Pure line formatting — a missing reset is elided, never printed."""

    def test_reset_none_elided(self):
        self.assertEqual(render._q_line("Week", 39, None), "Week 61%")

    def test_reset_unknown_marker_elided(self):
        self.assertEqual(render._q_line("5h", 20, "?"), "5h 80%")

    def test_reset_present_kept(self):
        self.assertEqual(render._q_line("5h", 20, "12:30"), "5h 80% 12:30")

    def test_used_none_shows_question(self):
        self.assertEqual(render._q_line("Mo", None, "3d"), "Mo ?")


class OrderPanelsTests(unittest.TestCase):
    """_order_panels: recency-first ordering with canonical tiebreak."""

    def _snap(self, stamps, live):
        snap = {"layout": "2+2", "updated_at": "16:40"}
        for name in ("codex", "claude", "deepseek", "opencode"):
            if name in live:
                sn = {"ok": True}
                if name in stamps:
                    sn["updated_at"] = stamps[name]
                snap[name] = sn
            else:
                snap[name] = _NOT_OK
        return snap

    def test_most_recent_changed_first(self):
        snap = self._snap({
            "codex": "2026-09-04 08:00:00", "claude": "2026-09-04 06:00:00",
            "deepseek": "2026-09-04 09:00:00", "opencode": "2026-09-04 07:00:00",
        }, ("codex", "claude", "deepseek", "opencode"))
        self.assertEqual(render._order_panels(snap, render._live_providers(snap), 4),
                         ["deepseek", "codex", "opencode", "claude"])

    def test_full_tie_falls_back_to_canonical(self):
        snap = self._snap({
            "codex": "2026-09-04 09:00:00", "claude": "2026-09-04 09:00:00",
            "deepseek": "2026-09-04 09:00:00", "opencode": "2026-09-04 09:00:00",
        }, ("codex", "claude", "deepseek", "opencode"))
        self.assertEqual(render._order_panels(snap, render._live_providers(snap), 4),
                         ["codex", "claude", "deepseek", "opencode"])

    def test_partial_tie_canonical_among_equals(self):
        # codex newest; claude+deepseek tied → canonical keeps claude ahead
        snap = self._snap({
            "codex": "2026-09-04 09:00:00", "claude": "2026-09-04 07:00:00",
            "deepseek": "2026-09-04 07:00:00", "opencode": "2026-09-04 06:00:00",
        }, ("codex", "claude", "deepseek", "opencode"))
        self.assertEqual(render._order_panels(snap, render._live_providers(snap), 4),
                         ["codex", "claude", "deepseek", "opencode"])

    def test_missing_stamps_canonical(self):
        snap = self._snap({}, ("codex", "claude", "deepseek", "opencode"))
        self.assertEqual(render._order_panels(snap, render._live_providers(snap), 4),
                         ["codex", "claude", "deepseek", "opencode"])

    def test_slots_take_top_n(self):
        # 3 live, 2 slots: the two most-recently-changed get the cells
        snap = self._snap({
            "codex": "2026-09-04 08:00:00", "deepseek": "2026-09-04 09:00:00",
            "opencode": "2026-09-04 07:00:00",
        }, ("codex", "deepseek", "opencode"))
        self.assertEqual(render._order_panels(snap, render._live_providers(snap), 2),
                         ["deepseek", "codex"])

    def test_plan_layout_jobs_follow_recency(self):
        snap = self._snap({
            "codex": "2026-09-04 07:00:00", "claude": "2026-09-04 09:00:00",
            "deepseek": "2026-09-04 08:00:00", "opencode": "2026-09-04 06:00:00",
        }, ("codex", "claude", "deepseek", "opencode"))
        mode, jobs = render._plan_layout(snap)
        self.assertEqual(mode, "2+2")
        self.assertEqual([name for name, _ in jobs],
                         ["claude", "deepseek", "codex", "opencode"])

    def test_dead_provider_never_ordered(self):
        snap = self._snap({"deepseek": "2026-09-04 09:00:00"}, ("deepseek", "opencode"))
        self.assertEqual(render._order_panels(snap, render._live_providers(snap), 4),
                         ["deepseek", "opencode"])


class CachedTimestampTests(unittest.TestCase):
    def test_short_marker_for_cached_ts(self):
        self.assertEqual(render._grid_ts({"updated_at": "16:40 (cached)", "_cached": True}), "16:40*")
        self.assertEqual(render._grid_ts({"updated_at": "16:40", "_cached": False}), "16:40")

    def test_cached_ts_does_not_collide_with_ne_title(self):
        # The fixture that actually stresses the reserve bound: both
        # primaries dead → TR = OPENCODE-GO (widest title, ink to ~x253)
        # against the cached ts ('16:40*', ink from ~x255). The all-live
        # fixture put CLAUDE in TR and never reached the body of the old
        # assertion's empty band — it could not fail on its own fixture.
        snap = _full_snap("2+2", live=["deepseek", "opencode"])
        snap["_cached"] = True
        snap["updated_at"] = "16:40 (cached)"
        png = render_image(snap)
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.size, (296, 152))
        px = img.load()
        # Strip edge the renderer reserves (right-aligned 8px ts at W-PAD,
        # reserve = tsw) — recomputed from the code's own rule, not a scan.
        strip_left = render.W - render.PAD - render._tsize(
            render.ImageDraw.Draw(img), "16:40*", render._pixel())[0]
        # Title ink is measured in its bottom rows only (y≥13): the 8px ts
        # ink stops at y=12, so that band is title-only across ALL x — a
        # title leak past the strip is caught by title_right itself, never
        # clamped away. Scanning the ts in the shared rows (6-12) instead
        # caught title ink at x≈248 and compared the title with itself.
        title_right = max(x for x in range(174, render.W)
                          for y in range(13, 18) if px[x, y] < 128)
        ts_zone = [x for x in range(strip_left, render.W)
                   for y in range(2, 18) if px[x, y] < 128]
        self.assertTrue(ts_zone, "refresh-time strip must be present")
        ts_left = min(ts_zone)
        self.assertLess(title_right, ts_left,
                        "top-right quarter title must end before the ts ink")
        self.assertGreater(max(ts_zone), render.W - render.PAD - 8,
                           "ts must stay flush right — a misplaced strip "
                           "would move the collision out of this scan")
        # the fixture must genuinely stress the boundary; if metrics shrink
        # the title this test silently goes vacuous again
        self.assertGreater(title_right, ts_left - 10)
