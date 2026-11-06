"""Configuration. Secrets remain in Railway variables, never in Google Sheets."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

DEFAULT_SHEET_ID = "1SdF1R4R5SRNvkdLkIxDhcv1ty0-3kXlL-eLVpjMnS00"


def bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    sheet_id: str
    credentials: dict
    interval_seconds: int
    history_minutes: int
    audit_db_url: str | None
    audit_account_alias: str
    audit_max_snapshot_minutes: int

    @classmethod
    def from_env(cls) -> "Settings":
        sheet_id = os.getenv("ATLAS_SHEET_ID", DEFAULT_SHEET_ID).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,150}", sheet_id):
            raise ValueError("ATLAS_SHEET_ID must be a Google Sheets spreadsheet ID, not a URL")
        raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is required; share the hub sheet with the service account as Editor")
        try:
            credentials = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON must contain the full service-account JSON object") from exc
        if not isinstance(credentials, dict) or not all(credentials.get(k) for k in ("client_email", "private_key", "token_uri")):
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is missing required service-account fields")
        audit_db_url = os.getenv("ATLAS_V_READONLY_DATABASE_URL", "").strip() or None
        # Do not accept a generic DATABASE_URL: accidental use of a privileged DB user
        # is an avoidable risk. The audit integration must be configured explicitly.
        alias = os.getenv("ATLAS_V_ACCOUNT_ALIAS", "main").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", alias):
            raise ValueError("ATLAS_V_ACCOUNT_ALIAS must be a short plain-text label")
        return cls(
            sheet_id=sheet_id,
            credentials=credentials,
            interval_seconds=bounded_int("HUB_INTERVAL_SECONDS", 300, 60, 3600),
            history_minutes=bounded_int("HUB_HISTORY_MINUTES", 60, 15, 1440),
            audit_db_url=audit_db_url,
            audit_account_alias=alias,
            audit_max_snapshot_minutes=bounded_int("ATLAS_V_MAX_SNAPSHOT_MINUTES", 35, 10, 1440),
        )
