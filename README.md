# WMS Inventory Automation (FastAPI + Supabase + n8n)

A minimal warehouse inventory core with **reconciliation + auto-heal** automation.

## What it does
- Records inventory movements as an **event ledger** (`inventory_event`)
- Maintains a rebuildable **on-hand balance** cache (`inventory_balance`)
- Provides APIs via **FastAPI** (Swagger at `/docs`)
- Automates **daily reconciliation, Telegram alerting, auto rebuild, and re-check** via **n8n**
- Sends a **daily summary** (NZ timezone: `Pacific/Auckland`)

## Tech Stack
- FastAPI (Python)
- Supabase Postgres
- n8n (local)
- Telegram Bot (alerts)

## Key Design
- **Source of truth**: `inventory_event` (append-only ledger)
- **Derived cache**: `inventory_balance` (fast reads, rebuildable)
- **Idempotency**: `idempotency_key` + unique constraint (safe retries)
- **Non-negative stock**: constraint + stock-out validation
- **Reconciliation**: compares ledger-calculated qty vs balance qty
- **Rebuild**: admin endpoint to rebuild balance from events

## API (examples)
Base: `http://127.0.0.1:8000`

- Health: `GET /health`
- Reconcile all mismatches: `GET /reconcile/all?only_mismatch=true`
- Admin rebuild: `POST /admin/rebuild-balance` (header `x-admin-key`)

Swagger UI: `http://127.0.0.1:8000/docs`

## Database setup (Supabase)
Run the SQL in Supabase SQL Editor (see `docs/sql/schema.sql` if you keep it there)
- `inventory_event` + constraints
- `inventory_balance` + non-negative constraint

## Local Run
### 1) Create venv and install deps
```bash
python3 -m venv wmsvenv
source wmsvenv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install fastapi uvicorn "psycopg[binary]" python-dotenv