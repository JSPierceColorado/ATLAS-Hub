"""Optional, strictly SELECT-only ATLAS V PostgreSQL status mirror.

ATLAS V still owns its audit schema and calculations. This module never migrates,
updates, or inserts into the database; it does not report certified returns.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .logic import iso, parse_utc

UTC = timezone.utc


def _status_for_time(value: datetime | None, now: datetime, max_age_minutes: int) -> str:
    if value is None:
        return "MISSING"
    age = (now - value).total_seconds()
    if age < -300:
        return "FUTURE_TIMESTAMP"
    return "RECENT" if age <= max_age_minutes * 60 else "STALE"


def read_audit(db_url: str, account_alias: str, now: datetime, max_age_minutes: int) -> dict:
    import psycopg

    # The connection is intentionally constrained to read-only transactions,
    # even if the configured role has broader permissions. A read-only DB role
    # remains strongly recommended and is described in README.md.
    with psycopg.connect(
        db_url,
        autocommit=False,
        connect_timeout=12,
        options="-c default_transaction_read_only=on -c statement_timeout=10000",
        application_name="atlas_hub_read_only",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT account_id,captured_at
                           FROM atlas_accounts ORDER BY captured_at DESC LIMIT 1""")
            latest = cur.fetchone()
            if latest is None:
                return {
                    "observed_at_utc": iso(now), "account_alias": account_alias,
                    "collector_health": "NO_SNAPSHOTS", "historical_coverage": "UNKNOWN",
                    "reconciliation_status": "UNKNOWN", "snapshot_utc": "",
                    "alerts": ["AUDITOR_HAS_NO_ACCOUNT_SNAPSHOTS"],
                    "notes": "Collector has not stored any account snapshots yet; no P/L inference.",
                }
            account_id, snapshot_time = latest
            cur.execute("""SELECT name,value FROM atlas_state
                           WHERE account_id=%s AND name IN
                           ('last_cycle','last_reconciliation_success','backfill_complete')""", (account_id,))
            state = dict(cur.fetchall())
            cur.execute("""SELECT count(*) FROM atlas_errors
                           WHERE account_id=%s AND occurred_at >= %s""",
                        (account_id, now - timedelta(hours=24)))
            recent_errors = int(cur.fetchone()[0])
        # No COMMIT is needed: exiting the transaction in read-only mode can
        # only finalize SELECT activity. Nothing is ever written to PostgreSQL.

    snapshot = parse_utc(snapshot_time)
    reconciliation = parse_utc(state.get("last_reconciliation_success"))
    snapshot_status = _status_for_time(snapshot, now, max_age_minutes)
    reconciliation_status = _status_for_time(reconciliation, now, max_age_minutes)
    alerts = []
    if snapshot_status != "RECENT":
        alerts.append("AUDIT_SNAPSHOT_" + snapshot_status)
    if reconciliation_status != "RECENT":
        alerts.append("AUDIT_RECONCILIATION_" + reconciliation_status)
    if recent_errors:
        alerts.append("AUDIT_ERRORS_24H:" + str(recent_errors))
    backfill = state.get("backfill_complete") == "true"
    return {
        "observed_at_utc": iso(now), "account_alias": account_alias,
        "collector_health": "RECENT" if snapshot_status == "RECENT" else "STALE",
        "historical_coverage": "COLLECTOR_MARKED_COMPLETE_UNVERIFIED" if backfill else "INCOMPLETE_OR_UNKNOWN",
        "reconciliation_status": reconciliation_status,
        "snapshot_utc": iso(snapshot) if snapshot else "",
        "alerts": alerts,
        "notes": "Account snapshot timestamp verified; balances omitted from the shared Sheet; no P/L inference.",
    }
