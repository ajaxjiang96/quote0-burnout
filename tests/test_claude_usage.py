import io
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image

import display
import render
from render import render_image


class ClaudeUsageSnapshotTests(unittest.TestCase):
    def test_parses_claude_cli_usage_output(self):
        raw = display.parse_claude_cli_usage(
            "\n".join([
                "You are currently using your subscription to power your Claude Code usage",
                "Current session: 59% used · resets Jul 2 at 12:29pm (Asia/Shanghai)",
                "Current week (all models): 12% used · resets Jul 2 at 1:59pm (Asia/Shanghai)",
                "Current week (Fable): 18% used · resets Jul 2 at 1:59pm (Asia/Shanghai)",
            ]),
            now=datetime(2026, 7, 2, 9, 22, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(raw["five_hour"]["utilization"], 59)
        self.assertEqual(raw["seven_day"]["utilization"], 12)
        self.assertTrue(raw["five_hour"]["resets_at"].startswith("2026-07-02T12:29:00"))

    def test_parses_claude_cli_reset_without_minutes(self):
        raw = display.parse_claude_cli_usage(
            "Current week (all models): 13% used · resets Jul 2 at 2pm (Asia/Shanghai)",
            now=datetime(2026, 7, 2, 9, 28, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(raw["seven_day"]["utilization"], 13)
        self.assertTrue(raw["seven_day"]["resets_at"].startswith("2026-07-02T14:00:00"))

    def test_builds_claude_snapshot_from_oauth_usage_windows(self):
        snapshot = display.build_claude_snapshot({
            "ok": True,
            "raw": {
                "five_hour": {"utilization": 42, "resets_at": None},
                "seven_day": {"utilization": 61, "resets_at": None},
            },
        })

        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["short_label"], "5h")
        self.assertEqual(snapshot["short_used_percent"], 42)
        self.assertEqual(snapshot["long_label"], "Week")
        self.assertEqual(snapshot["long_used_percent"], 61)
        self.assertEqual(snapshot["status"], "ok")

    def test_builds_claude_error_snapshot_when_auth_is_missing(self):
        snapshot = display.build_claude_snapshot({"ok": False, "status": "no auth"})

        self.assertFalse(snapshot["ok"])
        self.assertEqual(snapshot["raw_status"], "no auth")
        self.assertEqual(snapshot["short_label"], "?")
        self.assertIsNone(snapshot["short_used_percent"])


class ClaudeRenderTests(unittest.TestCase):
    def test_claude_logo_asset_matches_codex_logo_contract(self):
        self.assertEqual(render.LOGO_CLAUDE.size, render.LOGO_CODEX.size)
        self.assertEqual(render.LOGO_CLAUDE.mode, "1")

    def test_renders_claude_panel_in_dashboard_snapshot(self):
        png = render_image({
            "codex": {
                "ok": True,
                "short_label": "5h",
                "short_used_percent": 26,
                "short_reset": "3h44m",
                "long_label": "Week",
                "long_used_percent": 19,
                "long_reset": "5d3h",
                "status": "ok",
            },
            "claude": {
                "ok": True,
                "short_label": "5h",
                "short_used_percent": 42,
                "short_reset": "2h13m",
                "long_label": "Week",
                "long_used_percent": 61,
                "long_reset": "3d4h",
                "status": "ok",
            },
            "updated_at": "16:40",
        })

        image = Image.open(io.BytesIO(png))
        self.assertEqual(image.size, (296, 152))
        self.assertEqual(image.mode, "1")
        self.assertGreater(len(png), 500)


if __name__ == "__main__":
    unittest.main()
