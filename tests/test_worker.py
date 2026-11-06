from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

from atlas_hub.config import Settings
from atlas_hub.logic import EXPECTED_TABS
from atlas_hub.runner import HubWorker
from tests.test_logic import source_data, NOW


SETTINGS = Settings(
    sheet_id="1SdF1R4R5SRNvkdLkIxDhcv1ty0-3kXlL-eLVpjMnS00",
    credentials={}, interval_seconds=300, history_minutes=60,
    audit_db_url=None, audit_account_alias="main", audit_max_snapshot_minutes=35,
)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.g = Mock()
        self.g.list_tabs.return_value = {name: i for i, name in enumerate(EXPECTED_TABS)}
        self.g.read_sources.return_value = source_data()

    def test_dry_run_never_writes(self):
        result = HubWorker(self.g, SETTINGS).run_once(now=NOW, dry_run=True, history=True)
        self.assertEqual(result.status, "READY_PLANNING")
        self.g.ensure_health_tab.assert_not_called()
        self.g.publish_health.assert_not_called()
        self.g.append_atlas_v.assert_not_called()

    def test_normal_run_writes_only_monitoring(self):
        result = HubWorker(self.g, SETTINGS).run_once(now=NOW, history=True)
        self.assertEqual(result.status, "READY_PLANNING")
        self.g.ensure_health_tab.assert_called_once()
        self.g.publish_health.assert_called_once()
        self.g.append_atlas_v.assert_not_called()

    def test_optional_database_failure_is_not_fatal(self):
        s = replace(SETTINGS, audit_db_url="postgresql://invalid")
        def fail(*args):
            raise RuntimeError("no database")
        result = HubWorker(self.g, s, audit_reader=fail).run_once(now=NOW)
        self.assertEqual(result.status, "DEGRADED")
        self.assertEqual(result.audit_status, "ERROR")
        self.g.publish_health.assert_called_once()

    def test_no_db_write_in_source(self):
        import inspect
        import atlas_hub.audit
        code = inspect.getsource(atlas_hub.audit)
        self.assertIn("default_transaction_read_only=on", code)
        self.assertNotIn("INSERT INTO", code)
        self.assertNotIn("DELETE FROM", code)

    def test_empty_database_snapshot_is_reported(self):
        s = replace(SETTINGS, audit_db_url="postgresql://unused")
        def response(*args):
            return {
                "observed_at_utc": "2026-11-06T19:00:00Z", "account_alias":"main",
                "collector_health":"NO_SNAPSHOTS", "historical_coverage":"UNKNOWN",
                "reconciliation_status":"UNKNOWN", "snapshot_utc":"",
                "alerts":["AUDITOR_HAS_NO_ACCOUNT_SNAPSHOTS"], "notes":"No data"
            }
        result = HubWorker(self.g, s, audit_reader=response).run_once(now=NOW, history=True)
        self.assertEqual(result.audit_status, "NO_SNAPSHOTS")
        self.assertEqual(result.status, "DEGRADED")
        self.g.append_atlas_v.assert_called_once()

if __name__ == "__main__":
    unittest.main()
