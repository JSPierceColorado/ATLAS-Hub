"""Google Sheets adapter: reads existing tabs and writes ONLY Hub Health/ATLAS V."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .logic import HEADERS, Assessment, iso

HEALTH_TAB = "Hub Health"
HEALTH_HEADER = [
    "observed_at_utc", "hub_version", "status", "schema_ok", "execution_mode",
    "kill_switch", "trading_enabled", "universe_reference_count", "universe_verified_count",
    "momentum_current_count", "new_signals", "open_positions_mirrored",
    "atlas_v_link_status", "atlas_v_last_snapshot_utc", "alerts_json",
]
ATLAS_V_HEADER = HEADERS["ATLAS V"]


def google_client(service_account_info: dict):
    # Import lazily so pure unit tests don't require Google SDK packages.
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


class SheetGateway:
    def __init__(self, service: Any, sheet_id: str) -> None:
        self.service = service
        self.id = sheet_id

    def list_tabs(self) -> dict[str, int]:
        response = self.service.spreadsheets().get(
            spreadsheetId=self.id,
            fields="spreadsheetId,properties(title),sheets(properties(sheetId,title,gridProperties))",
        ).execute(num_retries=3)
        return {s["properties"]["title"]: s["properties"]["sheetId"] for s in response.get("sheets", [])}

    def read_sources(self) -> dict[str, list[list]]:
        ranges = {tab: f"'{tab}'!A1:{_last_col(len(cols))}250" for tab, cols in HEADERS.items()}
        result = self.service.spreadsheets().values().batchGet(
            spreadsheetId=self.id,
            ranges=list(ranges.values()),
            valueRenderOption="UNFORMATTED_VALUE",
        ).execute(num_retries=3)
        returned = result.get("valueRanges", [])
        if len(returned) != len(ranges):
            raise RuntimeError("Google Sheets returned an incomplete batch read")
        return {tab: returned[i].get("values", []) for i, tab in enumerate(ranges)}

    def ensure_health_tab(self, tabs: dict[str, int]) -> None:
        if HEALTH_TAB not in tabs:
            response = self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.id,
                body={"requests": [
                    {"addSheet": {"properties": {
                        "title": HEALTH_TAB,
                        "gridProperties": {"rowCount": 1000, "columnCount": len(HEALTH_HEADER), "frozenRowCount": 1},
                    }}},
                ]},
            ).execute(num_retries=3)
            tabs[HEALTH_TAB] = response["replies"][0]["addSheet"]["properties"]["sheetId"]
            self.service.spreadsheets().values().update(
                spreadsheetId=self.id,
                range="'Hub Health'!A1:O1",
                valueInputOption="RAW",
                body={"values": [HEALTH_HEADER]},
            ).execute(num_retries=3)
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.id,
                body={"requests": [
                    {"repeatCell": {
                        "range": {"sheetId": tabs[HEALTH_TAB], "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.95, "green": 0.96, "blue": 0.97}, "textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat",
                    }},
                    {"updateDimensionProperties": {
                        "range": {"sheetId": tabs[HEALTH_TAB], "dimension": "COLUMNS", "startIndex": 0, "endIndex": len(HEALTH_HEADER)},
                        "properties": {"pixelSize": 165}, "fields": "pixelSize",
                    }},
                    {"updateDimensionProperties": {
                        "range": {"sheetId": tabs[HEALTH_TAB], "dimension": "COLUMNS", "startIndex": 14, "endIndex": 15},
                        "properties": {"pixelSize": 460}, "fields": "pixelSize",
                    }},
                ]},
            ).execute(num_retries=3)
        else:
            row = self.service.spreadsheets().values().get(
                spreadsheetId=self.id, range="'Hub Health'!A1:O1",
            ).execute(num_retries=3).get("values", [])
            if not row:
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.id, range="'Hub Health'!A1:O1",
                    valueInputOption="RAW", body={"values": [HEALTH_HEADER]},
                ).execute(num_retries=3)
            elif row[0] != HEALTH_HEADER:
                raise RuntimeError("Existing Hub Health headers differ; refusing to overwrite user data")

    def publish_health(self, state: Assessment, version: str, history: bool) -> None:
        row = [
            iso(state.observed_at), version, state.status, state.workbook_ok,
            state.execution_mode, state.kill_switch, state.trading_enabled,
            state.universe_reference, state.universe_verified, state.momentum_scored,
            state.signal_new, state.positions_open, state.audit_status,
            state.audit_snapshot, json.dumps(state.alerts, separators=(",", ":")),
        ]
        values = self.service.spreadsheets().values()
        values.update(
            spreadsheetId=self.id,
            range="'Hub Health'!A2:O2",
            valueInputOption="RAW",
            body={"values": [row]},
        ).execute(num_retries=3)
        if history:
            values.append(
                spreadsheetId=self.id,
                range="'Hub Health'!A5:O",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute(num_retries=3)

    def append_atlas_v(self, audit: dict) -> None:
        # ATLAS V is read-only source data; avoid implied official trading P&L.
        head = self.service.spreadsheets().values().get(
            spreadsheetId=self.id,
            range="'ATLAS V'!A1:L1",
        ).execute(num_retries=3).get("values", [])
        if not head or head[0] != ATLAS_V_HEADER:
            raise RuntimeError("ATLAS V tab header mismatch; will not append a report")
        row = [
            "HUB-" + audit["observed_at_utc"], audit["observed_at_utc"], audit["account_alias"],
            "LATEST_SNAPSHOT", audit["collector_health"], audit["historical_coverage"],
            audit["reconciliation_status"], ";".join(audit["alerts"]), "", False,
            "ATLAS_V_POSTGRES_READONLY", audit["notes"],
        ]
        self.service.spreadsheets().values().append(
            spreadsheetId=self.id,
            range="'ATLAS V'!A2:L",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute(num_retries=3)


def _last_col(n: int) -> str:
    letters = ""
    while n:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
