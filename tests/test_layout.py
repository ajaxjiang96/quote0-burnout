"""Layout engine tests: planning/selection (pure) + grid render smoke + seams.

Selection is LIVE-based: providers whose snapshot is ok get cells; dead
providers (no auth, timeouts) are hidden. Auto maps live count → layout.
Reuses the mock snapshot helpers from test_render.py.
"""

import io
import unittest

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

    def test_explicit_cramped_uses_second_panel_preference(self):
        snap = _full_snap("1+1", live=["codex", "deepseek", "opencode"])
        mode, jobs = render._plan_layout(snap)
        self.assertEqual([name for name, _ in jobs], ["codex", "opencode"])
        snap["second_panel"] = "deepseek"
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


if __name__ == "__main__":
    unittest.main()


class CachedTimestampTests(unittest.TestCase):
    def test_short_marker_for_cached_ts(self):
        self.assertEqual(render._grid_ts({"updated_at": "16:40 (cached)", "_cached": True}), "16:40*")
        self.assertEqual(render._grid_ts({"updated_at": "16:40", "_cached": False}), "16:40")

    def test_cached_ts_does_not_collide_with_ne_title(self):
        snap = _full_snap("2+2")
        snap["_cached"] = True
        snap["updated_at"] = "16:40 (cached)"
        png = render_image(snap)
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.size, (296, 152))
        px = img.load()
        # the top-right quarter (CLAUDE) title must not run under the ts:
        # the strip between the title's right edge and the ts is reserved
        self.assertFalse(
            any(px[x, y] < 128 for x in range(244, 250) for y in range(2, 18)),
            "top-right quarter title must not collide with the cached timestamp")
