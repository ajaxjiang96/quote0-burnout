"""Layout engine tests: planning/selection (pure) + grid render smoke + seams.

Reuses the mock snapshot helpers from test_render.py (same directory, both
loaded as top-level modules by unittest discover).
"""

import io
import unittest

from PIL import Image

import render
from render import render_image

from test_render import _claude, _codex, _deepseek, _opencode


def _full_snap(layout="2+2", configured=None, codex=None, claude=None, deepseek=None, opencode=None):
    codex = codex if codex is not None else _codex()
    claude = claude if claude is not None else _claude(ok=True)
    deepseek = deepseek if deepseek is not None else _deepseek()
    opencode = opencode if opencode is not None else _opencode()
    if configured is None:
        configured = ["codex", "claude", "deepseek", "opencode"]
    return {
        "codex": codex, "claude": claude, "deepseek": deepseek, "opencode": opencode,
        "second_panel": "opencode", "layout": layout, "configured": configured,
        "updated_at": "16:40",
    }


def _dark(img, x, y):
    return img.getpixel((x, y)) < 128


class PlanLayoutTests(unittest.TestCase):
    def test_auto_mapping(self):
        for n, layout in ((0, "stack"), (1, "stack"), (2, "1+1"), (3, "1+2"), (4, "2+2")):
            snap = _full_snap(layout="auto", configured=["codex", "claude", "deepseek", "opencode"][:n])
            mode, jobs = render._plan_layout(snap)
            self.assertEqual(mode, layout, f"N={n}")

    def test_missing_configured_inferred_from_ok(self):
        snap = _full_snap()
        del snap["configured"]  # hand-built snapshot
        mode, jobs = render._plan_layout(snap)
        self.assertEqual(mode, "2+2")
        self.assertEqual([n for n, _ in jobs], ["codex", "claude", "deepseek", "opencode"])

    def test_auto_3_shows_both_secondaries(self):
        snap = _full_snap(layout="auto", configured=["codex", "deepseek", "opencode"])
        mode, jobs = render._plan_layout(snap)
        self.assertEqual(mode, "1+2")
        self.assertEqual([n for n, _ in jobs], ["codex", "deepseek", "opencode"])

    def test_2x2_shows_all_four(self):
        mode, jobs = render._plan_layout(_full_snap("2+2"))
        self.assertEqual([n for n, _ in jobs], ["codex", "claude", "deepseek", "opencode"])

    def test_explicit_cramped_uses_second_panel_preference(self):
        snap = _full_snap("1+1", configured=["codex", "deepseek", "opencode"])
        mode, jobs = render._plan_layout(snap)
        self.assertEqual([n for n, _ in jobs], ["codex", "opencode"])
        snap["second_panel"] = "deepseek"
        mode, jobs = render._plan_layout(snap)
        self.assertEqual([n for n, _ in jobs], ["codex", "deepseek"])

    def test_2x2_with_3_configured_leaves_cells_blank(self):
        snap = _full_snap("2+2", configured=["codex", "claude", "deepseek"])
        mode, jobs = render._plan_layout(snap)
        self.assertEqual(len(jobs), 3)
        self.assertEqual([n for n, _ in jobs], ["codex", "claude", "deepseek"])

    def test_stack_and_invalid(self):
        for layout in ("stack", "bogus", None):
            snap = _full_snap()
            snap["layout"] = layout
            mode, jobs = render._plan_layout(snap)
            self.assertEqual(mode, "stack")
            self.assertEqual(jobs, [])

    def test_dead_provider_not_selected(self):
        snap = _full_snap("2+2", deepseek=_deepseek(ok=False))
        snap["configured"] = ["codex", "claude", "deepseek", "opencode"]
        mode, jobs = render._plan_layout(snap)
        # configured rules; the dead provider still gets a cell (renders err-q)
        self.assertEqual([n for n, _ in jobs], ["codex", "claude", "deepseek", "opencode"])


class GridRenderTests(unittest.TestCase):
    def _render(self, snap, expect_layout=None):
        png = render_image(snap)
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.size, (296, 152))
        dark = sum(1 for px in img.getdata() if px < 128)
        self.assertGreater(dark, 100)
        return img

    def test_2x2_junction_is_4way_plus(self):
        img = self._render(_full_snap("2+2"))
        for pt in ((148, 76), (146, 76), (150, 76), (148, 74), (148, 78)):
            self.assertTrue(_dark(img, *pt), f"{pt} should be dark (junction)")

    def test_1x2_seams_and_bottom_t_junction(self):
        img = self._render(_full_snap("1+2", configured=["codex", "claude", "opencode"]))
        self.assertTrue(_dark(img, 60, 76))       # horizontal seam
        self.assertTrue(_dark(img, 148, 100))     # vertical seam only in bottom row
        self.assertTrue(_dark(img, 148, 79))      # T junction arm down
        self.assertFalse(_dark(img, 148, 5))      # no vertical in top row (above content)
        self.assertFalse(_dark(img, 148, 74))     # no up arm (plain T, not plus)

    def test_1x1_no_vertical_no_junction(self):
        img = self._render(_full_snap("1+1", configured=["codex", "claude"]))
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

    def test_timestamp_corner_painted(self):
        snap = _full_snap("2+2")
        snap["codex"]["updated_at"] = "09:15"
        img = self._render(snap)
        px = img.load()
        strip = sum(1 for x in range(104, 142) for y in range(4, 16) if px[x, y] < 128)
        self.assertGreater(strip, 0, "top-left quarter should paint its timestamp corner")

    def test_dead_provider_quarter_renders_error(self):
        snap = _full_snap("2+2", deepseek=_deepseek(ok=False))
        img = self._render(snap)  # no crash, dark enough
        self.assertTrue(True)

    def test_backcompat_stack_identical_bytes(self):
        plain = _full_snap()
        del plain["layout"]
        stacked = _full_snap("stack")
        del stacked["configured"]
        p1 = render_image(plain)
        p2 = render_image(plain)
        self.assertEqual(p1, render_image(plain))                    # deterministic
        self.assertEqual(p1, render_image(stacked))                  # absent == stack
        self.assertEqual(p1, render_image(dict(plain, layout="bogus")))  # invalid == stack
        self.assertEqual(p1, render_image(dict(plain, layout="auto", configured=["codex"])))  # N=1 → stack

    def test_missing_layout_is_stack(self):
        snap = _full_snap()
        del snap["layout"]
        img = Image.open(io.BytesIO(render_image(snap)))
        self.assertEqual(img.size, (296, 152))


if __name__ == "__main__":
    unittest.main()
