from __future__ import annotations

import unittest
from datetime import datetime, timezone
from atlas_hub.logic import HEADERS, EXPECTED_TABS, as_bool, assess, parse_utc, values_as_table

NOW = datetime(2026, 11, 6, 19, 0, tzinfo=timezone.utc)


def source_data():
    d = {name: [header.copy()] for name, header in HEADERS.items()}
    d["Control"] += [
        ["execution_mode", "PLANNING", "enum", "LOCKED"],
        ["trading_enabled", False, "boolean", "LOCKED"],
        ["kill_switch", True, "boolean", "LOCKED"],
        ["policy_approval_status", "NOT_APPROVED", "enum", "LOCKED"],
        ["manual_order_approval_required", True, "boolean", "DRAFT"],
        ["allow_margin_short_options", False, "boolean", "LOCKED"],
        ["max_order_notional_usd", 0, "USD", "LOCKED"],
    ]
    d["Universe"].append(["AAPL", "SP100", "REFERENCE_ONLY", "", "", "", ""])
    d["Momentum"].append(["AAPL", "", "", "", "", "", "", "", "", "", "", "", "AWAITING_REFRESH", ""])
    return d


class LogicTests(unittest.TestCase):
    def test_bool(self):
        self.assertIs(as_bool(True), True)
        self.assertIs(as_bool("TRUE"), True)
        self.assertIs(as_bool(False), False)
        self.assertIs(as_bool("no"), False)
        self.assertIsNone(as_bool("perhaps"))

    def test_parsed_z_time(self):
        self.assertEqual(parse_utc("2026-11-06T19:00:00Z"), NOW)
        self.assertIsNone(parse_utc("2026-11-06"))

    def test_blank_row_skipped(self):
        rows = [["code", "value"], ["", "no"], ["X", 5]]
        self.assertEqual(values_as_table(rows, ["code", "value"], "t"), [{"code": "X", "value": 5}])

    def test_schema_fails_closed(self):
        with self.assertRaises(ValueError):
            values_as_table([["wrong"]], ["expected"], "Control")

    def test_healthy_setup_status(self):
        a = assess(source_data(), set(EXPECTED_TABS), NOW)
        self.assertEqual(a.status, "READY_PLANNING")
        self.assertEqual(a.universe_reference, 1)
        self.assertEqual(a.universe_verified, 0)
        self.assertEqual(a.momentum_scored, 0)
        self.assertIn("UNIVERSE_IS_REFERENCE_ONLY", a.alerts)

    def test_missing_tabs_detected(self):
        a = assess(source_data(), {"Control"}, NOW)
        self.assertEqual(a.status, "SCHEMA_BLOCKED")
        self.assertIn("STRUCTURE_MISSING_TABS", a.alerts[0])

    def test_control_tampering_flags_safety_alert(self):
        d = source_data()
        d["Control"][2][1] = True
        a = assess(d, set(EXPECTED_TABS), NOW)
        self.assertEqual(a.status, "SAFETY_ALERT")
        self.assertIn("CONTROL_TRADING_ENABLED_NOT_FALSE", a.alerts)

    def test_kill_switch_cannot_be_ignored(self):
        d = source_data()
        d["Control"][3][1] = False
        a = assess(d, set(EXPECTED_TABS), NOW)
        self.assertEqual(a.status, "SAFETY_ALERT")

    def test_modified_approval_is_alert(self):
        d = source_data()
        d["Control"][4][1] = "APPROVED"
        a = assess(d, set(EXPECTED_TABS), NOW)
        self.assertEqual(a.status, "SAFETY_ALERT")

    def test_leverage_guard_alert(self):
        d = source_data()
        d["Control"][6][1] = True
        a = assess(d, set(EXPECTED_TABS), NOW)
        self.assertEqual(a.status, "SAFETY_ALERT")
        self.assertIn("CONTROL_LEVERAGE_GUARD_MODIFIED", a.alerts)

    def test_positive_order_notional_alert(self):
        d = source_data()
        d["Control"][7][1] = 100
        a = assess(d, set(EXPECTED_TABS), NOW)
        self.assertEqual(a.status, "SAFETY_ALERT")
        self.assertIn("CONTROL_ORDER_NOTIONAL_NOT_ZERO", a.alerts)

    def test_signal_without_verified_universe(self):
        d = source_data()
        d["Signals"].append(["S1", "", "AAPL", "MOM-SP100", "0.1", "BUY", 95, "", "NEW", "", "", "", ""])
        a = assess(d, set(EXPECTED_TABS), NOW)
        self.assertEqual(a.signal_new, 1)
        self.assertIn("NEW_SIGNALS_WITHOUT_VERIFIED_UNIVERSE", a.alerts)

    def test_stale_data_not_counted_as_momentum_current(self):
        d = source_data()
        d["Momentum"][1][6] = 99
        d["Momentum"][1][12] = "STALE"
        self.assertEqual(assess(d, set(EXPECTED_TABS), NOW).momentum_scored, 0)
        d["Momentum"][1][12] = "CURRENT"
        self.assertEqual(assess(d, set(EXPECTED_TABS), NOW).momentum_scored, 1)


if __name__ == "__main__":
    unittest.main()
