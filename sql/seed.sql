-- sql/seed.sql
-- Seed data for demo/testing (safe to re-run by truncating first)

-- Clean slate for demo
truncate table inventory_balance;
truncate table inventory_event;

-- ---- Case A: Normal (SKU-001) ----
insert into inventory_event (event_type, sku_code, qty, idempotency_key)
values
  ('RECEIPT','SKU-001', 10, 'SEED-A-001'),
  ('PICK',   'SKU-001',  4, 'SEED-A-002');

-- Build correct balance for SKU-001
insert into inventory_balance (sku_code, qty_on_hand, updated_at)
select
  sku_code,
  coalesce(sum(case when event_type='RECEIPT' then qty else 0 end),0)
  - coalesce(sum(case when event_type='PICK' then qty else 0 end),0) as qty_on_hand,
  now()
from inventory_event
group by sku_code;

-- ---- Case B: Mismatch (SKU-002) ----
insert into inventory_event (event_type, sku_code, qty, idempotency_key)
values
  ('RECEIPT','SKU-002', 5, 'SEED-B-001'),
  ('PICK',   'SKU-002', 2, 'SEED-B-002');

-- Force a WRONG balance for SKU-002 (mismatch on purpose)
insert into inventory_balance (sku_code, qty_on_hand, updated_at)
values ('SKU-002', 999, now())
on conflict (sku_code) do update
set qty_on_hand = excluded.qty_on_hand,
    updated_at = excluded.updated_at;