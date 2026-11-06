"""Pure deterministic validation and status logic. No Google or broker calls."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc

HEADERS = {
    "Control": ["parameter", "value", "value_type", "approval"],
    "Strategies": ["strategy_id", "version", "strategy_name", "universe_id", "entry_rule", "accumulation_rule", "exit_rule", "status", "deployment", "created_on", "notes"],
    "Universe": ["symbol", "universe_id", "membership_status", "source_snapshot_utc", "current_membership_check", "source_url", "notes"],
    "Momentum": ["symbol", "close_usd", "sma200_usd", "sma50_usd", "pos_52week_0to1", "avg_dollar_vol_musd", "legacy_v2_score", "eligible", "gap_vs_sma50_pct", "gap_vs_sma200_pct", "prices_asof_utc", "source_run_id", "data_state", "source_url"],
    "Research": ["research_id", "run_id", "engine", "observed_utc", "symbol", "asset_class", "thesis", "confidence", "source_urls", "review_status", "notes"],
    "Signals": ["signal_id", "observed_utc", "symbol", "strategy_id", "strategy_version", "signal_type", "score", "source_run_id", "status", "expires_utc", "universe_check_utc", "evidence_url", "notes"],
    "Accumulation": ["position_key", "symbol", "strategy_id", "first_buy_utc", "initial_fill_usd", "lowest_observed_usd", "last_buy_price_usd", "last_buy_utc", "add_count", "max_adds", "next_add_threshold_usd", "committed_cost_usd", "remaining_budget_usd", "membership_verified_utc", "status", "notes"],
    "Positions": ["position_key", "account_alias", "symbol", "quantity", "avg_entry_usd", "mark_usd", "market_value_usd", "unrealized_pl_usd", "unrealized_pl_pct", "position_state", "strategy_id", "snapshot_utc", "broker_source"],
    "Orders": ["order_id", "client_order_id", "signal_id", "strategy_id", "symbol", "side", "order_type", "quantity", "notional_usd", "status", "submitted_utc", "filled_utc", "avg_fill_usd", "broker_ref", "reconciliation"],
    "ATLAS V": ["check_id", "report_utc", "account_alias", "report_period", "collector_health", "historical_coverage", "reconciliation_status", "critical_alerts", "gross_realized_estimate_usd", "net_return_certified", "evidence_ref", "notes"],
    "Data Contract": ["tab", "data_owner", "writer", "primary_key", "update_pattern", "integration_rule"],
    "Change Log": ["change_id", "effective_date", "change_type", "description", "system_mode", "approved_by", "notes"],
}
EXPECTED_TABS = {
    "Overview", "Control", "Strategies", "Universe", "Momentum", "Research", "Signals",
    "Accumulation", "Positions", "Orders", "ATLAS V", "Data Contract", "Change Log",
}


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if str(value).strip().lower() in ("true", "1", "yes", "on"):
        return True
    if str(value).strip().lower() in ("false", "0", "no", "off"):
        return False
    return None


def parse_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        d = value
    elif isinstance(value, str) and value.strip():
        try:
            d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return d.astimezone(UTC) if d.tzinfo else None


def iso(now: datetime) -> str:
    return now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def values_as_table(rows: list[list[Any]], expected: list[str], tab: str) -> list[dict[str, Any]]:
    if not rows or rows[0][:len(expected)] != expected:
        raise ValueError(f"{tab} headers do not match the ATLAS Hub schema; will not write")
    results = []
    for row in rows[1:]:
        if not row or row[0] in ("", None):
            continue
        results.append({col: row[i] if i < len(row) else "" for i, col in enumerate(expected)})
    return results


@dataclass
class Assessment:
    observed_at: datetime
    workbook_ok: bool
    execution_mode: str = "UNKNOWN"
    kill_switch: bool | None = None
    trading_enabled: bool | None = None
    universe_reference: int = 0
    universe_verified: int = 0
    momentum_scored: int = 0
    signal_new: int = 0
    positions_open: int = 0
    alerts: list[str] = field(default_factory=list)
    audit_status: str = "NOT_CONFIGURED"
    audit_snapshot: str = ""

    @property
    def status(self) -> str:
        if not self.workbook_ok or any(x.startswith("STRUCTURE_") for x in self.alerts):
            return "SCHEMA_BLOCKED"
        if any(x.startswith("CONTROL_") for x in self.alerts):
            return "SAFETY_ALERT"
        if self.audit_status in ("ERROR", "STALE", "NO_SNAPSHOTS") or any(
                x.startswith("AUDIT_ERRORS_24H") for x in self.alerts):
            return "DEGRADED"
        return "READY_PLANNING"


def assess(values: dict[str, list[list[Any]]], tabs: set[str], now: datetime) -> Assessment:
    out = Assessment(observed_at=now, workbook_ok=True)
    missing = sorted(EXPECTED_TABS - tabs)
    if missing:
        out.workbook_ok = False
        out.alerts.append("STRUCTURE_MISSING_TABS:" + ",".join(missing))
        return out
    records: dict[str, list[dict[str, Any]]] = {}
    for tab, header in HEADERS.items():
        try:
            records[tab] = values_as_table(values.get(tab, []), header, tab)
        except ValueError:
            out.workbook_ok = False
            out.alerts.append("STRUCTURE_HEADER_MISMATCH:" + tab)
    if not out.workbook_ok:
        return out

    control = {str(r["parameter"]).strip(): r["value"] for r in records["Control"]}
    out.execution_mode = str(control.get("execution_mode", "UNKNOWN")).strip().upper()
    out.kill_switch = as_bool(control.get("kill_switch"))
    out.trading_enabled = as_bool(control.get("trading_enabled"))
    if out.execution_mode != "PLANNING":
        out.alerts.append("CONTROL_NOT_IN_PLANNING_MODE")
    if out.kill_switch is not True:
        out.alerts.append("CONTROL_KILL_SWITCH_NOT_TRUE")
    if out.trading_enabled is not False:
        out.alerts.append("CONTROL_TRADING_ENABLED_NOT_FALSE")
    if str(control.get("policy_approval_status", "")).strip().upper() != "NOT_APPROVED":
        out.alerts.append("CONTROL_POLICY_APPROVAL_MODIFIED")
    if as_bool(control.get("allow_margin_short_options")) is not False:
        out.alerts.append("CONTROL_LEVERAGE_GUARD_MODIFIED")
    if as_bool(control.get("manual_order_approval_required")) is not True:
        out.alerts.append("CONTROL_MANUAL_ORDER_APPROVAL_MODIFIED")
    try:
        if float(control.get("max_order_notional_usd", "nan")) != 0:
            out.alerts.append("CONTROL_ORDER_NOTIONAL_NOT_ZERO")
    except (TypeError, ValueError):
        out.alerts.append("CONTROL_ORDER_NOTIONAL_INVALID")

    universe = records["Universe"]
    out.universe_reference = sum(r["membership_status"] == "REFERENCE_ONLY" for r in universe)
    out.universe_verified = sum(r["membership_status"] == "VERIFIED_MEMBER" for r in universe)
    momentum = records["Momentum"]
    out.momentum_scored = sum(isinstance(r["legacy_v2_score"], (float, int)) and r["data_state"] == "CURRENT" for r in momentum)
    out.signal_new = sum(str(r["status"]).upper() == "NEW" for r in records["Signals"])
    out.positions_open = sum(str(r["position_state"]).upper() == "OPEN" for r in records["Positions"])

    # These are informational and entirely expected for an unconnected, draft workbook.
    # They are not considered to be a failure of the Hub worker.
    if out.universe_reference and not out.universe_verified:
        out.alerts.append("UNIVERSE_IS_REFERENCE_ONLY")
    if not out.momentum_scored:
        out.alerts.append("MOMENTUM_AWAITING_FRESH_DATA")
    if out.signal_new and out.universe_verified == 0:
        out.alerts.append("NEW_SIGNALS_WITHOUT_VERIFIED_UNIVERSE")
    return out
