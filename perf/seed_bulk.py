"""F5 性能：向性能库 ai_coach_perf 灌入百万行数据。

可重复执行 / 可清理。灌入内容：
- 1 个压测用户 + body_profile + user_benefit（供 /api/account/today）
- 1 个商家 + 1 个 merchant_sku（供 /api/order 下单）
- meal_record 百万行（供百万行分页实测，全归压测用户）
- "order" 若干行（供 /api/order/list 分页）

幂等：重复执行只补差量；--clean 先清空本脚本产生的数据。
批量插入走 PostgreSQL 服务端 generate_series（单条 INSERT ... SELECT）。

用法：
  PY=/workspace/.venv312/bin/python
  $PY perf/seed_bulk.py                    # 默认 1,000,000 meal + 200 orders
  $PY perf/seed_bulk.py --rows 500000
  $PY perf/seed_bulk.py --clean            # 清理
"""

import argparse
import asyncio
import json
import os

import asyncpg

DEFAULT_DSN = os.environ.get(
    "PERF_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach_perf"
)
DEMO_OPENID = "perf-demo-user"
MERCHANT_NAME = "性能压测商家"
BULK_MARK = "perf-bulk-food"
_COUNT_MEALS_SQL = "SELECT count(*) FROM meal_record WHERE user_id=$1"
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IDS_OUT = os.path.join(_HERE, "seed_ids.json")


async def _ensure_user(conn: asyncpg.Connection) -> int:
    row = await conn.fetchrow('SELECT id FROM "user" WHERE openid=$1', DEMO_OPENID)
    if row:
        return row["id"]
    row = await conn.fetchrow(
        'INSERT INTO "user"(openid, nickname, gender, status)'
        " VALUES($1, $2, 1, 1) RETURNING id",
        DEMO_OPENID,
        "性能压测用户",
    )
    return row["id"]


async def _ensure_profile(conn: asyncpg.Connection, user_id: int) -> None:
    if await conn.fetchval("SELECT 1 FROM body_profile WHERE user_id=$1", user_id):
        return
    await conn.execute(
        "INSERT INTO body_profile(user_id, gender, height_cm, age, current_weight,"
        " target_weight, target_type, activity_level, bmr, target_calories)"
        " VALUES($1, 1, 175.0, 28, 70.0, 65.0, 1, 2, 1600.0, 1800)",
        user_id,
    )


async def _ensure_benefit(conn: asyncpg.Connection, user_id: int) -> None:
    await conn.execute(
        "INSERT INTO user_benefit(user_id, tier, ai_times_left) VALUES($1, 0, 10)"
        " ON CONFLICT (user_id) DO NOTHING",
        user_id,
    )


async def _ensure_merchant_sku(conn: asyncpg.Connection) -> tuple[int, int]:
    row = await conn.fetchrow("SELECT id FROM merchant WHERE name=$1", MERCHANT_NAME)
    if row is None:
        row = await conn.fetchrow(
            "INSERT INTO merchant(name, category, status, audit_status)"
            " VALUES($1, '轻食', 1, 1) RETURNING id",
            MERCHANT_NAME,
        )
    merchant_id = row["id"]
    catalog_id = await conn.fetchval("SELECT id FROM sku_catalog ORDER BY id LIMIT 1")
    sku = await conn.fetchrow(
        "SELECT id FROM merchant_sku WHERE merchant_id=$1 AND catalog_id=$2",
        merchant_id,
        catalog_id,
    )
    if sku is None:
        sku = await conn.fetchrow(
            "INSERT INTO merchant_sku(merchant_id, catalog_id, price, stock, status)"
            " VALUES($1, $2, 25.0, -1, 1) RETURNING id",
            merchant_id,
            catalog_id,
        )
    return merchant_id, sku["id"]


