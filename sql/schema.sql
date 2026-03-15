-- sql/schema.sql
-- WMS Inventory Automation: schema (idempotent)

-- Needed for gen_random_uuid()
create extension if not exists pgcrypto;

-- 1) Event ledger (append-only)
create table if not exists inventory_event (
  id uuid primary key default gen_random_uuid(),
  event_type text not null,
  sku_code text not null,
  qty int not null check (qty > 0),
  idempotency_key text,
  created_at timestamptz not null default now()
);

-- event_type constraint (safe re-run)
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'ck_inventory_event_type'
  ) then
    alter table inventory_event
      add constraint ck_inventory_event_type
      check (event_type in ('RECEIPT','PICK','ADJUST'));
  end if;
end $$;

-- Idempotency unique index (allow nulls)
create unique index if not exists ux_inventory_event_idempo
on inventory_event(idempotency_key)
where idempotency_key is not null;

-- Backfill idempotency_key for existing rows (safe)
update inventory_event
set idempotency_key = coalesce(idempotency_key, 'BACKFILL-' || id::text)
where idempotency_key is null;

-- Make it NOT NULL if not already
do $$
begin
  -- only set not null if it isn't already
  if exists (
    select 1
    from information_schema.columns
    where table_name = 'inventory_event'
      and column_name = 'idempotency_key'
      and is_nullable = 'YES'
  ) then
    alter table inventory_event
      alter column idempotency_key set not null;
  end if;
end $$;

-- Helpful index for rebuild/reconcile
create index if not exists ix_inventory_event_sku_created
on inventory_event(sku_code, created_at);

-- 2) Derived balance cache
create table if not exists inventory_balance (
  sku_code text primary key,
  qty_on_hand int not null default 0,
  updated_at timestamptz not null default now(),
  constraint ck_balance_nonnegative check (qty_on_hand >= 0)
);

create index if not exists ix_inventory_balance_updated
on inventory_balance(updated_at);