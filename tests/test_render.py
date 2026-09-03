"""Render smoke tests: every supported layout combination renders without
crash at 296x152 and produces a sensible bitmap (monochrome, non-empty)."""

import io
import unittest

from PIL import Image

from render import render_image


def _codex(single=False):
    if single:
        return {"ok": True, "short_label": "Week", "short_used_percent": 11,
                "short_reset": "4d22h", "long_label": None,
                "long_used_percent": None, "long_reset": None, "status": "ok"}
    return {"ok": True, "short_label": "5h", "short_used_percent": 72,
            "short_reset": "2h13m", "long_label": "Week",
            "long_used_percent": 41, "long_reset": "123h3m", "status": "ok"}


def _claude(ok=False, auth=True):
    if not auth:
        return {"ok": False, "status": "error", "raw_status": "no auth"}
    if not ok:
        return {"ok": False, "status": "error", "raw_status": "no token"}
    return {"ok": True, "short_label": "5h", "short_used_percent": 42,
            "short_reset": "2h13m", "long_label": "Week",
            "long_used_percent": 61, "long_reset": "3d4h", "status": "ok"}


def _opencode():
    return {"ok": True, "rolling": {"used_percent": 70, "reset": "42m"},
            "weekly": {"used_percent": 33, "reset": "3d18h"},
            "monthly": {"used_percent": 16, "reset": "16d22h"},
            "short_label": "5h", "short_used_percent": 70, "short_reset": "42m",
            "long_label": "Week", "long_used_percent": 33, "long_reset": "3d18h",
            "status": "ok", "raw_status": ""}


def _deepseek(ok=True):
    if not ok:
        return {"ok": False, "status": "error", "raw_status": "no key"}
    return {"ok": True, "balance": 18.42, "currency": "USD", "symbol": "$",
            "status": "ok", "model": "deepseek-v4-flash", "window": "OFF",
            "factor": 0.5, "price_in": 0.22, "price_out": 0.66,
            "ends_in": 6600, "countdown": "1h50m", "next_window": "PEAK"}


class RenderSmokeTests(unittest.TestCase):
    def _render(self, snap):
        png = render_image(snap)
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.size, (296, 152))
        dark = sum(1 for px in img.getdata() if px < 128)
        self.assertGreater(dark, 100, "render should draw content")
        return img

    def test_single_window_codex_with_opencode_full_panel(self):
        # the user's real setup: Claude unauth -> hidden, OpenCode full 3 rows
        snap = {"codex": _codex(single=True), "claude": _claude(auth=False),
                "deepseek": _deepseek(ok=False), "opencode": _opencode(),
                "second_panel": "opencode", "updated_at": "13:30"}
        self._render(snap)

    def test_three_panels_compact_opencode(self):
        snap = {"codex": _codex(), "claude": _claude(),
                "deepseek": _deepseek(ok=False), "opencode": _opencode(),
                "second_panel": "opencode", "updated_at": "13:30"}
        self._render(snap)

    def test_deepseek_second_panel(self):
        snap = {"codex": _codex(single=True), "claude": _claude(auth=False),
                "deepseek": _deepseek(), "opencode": _opencode(),
                "second_panel": "deepseek", "updated_at": "13:30"}
        self._render(snap)

    def test_only_codex(self):
        snap = {"codex": _codex(single=True), "claude": _claude(auth=False),
                "deepseek": _deepseek(ok=False),
                "opencode": {"ok": False, "status": "error", "raw_status": "no key"},
                "second_panel": "none", "updated_at": "13:30"}
        self._render(snap)

    def test_nothing_renders_but_does_not_crash(self):
        snap = {"codex": {"ok": False, "status": "error", "raw_status": "no auth"},
                "claude": _claude(auth=False),
                "deepseek": _deepseek(ok=False),
                "opencode": {"ok": False, "status": "error", "raw_status": "no key"},
                "second_panel": "none", "updated_at": "13:30"}
        png = render_image(snap)
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.size, (296, 152))

    def test_unknown_second_panel_falls_back_to_ok_provider(self):
        snap = {"codex": _codex(single=True), "claude": _claude(auth=False),
                "deepseek": _deepseek(ok=False), "opencode": _opencode(),
                "second_panel": "bogus", "updated_at": "13:30"}
        # resolution falls back to opencode (the only ok second provider)
        self._render(snap)


if __name__ == "__main__":
    unittest.main()
