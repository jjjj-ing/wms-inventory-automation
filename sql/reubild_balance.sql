-- sql/rebuild_balance.sql
truncate table inventory_balance;

insert into inventory_balance (sku_code, qty_on_hand, updated_at)
select
  sku_code,
  coalesce(sum(case when event_type='RECEIPT' then qty else 0 end),0)
  - coalesce(sum(case when event_type='PICK' then qty else 0 end),0) as qty_on_hand,
  now()
from inventory_event
group by sku_code;