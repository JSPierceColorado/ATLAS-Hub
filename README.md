# ATLAS-Hub — Railway + Google Sheets integration (V1.0)

ATLAS-Hub is **a coordination and monitoring worker, not a trading bot**. It reads the verified ATLAS System Hub Google Sheet, checks its schema and planning/safety settings, and writes a heartbeat to its own `Hub Health` tab. Optionally, with a **separate read-only PostgreSQL credential**, it can mirror the existing ATLAS V audit collector's health into `ATLAS V`. It does not need or use Alpaca trading credentials.

**System Hub:** https://docs.google.com/spreadsheets/d/1SdF1R4R5SRNvkdLkIxDhcv1ty0-3kXlL-eLVpjMnS00/edit

## What works in this release

- Validates the expected tab names and exact headers for `Control`, `Strategies`, `Universe`, `Momentum`, `Signals`, `Positions`, `ATLAS V`.
- Checks `execution_mode=PLANNING`, `trading_enabled=FALSE`, `kill_switch=TRUE`, `policy_approval_status=NOT_APPROVED` and flags unexpected changes instead of trading.
- Counts reference S&P 100 universe symbols, verified symbols, fresh momentum rows, new signals and mirrored open positions. It does **not** treat the 101 legacy tickers as a verified current S&P 100 membership list.
- Creates a separate `Hub Health` tab with the verified schema, writes current status every five minutes and appends an hourly history row. It does not alter the `Control`, `Strategies`, `Universe`, `Momentum`, `Signals`, `Positions`, `Orders`, `Overview`, or `Research` tabs.
- Optional ATLAS V integration: if `ATLAS_V_READONLY_DATABASE_URL` is supplied, uses only PostgreSQL `SELECT` queries to read latest ATLAS V account snapshot, backfill/reconciliation status and 24-hour error count. Appends a strictly **non-P&L** audit health record to the existing `ATLAS V` tab roughly once per hour. The sheet does not receive actual account identifiers or cash balances.
- Built for a **single persistent Railway worker**: no HTTP server, no domain, no cron schedule; it polls internally, gracefully handles SIGTERM and continues on transient failures.

## GitHub upload (new repository)

1. In GitHub, create a **private** repository named `ATLAS-Hub`.
2. Unzip the package and upload its **contents into the repository root**. The root should have `main.py`, `Dockerfile`, `requirements.txt`, `.gitignore`, `.env.example`, the `atlas_hub/` directory and `tests/` directory. Do not upload the ZIP itself as the only repository file.
3. Do **not** put Google service account keys or database passwords in GitHub. `.env.example` has no secrets.

## Railway service setup

1. Open the existing **Investing** Railway project, and add a service via **Deploy from GitHub Repo** > `ATLAS-Hub`.
2. Ensure Railway builds the root **Dockerfile**. Use **one replica**, keep **Cron Schedule empty**, do not configure a public domain or HTTP healthcheck, and do not enable serverless sleep.
3. In **Variables**, set:

   | Name | Value | Required? |
   |---|---|---|
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | The complete Google service account JSON key (Railway secret variable, never GitHub) | **YES** |
   | `ATLAS_SHEET_ID` | `1SdF1R4R5SRNvkdLkIxDhcv1ty0-3kXlL-eLVpjMnS00` | Recommended (default exists) |
   | `HUB_INTERVAL_SECONDS` | `300` | Optional |
   | `HUB_HISTORY_MINUTES` | `60` | Optional |
   | `ATLAS_V_READONLY_DATABASE_URL` | PostgreSQL URL for a **SELECT-only role**, NOT the original write-enabled database URL | Optional |
   | `ATLAS_V_ACCOUNT_ALIAS` | `main` | Optional |
   | `ATLAS_V_MAX_SNAPSHOT_MINUTES` | `35` | Optional |
   | `LOG_LEVEL` | `INFO` | Optional |

4. In Google Sheets, share the [ATLAS — System Hub](https://docs.google.com/spreadsheets/d/1SdF1R4R5SRNvkdLkIxDhcv1ty0-3kXlL-eLVpjMnS00/edit) with the service account's **`client_email`** as **Editor**. Only this one document needs to be shared. You can use a dedicated service account. Never paste its `private_key` into Sheets, GitHub, or chat.
5. Deploy. Initial logs should show `ATLAS-Hub 1.0.0 starting` followed by `ATLAS_HUB_HEALTH status=READY_PLANNING`.
6. Open `Hub Health` in Google Sheets. The current heartbeat is row **2**; history starts at row **5**. `audit=NOT_CONFIGURED` is normal until you add the optional database connection.

### Optional: least-privilege ATLAS V connection

**Do not copy ATLAS V's original `DATABASE_URL` into ATLAS-Hub.** A write-enabled credential creates unnecessary risk. In PostgreSQL, a database administrator can create a separate role with permissions only on the tables the hub reads. Illustrative SQL (adapt DB/user names; execute as an authorized DB administrator, never inside Hub):

```sql
CREATE ROLE atlas_hub_reader LOGIN PASSWORD 'generate_a_strong_unique_secret';
GRANT CONNECT ON DATABASE railway TO atlas_hub_reader;
GRANT USAGE ON SCHEMA public TO atlas_hub_reader;
GRANT SELECT ON TABLE public.atlas_accounts,
    public.atlas_state, public.atlas_errors TO atlas_hub_reader;
ALTER ROLE atlas_hub_reader SET default_transaction_read_only = on;
```

Store the resulting *reader-role* URL as `ATLAS_V_READONLY_DATABASE_URL` in Railway. The Hub enforces read-only transactions additionally, even if the role is accidentally over-permissioned. If you aren't ready to provision that credential, leave it blank—the Hub still works.

## Safety and ownership

- The code does not import `alpaca`, call broker APIs or submit orders, and does not use any `ALPACA_*` or `APCA_*` variables. The new `Hub Health` tab is the only required write target.
- An optional `ATLAS V` append is a health/status mirror, **not official realized P&L, not a reconciliation guarantee, and not an order execution command**.
- Editing cells like `Control!B3` never grants trading ability; the Hub has no trading capability at all.
- The canonical broker audit remains ATLAS V's PostgreSQL database. The new Google Sheet is a coordination/view layer, not a transaction database. Future Executor code must independently enforce risk controls and its own permissions.
- Do not run multiple Hub replicas. The worker does not implement distributed locking or exactly-once event writes; retries or restarts may duplicate a history row. Current heartbeat row A2:O2 is idempotent.
- No external monitoring service, no broker integration and no new strategy deployments are installed by this package.

## Tests and local commands

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
```

A local single-cycle dry run (requires real Google service account credentials in environment variables) will validate the workbook, but **not write** to it:

```bash
python main.py --once --dry-run
```

To run one actual heartbeat instead of a persistent service:

```bash
python main.py --once
```

## Expected first result

`Hub Health` row 2 will look approximately like this:

- `status`: `READY_PLANNING`
- `execution_mode`: `PLANNING`
- `kill_switch`: `TRUE`
- `trading_enabled`: `FALSE`
- `universe_reference_count`: `101`
- `universe_verified_count`: `0`
- `momentum_current_count`: `0`
- `atlas_v_link_status`: `NOT_CONFIGURED`, unless optional database URL is present

Reference-only and awaiting-refresh alerts are *expected* at this stage and do not represent a failed deployment.
