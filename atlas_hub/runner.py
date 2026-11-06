"""Single-cycle orchestration. No trading calls, no Alpaca credentials."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import VERSION
from .audit import read_audit
from .config import Settings
from .logic import Assessment, assess
from .sheets import SheetGateway

LOG = logging.getLogger("atlas-hub")
UTC = timezone.utc


class HubWorker:
    def __init__(self, gateway: SheetGateway, settings: Settings, audit_reader=read_audit):
        self.gateway = gateway
        self.settings = settings
        self.audit_reader = audit_reader

    def run_once(self, *, now: datetime | None = None, dry_run: bool = False, history: bool = False) -> Assessment:
        now = now or datetime.now(UTC)
        tabs = self.gateway.list_tabs()
        values = self.gateway.read_sources()
        state = assess(values, set(tabs), now)
        audit_data: dict[str, Any] | None = None
        if self.settings.audit_db_url:
            try:
                audit_data = self.audit_reader(
                    self.settings.audit_db_url,
                    self.settings.audit_account_alias,
                    now, self.settings.audit_max_snapshot_minutes,
                )
                state.audit_status = audit_data["collector_health"]
                if audit_data["reconciliation_status"] in ("STALE", "MISSING", "FUTURE_TIMESTAMP"):
                    state.audit_status = "STALE"
                state.audit_snapshot = audit_data["snapshot_utc"]
                state.alerts.extend(audit_data["alerts"])
            except Exception as exc:
                # Do not log exception messages: they may include a database URI.
                state.audit_status = "ERROR"
                state.alerts.append("ATLAS_V_DATABASE_READ_FAILED:" + type(exc).__name__)
                LOG.warning("Optional read-only ATLAS V audit query failed: %s", type(exc).__name__)
        if dry_run:
            LOG.info("DRY RUN: status=%s universe_reference=%s audit_status=%s",
                     state.status, state.universe_reference, state.audit_status)
            return state

        # The hub may record that a safety gate is broken; it never acts on
        # the gate by submitting a trade or changing any user controls.
        self.gateway.ensure_health_tab(tabs)
        self.gateway.publish_health(state, VERSION, history=history)
        if history and audit_data and state.workbook_ok:
            try:
                self.gateway.append_atlas_v(audit_data)
            except Exception as exc:
                # Reporting is optional; health collection is not blocked.
                LOG.warning("ATLAS V sheet mirror unavailable: %s", type(exc).__name__)
        LOG.info("ATLAS_HUB_HEALTH status=%s sheet_ok=%s mode=%s kill_switch=%s "
                 "universe_reference=%s universe_verified=%s signals_new=%s audit=%s alerts=%s",
                 state.status, state.workbook_ok, state.execution_mode,
                 state.kill_switch, state.universe_reference, state.universe_verified,
                 state.signal_new, state.audit_status, ",".join(state.alerts)[:500])
        return state
