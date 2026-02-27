from psycopg import errors
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import psycopg

load_dotenv()
db_url = os.getenv("DATABASE_URL")

app = FastAPI()

class EventIn(BaseModel):
    idempotency_key: str
    event_type: str  # RECEIPT / PICK / ADJUST
    sku_code: str
    qty: int

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/events")
def deprecated_events_write():
    raise HTTPException(status_code=410, detail="deprecated: use /stock/in or /stock/out")
from typing import Optional

@app.get("/events")
def list_events(sku_code: Optional[str] = None, limit: int = 20):
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    limit = max(1, min(limit, 100))

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            if sku_code:
                cur.execute(
                    """
                    select id, idempotency_key, event_type, sku_code, qty, created_at
                    from inventory_event
                    where sku_code = %s
                    order by created_at desc
                    limit %s
                    """,
                    (sku_code, limit),
                )
            else:
                cur.execute(
                    """
                    select id, idempotency_key, event_type, sku_code, qty, created_at
                    from inventory_event
                    order by created_at desc
                    limit %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()

    return [
        {
            "id": str(r[0]),
            "idempotency_key": r[1],
            "event_type": r[2],
            "sku_code": r[3],
            "qty": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]

class StockIn(BaseModel):
    idempotency_key: str
    sku_code: str
    qty: int

@app.post("/stock/in")
def stock_in(s: StockIn):
    if s.qty <= 0:
        raise HTTPException(status_code=400, detail="qty must be > 0")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # 幂等：复用 inventory_event 的幂等键机制（简单起见直接写 event）
                cur.execute("select id from inventory_event where idempotency_key=%s", (s.idempotency_key,))
                if cur.fetchone():
                    return {"idempotent": True}

                # 写事件
                cur.execute(
                    "insert into inventory_event (idempotency_key, event_type, sku_code, qty) values (%s,'RECEIPT',%s,%s)",
                    (s.idempotency_key, s.sku_code, s.qty),
                )

                # upsert balance
                cur.execute(
                    """
                    insert into inventory_balance (sku_code, qty_on_hand)
                    values (%s, %s)
                    on conflict (sku_code)
                    do update set qty_on_hand = inventory_balance.qty_on_hand + excluded.qty_on_hand,
                                 updated_at = now()
                    """,
                    (s.sku_code, s.qty),
                )
                conn.commit()
        return {"idempotent": False}
    except errors.UniqueViolation:
        return {"idempotent": True}
    except Exception:
        raise HTTPException(status_code=500, detail="internal error")


class StockOut(BaseModel):
    idempotency_key: str
    sku_code: str
    qty: int

@app.post("/stock/out")
def stock_out(s: StockOut):
    if s.qty <= 0:
        raise HTTPException(status_code=400, detail="qty must be > 0")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # 幂等
                cur.execute("select id from inventory_event where idempotency_key=%s", (s.idempotency_key,))
                if cur.fetchone():
                    return {"idempotent": True}

                # 锁住余额行，防并发扣成负数
                cur.execute(
                    "select qty_on_hand from inventory_balance where sku_code=%s for update",
                    (s.sku_code,),
                )
                row = cur.fetchone()
                current = row[0] if row else 0

                if current < s.qty:
                    raise HTTPException(status_code=409, detail="insufficient stock")

                # 写事件（出库用 PICK，qty 仍然写正数，语义更清晰）
                cur.execute(
                    "insert into inventory_event (idempotency_key, event_type, sku_code, qty) values (%s,'PICK',%s,%s)",
                    (s.idempotency_key, s.sku_code, s.qty),
                )

                # 扣减余额
                cur.execute(
                    """
                    update inventory_balance
                    set qty_on_hand = qty_on_hand - %s,
                        updated_at = now()
                    where sku_code = %s
                    """,
                    (s.qty, s.sku_code),
                )
                conn.commit()
        return {"idempotent": False}
    except HTTPException:
        # 让 409 这种业务错误原样返回
        raise
    except errors.UniqueViolation:
        return {"idempotent": True}
    except Exception:
        raise HTTPException(status_code=500, detail="internal error")

from typing import Optional

@app.get("/stock")
def get_stock(sku_code: Optional[str] = None):
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            if sku_code:
                cur.execute(
                    "select sku_code, qty_on_hand, updated_at from inventory_balance where sku_code=%s",
                    (sku_code,),
                )
            else:
                cur.execute(
                    "select sku_code, qty_on_hand, updated_at from inventory_balance order by sku_code",
                )
            rows = cur.fetchall()

    return [
        {"sku_code": r[0], "qty_on_hand": r[1], "updated_at": r[2].isoformat()}
        for r in rows
    ]
@app.get("/reconcile")
def reconcile(sku_code: str):
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                  coalesce(sum(case when event_type='RECEIPT' then qty end), 0) as total_in,
                  coalesce(sum(case when event_type='PICK' then qty end), 0) as total_out
                from inventory_event
                where sku_code = %s
                """,
                (sku_code,),
            )
            total_in, total_out = cur.fetchone()

            cur.execute(
                "select coalesce(qty_on_hand, 0) from inventory_balance where sku_code=%s",
                (sku_code,),
            )
            balance = cur.fetchone()
            balance_qty = balance[0] if balance else 0

    expected = total_in - total_out
    return {
        "sku_code": sku_code,
        "total_in": total_in,
        "total_out": total_out,
        "expected_from_events": expected,
        "balance_qty_on_hand": balance_qty,
        "match": expected == balance_qty,
    }
