from __future__ import annotations

import unittest
from unittest.mock import Mock

from atlas_hub.sheets import _last_col, HEALTH_HEADER, SheetGateway
from tests.test_logic import source_data, NOW
from atlas_hub.logic import assess, EXPECTED_TABS


class SheetsTests(unittest.TestCase):
    def test_a1_col_names(self):
        self.assertEqual(_last_col(4), "D")
        self.assertEqual(_last_col(12), "L")
        self.assertEqual(_last_col(26), "Z")
        self.assertEqual(_last_col(27), "AA")

    def test_health_has_15_fields(self):
        self.assertEqual(len(HEALTH_HEADER), 15)

    def test_refuses_to_overwrite_unknown_health_tab(self):
        mock = Mock()
        mock.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {"values": [["wrong", "owner"]]}
        g = SheetGateway(mock, "a-sheet")
        with self.assertRaises(RuntimeError):
            g.ensure_health_tab({"Hub Health": 22})
        mock.spreadsheets.return_value.values.return_value.update.assert_not_called()

    def test_current_health_row_updates_only_hub_health(self):
        mock = Mock()
        g = SheetGateway(mock, "a-sheet")
        state = assess(source_data(), set(EXPECTED_TABS), NOW)
        g.publish_health(state, "1.0.0", history=False)
        kwargs = mock.spreadsheets.return_value.values.return_value.update.call_args.kwargs
        self.assertEqual(kwargs["range"], "'Hub Health'!A2:O2")
        self.assertEqual(kwargs["body"]["values"][0][2], "READY_PLANNING")
        mock.spreadsheets.return_value.values.return_value.append.assert_not_called()


if __name__ == "__main__":
    unittest.main()
