"""ATLAS Hub -- always-on Google Sheets integration and monitoring worker.

Never places orders. Never reads or modifies Alpaca trading credentials.
Usage: python main.py [--once] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone

from atlas_hub import VERSION
from atlas_hub.config import Settings
from atlas_hub.runner import HubWorker
from atlas_hub.sheets import SheetGateway, google_client

STOP = threading.Event()
LOG = logging.getLogger("atlas-hub")
UTC = timezone.utc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Single heartbeat, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Validate and log only; never write to Google Sheets")
    args = parser.parse_args()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())

    settings = Settings.from_env()
    service = google_client(settings.credentials)
    worker = HubWorker(SheetGateway(service, settings.sheet_id), settings)
    LOG.info("ATLAS-Hub %s starting; Google Sheet=%s; trading endpoints: NONE; audit DB: %s",
             VERSION, settings.sheet_id, "CONFIGURED_READ_ONLY" if settings.audit_db_url else "NOT_CONFIGURED")
    last_history: datetime | None = None
    while not STOP.is_set():
        now = datetime.now(UTC)
        history = last_history is None or (now - last_history).total_seconds() >= settings.history_minutes * 60
        try:
            result = worker.run_once(now=now, dry_run=args.dry_run, history=history)
            if history and not args.dry_run:
                last_history = now
            if args.once:
                return 0 if result.workbook_ok else 2
        except Exception as exc:
            # Secrets or HTTP response bodies must never be written to logs.
            LOG.error("ATLAS-Hub cycle failed (will retry): %s", type(exc).__name__)
            if args.once:
                return 1
        STOP.wait(settings.interval_seconds)
    LOG.info("ATLAS-Hub shutdown cleanly")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.basicConfig(level=logging.INFO)
        LOG.error("ATLAS-Hub startup failed: %s", type(exc).__name__)
        raise SystemExit(1)
