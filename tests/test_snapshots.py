"""Snapshot-builder unit tests for all providers (pure functions, no network)."""

import unittest
from datetime import datetime, timezone

import display


class CodexSnapshotTests(unittest.TestCase):
    def test_not_ok(self):
        sn = display.build_codex_snapshot({"ok": False, "status": "no auth"})
        self.assertFalse(sn["ok"])
        self.assertEqual(sn["status"], "error")
        self.assertEqual(sn["raw_status"], "no auth")

    def test_missing_rate_limit_is_null_safe(self):
        # OAI can return usage without rate_limit at all (see backport fix #5)
        sn = display.build_codex_snapshot({"ok": True, "raw": {}})
        self.assertTrue(sn["ok"])
        self.assertIsNone(sn["short_used_percent"])
        self.assertIsNone(sn["long_used_percent"])
        self.assertEqual(sn["status"], "unknown")

    def test_single_window_derives_label_from_seconds(self):
        raw = {"rate_limit": {"primary_window": {"used_percent": 11, "limit_window_seconds": 604800}}}
        sn = display.build_codex_snapshot({"ok": True, "raw": raw})
        self.assertEqual(sn["short_label"], "Week")
        self.assertIsNone(sn["long_used_percent"])
        self.assertIsNone(sn["long_label"])
        self.assertEqual(sn["short_used_percent"], 11)
        # status falls back to the only window for hot/warn display
        self.assertEqual(sn["status"], "ok")

    def test_single_window_without_seconds_uses_now_label(self):
        raw = {"rate_limit": {"primary_window": {"used_percent": 90}}}
        sn = display.build_codex_snapshot({"ok": True, "raw": raw})
        self.assertEqual(sn["short_label"], "Now")
        self.assertEqual(sn["status"], "hot")

    def test_secondary_window_keeps_week(self):
        raw = {
            "rate_limit": {
                "primary_window": {"used_percent": 20},
                "secondary_window": {"used_percent": 40},
            }
        }
        sn = display.build_codex_snapshot({"ok": True, "raw": raw})
        self.assertEqual(sn["long_label"], "Week")
        self.assertEqual(sn["long_used_percent"], 40)


class DeepSeekWindowTests(unittest.TestCase):
    def _window(self, hour, minute=0, currency="USD"):
        now = datetime(2026, 8, 21, hour, minute, tzinfo=timezone.utc)
        return display.deepseek_window(now_utc=now, currency=currency)

    def test_peak_01_to_04(self):
        w = self._window(2, 30)
        self.assertEqual(w["window"], "PEAK")
        self.assertEqual(w["factor"], 1.0)
        self.assertEqual(w["next_window"], "OFF")
        self.assertEqual(w["countdown"], "1h30m")

    def test_offpeak_04_to_06(self):
        w = self._window(5)
        self.assertEqual(w["window"], "OFF")
        self.assertEqual(w["factor"], 0.5)
        self.assertEqual(w["next_window"], "PEAK")
        self.assertEqual(w["countdown"], "1h")

    def test_peak_06_to_10(self):
        w = self._window(8)
        self.assertEqual(w["window"], "PEAK")
        self.assertEqual(w["next_window"], "OFF")

    def test_overnight_offpeak_ends_next_day(self):
        w = self._window(13)
        self.assertEqual(w["window"], "OFF")
        self.assertEqual(w["next_window"], "PEAK")
        self.assertEqual(w["countdown"], "12h")

    def test_midnight_edges(self):
        self.assertEqual(self._window(0)["window"], "OFF")
        self.assertEqual(self._window(1)["window"], "PEAK")
        self.assertEqual(self._window(10)["window"], "OFF")

    def test_cny_prices(self):
        w = self._window(3, currency="CNY")
        self.assertEqual(w["price_in"], 3.0)
        self.assertEqual(w["price_out"], 9.0)

    def test_vision_exp_aliases_flash(self):
        w = self._window(3)
        self.assertEqual(w["model"], "deepseek-v4-flash")
        self.assertEqual(
            display.DEEPSEEK_PRICING["deepseek-v4-flash-vision-exp"],
            display.DEEPSEEK_PRICING["deepseek-v4-flash"],
        )

    def test_countdown_format(self):
        self.assertEqual(display._countdown(8520), "2h22m")
        self.assertEqual(display._countdown(2700), "45m")
        self.assertEqual(display._countdown(54000), "15h")
        self.assertEqual(display._countdown(3600), "1h")

    def test_balance_status_thresholds(self):
        self.assertEqual(display._balance_status(None, None), "unknown")
        self.assertEqual(display._balance_status(5.0, None), "warn")
        self.assertEqual(display._balance_status(2.0, None), "hot")
        self.assertEqual(display._balance_status(20.0, False), "hot")
        self.assertEqual(display._balance_status(20.0, True), "ok")

    def test_snapshot_coerces_amount_and_sets_badge_fields(self):
        sn = display.build_deepseek_snapshot({"ok": True, "amount": "18.42", "currency": "CNY", "available": True})
        self.assertEqual(sn["balance"], 18.42)
        self.assertEqual(sn["symbol"], "¥")
        self.assertIn(sn["window"], ("PEAK", "OFF"))
        self.assertEqual(sn["price_out"], 9.0 if sn["window"] == "PEAK" else 4.5)
        self.assertIsNotNone(sn["countdown"])


class OpenCodeSnapshotTests(unittest.TestCase):
    def test_no_key(self):
        sn = display.build_opencode_snapshot({"ok": False, "status": "no key"})
        self.assertFalse(sn["ok"])
        self.assertEqual(sn["raw_status"], "no key")

    def test_windows_normalized(self):
        raw = {"usage": {
            "rolling": {"percent": "6", "resetsAt": None, "status": "ok"},
            "weekly": {"percent": 33},
            "monthly": {},
        }}
        sn = display.build_opencode_snapshot({"ok": True, "raw": raw})
        self.assertTrue(sn["ok"])
        self.assertEqual(sn["rolling"]["used_percent"], 6)
        self.assertEqual(sn["weekly"]["used_percent"], 33)
        self.assertIsNone(sn["monthly"]["used_percent"])
        self.assertEqual(sn["short_used_percent"], 6)
        self.assertEqual(sn["long_used_percent"], 33)
        self.assertEqual(sn["status"], "ok")

    def test_status_from_max_percent(self):
        raw = {"usage": {"rolling": {"percent": 75}}}
        sn = display.build_opencode_snapshot({"ok": True, "raw": raw})
        self.assertEqual(sn["status"], "warn")


class SecondPanelResolutionTests(unittest.TestCase):
    def _snap(self, ok=True):
        return {"ok": ok, "status": "ok" if ok else "no key"}

    def test_auto_prefers_opencode(self):
        display.SECOND_PANEL = "auto"
        self.assertEqual(display._resolve_second_panel(self._snap(True), self._snap(True)), "opencode")

    def test_auto_falls_back_to_deepseek(self):
        display.SECOND_PANEL = "auto"
        self.assertEqual(display._resolve_second_panel(self._snap(True), self._snap(False)), "deepseek")

    def test_auto_none_when_neither(self):
        display.SECOND_PANEL = "auto"
        self.assertEqual(display._resolve_second_panel(self._snap(False), self._snap(False)), "none")

    def test_forced_modes(self):
        display.SECOND_PANEL = "deepseek"
        self.assertEqual(display._resolve_second_panel(self._snap(True), self._snap(True)), "deepseek")
        display.SECOND_PANEL = "opencode"
        self.assertEqual(display._resolve_second_panel(self._snap(True), self._snap(True)), "opencode")


if __name__ == "__main__":
    unittest.main()
