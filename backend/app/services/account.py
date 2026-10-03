"""热量账户服务：读当日记录 → 走热量引擎 → 幂等写 daily_snapshot → 产出账户/趋势。

- 快照唯一约束 (user_id, snapshot_date)：PG `INSERT ... ON CONFLICT DO UPDATE` 幂等。
- 写入触发：饮食/运动/步数写操作后调用 `recompute_day` 重算当日。
- 时区：业务口径 UTC+8（Asia/Shanghai），运动记录按 +08:00 日界聚合。
- 当日状态（F-01，§2.3.1/§6.3.3）：`daily_snapshot.activity_level` 存当日所选状态；
  已选则 PAL/NEAT 取当日状态，未选回退建档 `body_profile.activity_level`（「不点则用默认 PAL」）。
  不改变 TEE 结构（TEE = BMR×PAL + EAT + TEF）。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models import (
    BodyProfile,
    DailySnapshot,
    MealRecord,
    SportRecord,
    StepRecord,
    WeightRecord,
)
from app.schemas.account import AccountTrendData, DailyAccount, DailyTrendItem, MealSummary
from app.schemas.common import ErrorCode
from app.services import calorie

TZ = timezone(timedelta(hours=8))
MEAL_LABELS = {1: "早餐", 2: "午餐", 3: "晚餐", 4: "加餐"}
# 第四层「体重变化·周度反推」校准窗口【假设】：近 7 天
WEEK_CALIBRATION_DAYS = 7
# daily_snapshot.intake/eat/tee 为 NUMERIC(7,1)，上限 999999.9；当日合计越界前置 2001，
# 避免「多条记录叠加」把快照列写溢出（→ HTTP 500）。deficit 为 NUMERIC(8,1) 无需校验。
SNAPSHOT_NUMERIC_MAX = 999999.9

_ACCOUNT_FIELDS = (
    "bmr",
    "pal",
    "neat",
    "eat",
    "tef",
    "tee",
    "intake",
    "deficit",
    "steps",
    "calories_burnt",
    "calibration_used",
)


async def get_body_profile(session: AsyncSession, user_id: int) -> BodyProfile | None:
    return (
        await session.execute(select(BodyProfile).where(BodyProfile.user_id == user_id))
    ).scalar_one_or_none()


async def _day_intake(session: AsyncSession, user_id: int, day: date) -> float:
    total = await session.scalar(
        select(func.coalesce(func.sum(MealRecord.calories), 0)).where(
            MealRecord.user_id == user_id, MealRecord.record_date == day
        )
    )
    return float(total or 0)


async def _day_eat(session: AsyncSession, user_id: int, day: date) -> float:
    start = datetime.combine(day, time.min, tzinfo=TZ)
    end = start + timedelta(days=1)
    total = await session.scalar(
        select(func.coalesce(func.sum(SportRecord.calories), 0)).where(
            SportRecord.user_id == user_id,
            SportRecord.record_at >= start,
            SportRecord.record_at < end,
        )
    )
    return float(total or 0)


async def _day_steps(session: AsyncSession, user_id: int, day: date) -> StepRecord | None:
    return (
        await session.execute(
            select(StepRecord).where(StepRecord.user_id == user_id, StepRecord.record_date == day)
        )
    ).scalar_one_or_none()


async def _selected_status_level(session: AsyncSession, user_id: int, day: date) -> int | None:
    """当日已选状态（daily_snapshot.activity_level）；未选/无快照返回 None。"""
    value = await session.scalar(
        select(DailySnapshot.activity_level).where(
            DailySnapshot.user_id == user_id, DailySnapshot.snapshot_date == day
        )
    )
    return int(value) if value is not None else None


async def compute_result(
    session: AsyncSession,
    user_id: int,
    day: date,
    *,
    activity_level: int | None = None,
) -> calorie.CalorieResult:
    """读当日数据 → 热量引擎结果。未建档抛 3001。

    活动水平：显式传入（写入当日状态）时直接采用；否则取当日已选状态，未选回退建档
    `body_profile.activity_level`（F-01「不点则用默认 PAL」）。
    """
    profile = await get_body_profile(session, user_id)
    if profile is None:
        raise AppException(ErrorCode.NOT_FOUND, "尚未创建身体档案")
    weight = float(profile.current_weight or 0)
    if weight <= 0:
        raise AppException(ErrorCode.NOT_FOUND, "尚未创建身体档案")
    if activity_level is None:
        selected = await _selected_status_level(session, user_id, day)
        activity_level = (
            selected
            if selected is not None
            else int(profile.activity_level or calorie.DEFAULT_ACTIVITY_LEVEL)
        )
    step_row = await _day_steps(session, user_id, day)
    steps = int(step_row.steps) if step_row else 0
    hourly = step_row.hourly_json if step_row else None
    return calorie.compute_account(
        calorie.CalorieInputs(
            gender=int(profile.gender),
            weight_kg=weight,
            height_cm=float(profile.height_cm),
            age=int(profile.age or calorie.age_from_birth_year(profile.birth_year, day)),
            activity_level=int(activity_level),
            intake=await _day_intake(session, user_id, day),
            eat=await _day_eat(session, user_id, day),
            steps=steps,
            hourly=hourly,
        )
    )


async def upsert_snapshot(
    session: AsyncSession,
    user_id: int,
    day: date,
    result: calorie.CalorieResult | None = None,
    *,
    activity_level: int | None = None,
) -> calorie.CalorieResult:
    """幂等写当日快照（(user_id, snapshot_date) 冲突则更新）。返回计算结果。

    写库前校验当日合计：intake/eat/tee 任一超 NUMERIC(7,1) 上限 → 2001（防写库溢出 500）。
    `activity_level` 仅在「写入当日状态」（set_today_status）时传入；普通重算不传，
    避免把用户已选状态覆盖为 NULL（ON CONFLICT 只更新 _ACCOUNT_FIELDS）。
    """
    res = result or await compute_result(session, user_id, day)
    for value in (res.intake, res.eat, res.tee):
        if float(value) > SNAPSHOT_NUMERIC_MAX:
            raise AppException(ErrorCode.VALIDATION_ERROR, "当日数据超出合理范围")
    values = {
        "user_id": user_id,
        "snapshot_date": day,
        **{f: getattr(res, f) for f in _ACCOUNT_FIELDS},
    }
    set_fields = {f: getattr(res, f) for f in _ACCOUNT_FIELDS}
    if activity_level is not None:
        values["activity_level"] = activity_level
        set_fields["activity_level"] = activity_level
    stmt = pg_insert(DailySnapshot).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "snapshot_date"],
        set_=set_fields,
    )
    await session.execute(stmt)
    await session.commit()
    return res


async def recompute_day(session: AsyncSession, user_id: int, day: date | None = None) -> None:
    """记录写操作后重算当日快照（供 BE3/BE2b 调用）。"""
    await upsert_snapshot(session, user_id, day or datetime.now(TZ).date())


async def get_weekly_calibration(session: AsyncSession, user_id: int) -> calorie.WeeklyCalibration:
    """NEAT 第四层「体重变化·周度反推」校准（F-07，04 §6.3.3）。

    周度口径：近 `WEEK_CALIBRATION_DAYS` 天「实际体重变化」vs「快照累计缺口对应的
    体重变化」，经 `calorie.weekly_neat_calibration` 反推有界 PAL/NEAT 修正系数。
    仅服务周度校准路径；日内计算（compute_result/get_today）不接入，保证不回归。
    数据不足（无档案/最近窗口体重记录 < 2 条/无快照）→ 偏差按 0，系数 1.0（不校准）。
    """
    today = datetime.now(TZ).date()
    start = today - timedelta(days=WEEK_CALIBRATION_DAYS - 1)
    weights = (
        (
            await session.execute(
                select(WeightRecord)
                .where(
                    WeightRecord.user_id == user_id,
                    WeightRecord.record_at >= start,
                    WeightRecord.record_at <= today,
                )
                .order_by(WeightRecord.record_at.asc(), WeightRecord.id.asc())
            )
        )
        .scalars()
        .all()
    )
    actual_change = (
        round(float(weights[-1].weight) - float(weights[0].weight), 3) if len(weights) >= 2 else 0.0
    )
    deficit_sum = float(
        await session.scalar(
            select(func.coalesce(func.sum(DailySnapshot.deficit), 0)).where(
                DailySnapshot.user_id == user_id,
                DailySnapshot.snapshot_date >= start,
                DailySnapshot.snapshot_date <= today,
            )
        )
        or 0
    )
    return calorie.weekly_neat_calibration(
        actual_change_kg=actual_change, predicted_deficit_kcal=deficit_sum
    )


async def _meals_summary(session: AsyncSession, user_id: int, day: date) -> list[MealSummary]:
    rows = (
        await session.execute(
            select(
                MealRecord.meal_type,
                func.coalesce(func.sum(MealRecord.calories), 0).label("kcal"),
            )
            .where(MealRecord.user_id == user_id, MealRecord.record_date == day)
            .group_by(MealRecord.meal_type)
            .order_by(MealRecord.meal_type)
        )
    ).all()
    return [
        MealSummary(
            meal_type=int(r.meal_type),
            name=MEAL_LABELS.get(int(r.meal_type), "加餐"),
            calories=round(float(r.kcal), 1),
        )
        for r in rows
    ]


async def _daily_account(
    session: AsyncSession,
    user_id: int,
    day: date,
    res: calorie.CalorieResult,
    activity_level: int | None,
) -> DailyAccount:
    """由引擎结果组装 DailyAccount（含当日已选状态与摄入明细）。"""
    return DailyAccount(
        date=day,
        bmr=res.bmr,
        pal=res.pal,
        neat=res.neat,
        eat=res.eat,
        tef=res.tef,
        tee=res.tee,
        intake=res.intake,
        deficit=res.deficit,
        steps=res.steps,
        calories_burnt=res.calories_burnt,
        calibration_used=res.calibration_used,
        today_left=res.today_left,
        activity_level=activity_level,
        meals=await _meals_summary(session, user_id, day),
    )


async def get_today(session: AsyncSession, user_id: int) -> DailyAccount:
    """今日账户：确保快照最新（幂等重算），返回 DailyAccount（含当日已选状态）。"""
    day = datetime.now(TZ).date()
    res = await upsert_snapshot(session, user_id, day)
    return await _daily_account(
        session, user_id, day, res, await _selected_status_level(session, user_id, day)
    )


async def set_today_status(
    session: AsyncSession, user_id: int, activity_level: int
) -> DailyAccount:
    """写入当日所选状态并重算当日快照（F-01，§2.3.1「今天什么状态」/§6.3.3 第一层粗调）。

    状态落 `daily_snapshot.activity_level`；当日 PAL/NEAT 即时按该状态取值（不改 TEE 结构），
    之后任意重算（饮食/运动写操作）仍读该列，未选则回退建档 activity_level。未建档抛 3001。
    """
    day = datetime.now(TZ).date()
    res = await compute_result(session, user_id, day, activity_level=activity_level)
    await upsert_snapshot(session, user_id, day, res, activity_level=activity_level)
    return await _daily_account(session, user_id, day, res, activity_level)


async def get_trend(
    session: AsyncSession, user_id: int, start: date | None, end: date | None
) -> AccountTrendData:
    """按日趋势：【假设】缺省最近 7 天；返回已有快照（无快照的日期不造数）。"""
    today = datetime.now(TZ).date()
    end = end or today
    start = start or (end - timedelta(days=6))
    rows = (
        (
            await session.execute(
                select(DailySnapshot)
                .where(
                    DailySnapshot.user_id == user_id,
                    DailySnapshot.snapshot_date >= start,
                    DailySnapshot.snapshot_date <= end,
                )
                .order_by(DailySnapshot.snapshot_date)
            )
        )
        .scalars()
        .all()
    )
    return AccountTrendData(
        items=[
            DailyTrendItem(
                date=r.snapshot_date,
                intake=float(r.intake or 0),
                tee=float(r.tee or 0),
                deficit=float(r.deficit or 0),
                steps=int(r.steps or 0),
                calories_burnt=float(r.calories_burnt or 0),
            )
            for r in rows
        ]
    )


# G7 账号注销（级联清除，04 §6.3「删除账号级联清除可清除数据」）

# 所有外键指向 public."user"(id) 的表（用 PG 目录动态枚举，含无 ON DELETE CASCADE 的表，
# 如 user_benefit/ai_dialog/invite/order/coupon/… 与分区归档父表）。
# 只取父表（NOT relispartition），避免分区子表重复；列名可为多列（invite/user_a·user_b）。
_USER_FK_SQL = text(
    """
    SELECT rel.relname AS child_table, att.attname AS child_column
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_class frel ON frel.oid = con.confrelid
    JOIN pg_attribute att
      ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
    WHERE con.contype = 'f'
      AND frel.relname = 'user'
      AND frel.relnamespace = 'public'::regnamespace
      AND rel.relnamespace = 'public'::regnamespace
      AND NOT rel.relispartition
    """
)

# 含 `user_id` 列（且非分区子表）的全部 public 表。除「外键指向 user」外，还需覆盖
# 无外键但带 `user_id` 的埋点表（track_event / track_event_archive）：其 user_id 无 FK，
# 仅靠 _USER_FK_SQL 收集不到 → 注销后会残留。relkind 'p' 为分区父表（DELETE 级联清分区）。
_USER_ID_COL_SQL = text(
    """
    SELECT rel.relname AS table_name
    FROM pg_attribute att
    JOIN pg_class rel ON rel.oid = att.attrelid
    JOIN pg_namespace ns ON ns.oid = rel.relnamespace
    WHERE att.attname = 'user_id'
      AND att.attnum > 0
      AND NOT att.attisdropped
      AND rel.relkind IN ('r', 'p')
      AND ns.nspname = 'public'
      AND NOT rel.relispartition
    """
)

# 目标集合内表与表之间的外键（child 引用 parent），带引用列对被删时的过滤/排序复用。
_FK_EDGE_SQL = text(
    """
    SELECT DISTINCT rel.relname AS child, frel.relname AS parent,
                    att.attname AS child_col, fatt.attname AS parent_col
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_class frel ON frel.oid = con.confrelid
    JOIN LATERAL unnest(con.conkey, con.confkey) AS k(child_attnum, parent_attnum) ON true
    JOIN pg_attribute att
      ON att.attrelid = con.conrelid AND att.attnum = k.child_attnum
    JOIN pg_attribute fatt
      ON fatt.attrelid = con.confrelid AND fatt.attnum = k.parent_attnum
    WHERE con.contype = 'f'
      AND rel.relnamespace = 'public'::regnamespace
      AND frel.relnamespace = 'public'::regnamespace
      AND NOT rel.relispartition
    """
)


def _referencing_closure(
    roots: set[str], edges: list[tuple[str, str, str, str]]
) -> set[str]:
    """删除集合的递归闭包：凡（直接/间接）引用集合内表的表都纳入。

    仅「FK→user ∪ 含 user_id 列」不足：merchant / order 被 coupon_pool、redeem_log、
    merchant_sku、merchant_account 等**无 user_id 列**的下游表引用（FK 无 CASCADE），
    不纳入就会在删父表时外键违约 → 500。闭包保证所有引用者都在删除集合内。
    """
    closure = set(roots)
    changed = True
    while changed:
        changed = False
        for child, parent, _ccol, _pcol in edges:
            if parent in closure and child not in closure:
                closure.add(child)
                changed = True
    return closure


def _delete_order(tables: set[str], edges: list[tuple[str, str]]) -> list[str]:
    """按 FK 依赖给出删除顺序：引用方（child）先于被引用方（parent）。

    以 child→parent 边构造 `children[parent] = [child...]`，对受影响表做**后序 DFS**
    （先递归删除所有引用该表的子表，再删自身），确保被引用的行总在其引用者之后删除，
    不会因子表 `NO ACTION` 外键报错。**不依赖表名字母序**——字母序可能把父表（如 food）
    排在子表（如 meal_record）之前，导致外键违约。
    """
    children: dict[str, list[str]] = {t: [] for t in tables}
    for child, parent in edges:
        if child in tables and parent in tables and child not in children[parent]:
            children[parent].append(child)
    order: list[str] = []
    seen: set[str] = set()

    def visit(table: str) -> None:
        if table in seen:
            return
        seen.add(table)
        for child in children[table]:
            visit(child)
        order.append(table)  # 先删所有引用它的子表，再删自身（子表优先）

    for t in sorted(tables):
        visit(t)
    return order


def _membership_pred(
    table: str,
    direct_cols: dict[str, list[str]],
    child_edges: dict[str, list[tuple[str, str, str]]],
    cache: dict[str, str],
    stack: set[str],
) -> str:
    """返回「该表属于被注销用户的行」的 SQL 布尔片段（用于 `DELETE ... WHERE <片段>`）。

    - 直接命中：`"col" = :uid`（FK→user 的列 / 含 user_id 的列）；
    - 间接触达：`"ccol" IN (SELECT "pcol" FROM parent WHERE <parent 归属片段>)`，沿 FK 边递归。
    删除按「子表优先」序执行，删子表时其父表行仍在 → 子查询可正常取到父表的 id。
    """
    if table in cache:
        return cache[table]
    if table in stack:  # 自引用/环：保守返回 FALSE，避免无限递归
        return "FALSE"
    stack.add(table)
    preds = [f'"{col}" = :uid' for col in direct_cols.get(table, [])]
    for child_col, parent, parent_col in child_edges.get(table, []):
        parent_pred = _membership_pred(parent, direct_cols, child_edges, cache, stack)
        preds.append(
            f'"{child_col}" IN (SELECT "{parent_col}" FROM "{parent}" WHERE {parent_pred})'
        )
    stack.discard(table)
    result = "(" + " OR ".join(preds) + ")" if preds else "FALSE"
    cache[table] = result
    return result


async def delete_account(session: AsyncSession, user_id: int) -> bool:
    """级联清除用户及其全部关联数据（单事务），最后删 "user" 行。

    - 根集合 = 「外键指向 `"user"(id)` 的表」（含无 ON DELETE CASCADE 的 user_benefit/
      ai_dialog/invite/order/coupon/… 与归档分区父表）∪「含 `user_id` 列的表」
      （后者覆盖 track_event / track_event_archive 等无 FK 的埋点表，避免注销后残留）；
    - 再取**下游引用闭包**（所有引用根集合表的表，如 merchant→coupon_pool、order→redeem_log），
      保证删除父表前其子表数据已清除；
    - 按 FK 依赖的**拓扑序（子表先于父表）**逐表删除：直接命中表用 `"列" = :uid`，
      间接触达表用 `"子列" IN (SELECT "父列" FROM 父表 WHERE <父表归属片段>)` 子查询；
    - 同一事务内完成，最终删 `"user"` 行；用户不存在时返回 False（幂等，无残留）。

    返回是否真正删除了 `"user"` 行。
    """
    fk_rows = (await session.execute(_USER_FK_SQL)).all()
    direct_cols: dict[str, list[str]] = {}
    for table, column in fk_rows:
        cols = direct_cols.setdefault(table, [])
        if column not in cols:
            cols.append(column)

    # 补充无外键但含 `user_id` 列的表（track_event 等）：按列值一并清除。
    for (table,) in (await session.execute(_USER_ID_COL_SQL)).all():
        cols = direct_cols.setdefault(table, [])
        if "user_id" not in cols:
            cols.append("user_id")

    full_edges = [
        (child, parent, child_col, parent_col)
        for child, parent, child_col, parent_col in (await session.execute(_FK_EDGE_SQL)).all()
    ]
    closure = _referencing_closure(set(direct_cols), full_edges)
    order = _delete_order(closure, [(c, p) for c, p, _cc, _pc in full_edges])

    child_edges: dict[str, list[tuple[str, str, str]]] = {}
    for child, parent, child_col, parent_col in full_edges:
        if child in closure and parent in closure:
            child_edges.setdefault(child, []).append((child_col, parent, parent_col))

    cache: dict[str, str] = {}
    try:
        for table in order:
            pred = _membership_pred(table, direct_cols, child_edges, cache, set())
            await session.execute(text(f'DELETE FROM "{table}" WHERE {pred}'), {"uid": user_id})
        result = await session.execute(
            text('DELETE FROM "user" WHERE id = :uid'), {"uid": user_id}
        )
        deleted = bool(result.rowcount)
        await session.commit()
        return deleted
    except Exception:
        await session.rollback()
        raise