from fastapi import Header

@app.post("/admin/rebuild-balance")
def admin_rebuild_balance(x_admin_key: str = Header(default="")):
    # 1) 简单鉴权：请求头必须带 x-admin-key
    expected = os.getenv("ADMIN_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="ADMIN_KEY not set")
    if x_admin_key != expected:
        raise HTTPException(status_code=401, detail="unauthorized")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # 2) 重建 balance：以事件为真相
                cur.execute("truncate table inventory_balance;")
                cur.execute(
                    """
                    insert into inventory_balance (sku_code, qty_on_hand, updated_at)
                    select
                      sku_code,
                      coalesce(sum(case when event_type='RECEIPT' then qty else 0 end),0)
                      - coalesce(sum(case when event_type='PICK' then qty else 0 end),0) as qty_on_hand,
                      now()
                    from inventory_event
                    group by sku_code
                    """
                )
                conn.commit()

        return {"ok": True, "message": "balance rebuilt from events"}

    except Exception:
        raise HTTPException(status_code=500, detail="internal error")

@app.get("/reconcile/all")
def reconcile_all(only_mismatch: bool = True):
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            # 用事件算 expected，再和 balance 对比
            cur.execute(
                """
                with expected as (
                  select
                    sku_code,
                    coalesce(sum(case when event_type='RECEIPT' then qty else 0 end),0)
                    - coalesce(sum(case when event_type='PICK' then qty else 0 end),0) as expected_qty
                  from inventory_event
                  group by sku_code
                ),
                actual as (
                  select sku_code, qty_on_hand as actual_qty
                  from inventory_balance
                )
                select
                  coalesce(e.sku_code, a.sku_code) as sku_code,
                  coalesce(e.expected_qty, 0) as expected_qty,
                  coalesce(a.actual_qty, 0) as actual_qty,
                  (coalesce(e.expected_qty, 0) - coalesce(a.actual_qty, 0)) as diff
                from expected e
                full outer join actual a using (sku_code)
                order by sku_code
                """
            )
            rows = cur.fetchall()

    results = [
        {
            "sku_code": r[0],
            "expected_qty": r[1],
            "actual_qty": r[2],
            "diff": r[3],
            "match": r[3] == 0,
        }
        for r in rows
    ]

    if only_mismatch:
        results = [x for x in results if not x["match"]]

    return {
        "mismatch_count": len(results),
        "results": results,
    }