async def _seed_meals(
    conn: asyncpg.Connection, user_id: int, rows: int
) -> tuple[int, int]:
    have = int(await conn.fetchval(_COUNT_MEALS_SQL, user_id))
    if have >= rows:
        return have, 0
    need = rows - have
    await conn.execute(
        "INSERT INTO meal_record(user_id, record_date, meal_type, food_id,"
        " food_name_snapshot, amount_g, calories, protein, fat, carb, source,"
        " created_at)"
        " SELECT $1, CURRENT_DATE - 1 - (g % 365), (g % 4) + 1, NULL, $2, 100.0,"
        " 200.0, 10.0, 5.0, 20.0, 3, NOW() - make_interval(secs => g)"
        " FROM generate_series(1, $3) AS g",
        user_id,
        BULK_MARK,
        need,
    )
    return rows, need


async def _seed_orders(
    conn: asyncpg.Connection, user_id: int, merchant_id: int, count: int
) -> tuple[int, int]:
    prefix = f"PERF{user_id}-"
    like = prefix + "%"
    have = int(
        await conn.fetchval('SELECT count(*) FROM "order" WHERE order_no LIKE $1', like)
    )
    if have >= count:
        return have, 0
    await conn.execute(
        'INSERT INTO "order"(order_no, user_id, merchant_id, total_amount,'
        " discount_amount, pay_amount, status, expire_at)"
        " SELECT $1 || g::text, $2, $3, 25.0, 0, 25.0, 1,"
        " NOW() + interval '30 minutes'"
        " FROM generate_series($4::bigint, $5::bigint) AS g",
        prefix,
        user_id,
        merchant_id,
        have + 1,
        count,
    )
    return count, count - have


async def _clean(conn: asyncpg.Connection) -> None:
    uid = await conn.fetchval('SELECT id FROM "user" WHERE openid=$1', DEMO_OPENID)
    await conn.execute("DELETE FROM meal_record WHERE food_name_snapshot=$1", BULK_MARK)
    # 删除压测用户的全部订单（含压测期间 app 动态下单的，order_item 级联删除）
    if uid is not None:
        await conn.execute('DELETE FROM "order" WHERE user_id=$1', uid)
    await conn.execute('DELETE FROM "order" WHERE order_no LIKE $1', "PERF%")
    await conn.execute(
        "DELETE FROM merchant_sku WHERE merchant_id IN"
        " (SELECT id FROM merchant WHERE name=$1)",
        MERCHANT_NAME,
    )
    await conn.execute("DELETE FROM merchant WHERE name=$1", MERCHANT_NAME)
    if uid is not None:
        # user_benefit/user_auth 无级联删除，须先清依赖
        await conn.execute("DELETE FROM user_benefit WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM user_auth WHERE user_id=$1", uid)
        await conn.execute('DELETE FROM "user" WHERE id=$1', uid)


async def main() -> None:
    parser = argparse.ArgumentParser(description="百万行性能数据灌入")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--rows", type=int, default=1_000_000, help="meal 行数")
    parser.add_argument("--orders", type=int, default=200, help="order 目标行数")
    parser.add_argument("--clean", action="store_true", help="清理后退出")
    parser.add_argument("--ids-out", default=DEFAULT_IDS_OUT)
    args = parser.parse_args()

    conn = await asyncpg.connect(args.dsn)
    try:
        if args.clean:
            await _clean(conn)
            print(json.dumps({"cleaned": True, "dsn": args.dsn}, ensure_ascii=False))
            return

        user_id = await _ensure_user(conn)
        await _ensure_profile(conn, user_id)
        await _ensure_benefit(conn, user_id)
        merchant_id, sku_id = await _ensure_merchant_sku(conn)
        meal_total, meal_inserted = await _seed_meals(conn, user_id, args.rows)
        order_total, order_inserted = await _seed_orders(
            conn, user_id, merchant_id, args.orders
        )
        food_id = await conn.fetchval("SELECT id FROM food ORDER BY id LIMIT 1")

        await conn.execute("ANALYZE meal_record")
        await conn.execute('ANALYZE "order"')

        summary = {
            "dsn": args.dsn,
            "user_id": user_id,
            "merchant_id": merchant_id,
            "sku_id": sku_id,
            "food_id": food_id,
            "meal_rows": meal_total,
            "meal_inserted": meal_inserted,
            "orders": order_total,
            "orders_inserted": order_inserted,
        }
        if args.ids_out:
            with open(args.ids_out, "w", encoding="utf-8") as fh:
                json.dump(summary, fh, ensure_ascii=False, indent=2)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())