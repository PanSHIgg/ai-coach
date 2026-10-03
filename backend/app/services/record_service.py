"""记录域服务（BE3）：食物搜索、饮食记录 CRUD、运动记录。

口径与默认决策：
- 食物搜索：pg_trgm 中文可用检索——name / food_alias.alias 的 ILIKE 子串命中（GIN trgm
  索引可加速，见 0010 迁移）+ `similarity()` 排序；仅 status=1。弃用 `to_tsvector('simple')`
  （不切中文，会漏中文子串）；ILIKE 对中文/英文/拼音同样有效。
- 饮食写入：calories = food.calories_100g × amount_g/100，蛋白/脂/碳同理；热量 round 1 位、
  营养素 round 2 位；保存 food_name_snapshot 快照；record_date 默认当日（UTC+8）。
- 运动消耗【假设】= MET × 体重(kg) × 时长(h)；体重取 body_profile.current_weight，缺失默认 60kg；
  met 缺省按 sport_name 映射标准表（文档未给全，常量表见 SPORT_MET）。
- 写后重算：饮食/运动写入后重算当日快照（account.upsert_snapshot，等价 recompute_day；后者返回
  None，此处直接取其计算结果供返回值使用）。
- 行级隔离：所有查询/更新/删除带 user_id，越权/不存在统一 3001。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models import Food, FoodAlias, MealRecord, SportRecord
from app.schemas.common import ErrorCode, PageMeta
from app.schemas.record import (
    FoodCustomData,
    FoodItem,
    FoodSearchData,
    MealCreatedData,
    MealDeleteData,
    MealPageData,
    MealRecordOut,
    SportCreatedData,
    SportPageData,
    SportRecordOut,
)
from app.services import account

TZ = timezone(timedelta(hours=8))

# 运动 MET 标准表（默认决策：文档仅给慢跑/快走/游泳/骑行/跳绳/瑜伽，其余取业界常见值）
SPORT_MET: dict[str, float] = {
    "慢跑": 8.0,
    "跑步": 8.0,
    "快走": 4.3,
    "走路": 4.3,
    "散步": 2.5,
    "游泳": 6.0,
    "骑行": 6.0,
    "骑车": 6.0,
    "跳绳": 10.0,
    "瑜伽": 2.5,
    "羽毛球": 5.5,
    "篮球": 6.5,
    "健身": 5.0,
    "力量训练": 5.0,
    "爬楼": 4.0,
    "爬楼梯": 4.0,
    "普拉提": 3.0,
    "太极": 3.0,
    "广场舞": 4.5,
}
DEFAULT_SPORT_MET = 6.0  # 名字未命中时的中等强度默认值
DEFAULT_WEIGHT_KG = 60.0  # 无档案时的默认体重
# meal_record.calories 为 NUMERIC(8,1) 上限 9999999.9；daily_snapshot.intake 为 NUMERIC(7,1)
# 上限 999999.9；超上界写库会 500，统一前置为 2001。
CALORIES_MAX = 999999.9
# meal_record.protein/fat/carb 为 NUMERIC(7,2) 上限 99999.99；单条计算值超限前置 2001。
MACRO_MAX = 99999.99
# daily_snapshot.intake/eat/tee 均 NUMERIC(7,1)（上限 999999.9）：当日合计设业务上界 20000kcal，
# 防止「多条记录叠加」把快照列写溢出（account.py 为冻结文件，聚合校验在此自行完成）。
DAILY_INTAKE_MAX = 20000.0  # 当日饮食合计 kcal 上限
DAILY_EAT_MAX = 20000.0  # 当日运动消耗合计 kcal 上限


def today_tz() -> date:
    """业务当日（UTC+8）。"""
    return datetime.now(TZ).date()


def _ensure_aware(dt: datetime) -> datetime:
    """naive datetime 按 UTC+8 补时区（避免 asyncpg 对 timestamptz 的 naive 报错）。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=TZ)


# 食物搜索


def _food_item(food: Food) -> FoodItem:
    return FoodItem(
        id=food.id,
        name=food.name,
        calories_100g=float(food.calories_100g),
        protein_100g=float(food.protein_100g) if food.protein_100g is not None else None,
        fat_100g=float(food.fat_100g) if food.fat_100g is not None else None,
        carb_100g=float(food.carb_100g) if food.carb_100g is not None else None,
        gi=float(food.gi) if food.gi is not None else None,
    )


def _visible_clause(user_id: int):
    """可见性：平台食物（owner 为 NULL）或本人自定义食物（F-02，仅本人可见）。"""
    return or_(Food.owner_user_id.is_(None), Food.owner_user_id == user_id)


def _escape_like(value: str) -> str:
    """转义 LIKE 通配符：关键词里的 % / _ 当字面量处理（搭配 ilike(escape="\\\\")）。"""
    for old, new in (("\\", "\\\\"), ("%", "\\%"), ("_", "\\_")):
        value = value.replace(old, new)
    return value


def _food_match_clause(keyword: str):
    """命中条件：name 或别名 ILIKE 子串（pg_trgm GIN 索引可加速）。"""
    pattern = f"%{_escape_like(keyword)}%"
    return or_(
        Food.name.ilike(pattern, escape="\\"),
        Food.id.in_(
            select(FoodAlias.food_id).where(FoodAlias.alias.ilike(pattern, escape="\\"))
        ),
    )


def _food_score(keyword: str):
    """排序分：name 与别名三元组相似度的较大者（精确/更接近者靠前，G10）。"""
    alias_sim = (
        select(func.max(func.similarity(FoodAlias.alias, keyword)))
        .where(FoodAlias.food_id == Food.id)
        .scalar_subquery()
    )
    return func.greatest(func.similarity(Food.name, keyword), func.coalesce(alias_sim, 0.0))


async def _search_by_trgm(
    session: AsyncSession, user_id: int, keyword: str, limit: int
) -> list[Food]:
    """pg_trgm 检索：ILIKE 命中 + similarity 排序，去重由单次查询天然完成。"""
    rows = await session.execute(
        select(Food)
        .where(Food.status == 1, _visible_clause(user_id), _food_match_clause(keyword))
        .order_by(_food_score(keyword).desc(), Food.id)
        .limit(limit)
    )
    return list(rows.scalars().all())


async def search_food(
    session: AsyncSession, user_id: int, keyword: str, limit: int = 20
) -> FoodSearchData:
    """pg_trgm 中文检索：name/别名 ILIKE 命中 + similarity 排序。

    结果含平台食物 + 本人自定义食物（owner_user_id = user_id），不含他人自定义食物。
    """
    kw = keyword.strip()
    if not kw:
        return FoodSearchData(items=[], total=0)
    items = [_food_item(f) for f in await _search_by_trgm(session, user_id, kw, limit)]
    # total 取真实命中总数（单独 count，不受 limit 截断）；条件与检索一致
    total = await session.scalar(
        select(func.count())
        .select_from(Food)
        .where(Food.status == 1, _visible_clause(user_id), _food_match_clause(kw))
    )
    return FoodSearchData(items=items, total=int(total or 0))


async def create_custom_food(session: AsyncSession, user_id: int, payload) -> FoodCustomData:
    """新建用户自定义食物：owner=当前用户、audit_status=0（待审），仅本人可见。"""
    food = Food(
        name=payload.name,
        calories_100g=payload.calories_100g,
        protein_100g=payload.protein_100g,
        fat_100g=payload.fat_100g,
        carb_100g=payload.carb_100g,
        status=1,
        owner_user_id=user_id,
        audit_status=0,
    )
    session.add(food)
    await session.flush()  # 拿到 id 并校验约束
    await session.commit()  # 与 meal 写入一致：请求内提交，后续搜索可见
    return FoodCustomData(
        id=food.id,
        name=food.name,
        calories_100g=float(food.calories_100g),
        audit_status=int(food.audit_status),
    )


# 饮食记录


async def _get_food(session: AsyncSession, food_id: int) -> Food:
    food = (await session.execute(select(Food).where(Food.id == food_id))).scalar_one_or_none()
    if food is None:
        raise AppException(ErrorCode.NOT_FOUND, "食物不存在")
    return food


def _nutrition(food: Food, amount_g: float) -> dict[str, float | None]:
    """按所选食物与分量计算热量/营养素（热量 1 位、营养素 2 位）。

    calories 超 NUMERIC(8,1) 上限（CALORIES_MAX）、蛋白/脂/碳超 NUMERIC(7,2) 上限
    （MACRO_MAX）→ 拒绝（2001），避免单条记录写库溢出 500。
    """
    ratio = amount_g / 100.0
    calories = round(float(food.calories_100g) * ratio, 1)
    if calories > CALORIES_MAX:
        raise AppException(ErrorCode.VALIDATION_ERROR, "分量超出合理范围")
    macros = {
        "protein": round(float(food.protein_100g) * ratio, 2)
        if food.protein_100g is not None
        else None,
        "fat": round(float(food.fat_100g) * ratio, 2) if food.fat_100g is not None else None,
        "carb": round(float(food.carb_100g) * ratio, 2) if food.carb_100g is not None else None,
    }
    for value in macros.values():
        if value is not None and value > MACRO_MAX:
            raise AppException(ErrorCode.VALIDATION_ERROR, "分量或营养值超出范围")
    return {"calories": calories, **macros}


def _meal_out(record: MealRecord) -> MealRecordOut:
    return MealRecordOut(
        id=record.id,
        meal_type=int(record.meal_type),
        food_id=record.food_id,
        food_name=record.food_name_snapshot or "",
        amount_g=float(record.amount_g),
        calories=float(record.calories),
        protein=float(record.protein) if record.protein is not None else None,
        fat=float(record.fat) if record.fat is not None else None,
        carb=float(record.carb) if record.carb is not None else None,
        confidence=float(record.confidence) if record.confidence is not None else None,
        source=int(record.source),
        image_url=record.image_url,
        record_date=record.record_date,
        created_at=record.created_at,
    )


async def _get_own_meal(session: AsyncSession, user_id: int, meal_id: int) -> MealRecord:
    """按 id + user_id 取记录（行级隔离）；不存在/越权统一 3001。"""
    record = (
        await session.execute(
            select(MealRecord).where(MealRecord.id == meal_id, MealRecord.user_id == user_id)
        )
    ).scalar_one_or_none()
    if record is None:
        raise AppException(ErrorCode.NOT_FOUND, "饮食记录不存在")
    return record


async def _day_intake_total(session: AsyncSession, user_id: int, day: date) -> float:
    """当日饮食热量合计（同一事务内 SUM，含已 flush 未提交的写入）。"""
    total = await session.scalar(
        select(func.coalesce(func.sum(MealRecord.calories), 0)).where(
            MealRecord.user_id == user_id, MealRecord.record_date == day
        )
    )
    return float(total or 0)


async def _day_eat_total(session: AsyncSession, user_id: int, day: date) -> float:
    """当日运动消耗合计（UTC+8 日界，同一事务内 SUM）。"""
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


async def create_meal(session: AsyncSession, user_id: int, payload) -> MealCreatedData:
    """新增饮食记录 → 落库并重算当日（同一事务，建档缺失时回滚）。"""
    food = await _get_food(session, payload.food_id)
    day = today_tz()
    record = MealRecord(
        user_id=user_id,
        record_date=day,
        meal_type=payload.meal_type,
        food_id=food.id,
        food_name_snapshot=food.name,
        amount_g=payload.amount_g,
        source=payload.source,
        image_url=payload.image_url,
        **_nutrition(food, payload.amount_g),
    )
    session.add(record)
    await session.flush()  # 拿到 id 并校验约束
    # 当日合计上限校验（同一事务内 SUM，超限抛异常且不 commit → 回滚）
    if await _day_intake_total(session, user_id, day) > DAILY_INTAKE_MAX:
        raise AppException(ErrorCode.VALIDATION_ERROR, "当日摄入合计超出合理范围")
    # 写后重算当日（account.upsert_snapshot 内部即 recompute_day 的核心，直接取结果供返回）
    res = await account.upsert_snapshot(session, user_id, day)
    return MealCreatedData(
        id=record.id,
        calories=float(record.calories),
        today_intake=res.intake,
        today_left=res.today_left,
    )


async def update_meal(
    session: AsyncSession, user_id: int, meal_id: int, payload
) -> MealCreatedData:
    """部分更新饮食记录（至少一字段）；食物/分量变化时重算热量。"""
    sent = payload.model_dump(exclude_unset=True)
    # 常规字段忽略 None；image_url 显式传 null 表示「置空」（区分未传与传 null）
    updates = {k: v for k, v in sent.items() if v is not None}
    if "image_url" in sent and sent["image_url"] is None:
        updates["image_url"] = None
    if not updates:
        raise AppException(ErrorCode.VALIDATION_ERROR, "至少提供一个待更新字段")
    record = await _get_own_meal(session, user_id, meal_id)

    food = None
    if "food_id" in updates:
        food = await _get_food(session, updates["food_id"])
        record.food_id = food.id
        record.food_name_snapshot = food.name
    if "amount_g" in updates:
        record.amount_g = updates["amount_g"]
    # 食物或分量变化 → 重算热量/营养素
    if "food_id" in updates or "amount_g" in updates:
        base_food = food or await _get_food(session, record.food_id)
        for field, value in _nutrition(base_food, float(record.amount_g)).items():
            setattr(record, field, value)
    for field in ("meal_type", "source", "image_url"):
        if field in updates:
            setattr(record, field, updates[field])

    await session.flush()
    # 当日合计上限校验（同一事务内 SUM，超限抛异常且不 commit → 回滚）
    if await _day_intake_total(session, user_id, record.record_date) > DAILY_INTAKE_MAX:
        raise AppException(ErrorCode.VALIDATION_ERROR, "当日摄入合计超出合理范围")
    res = await account.upsert_snapshot(session, user_id, record.record_date)
    return MealCreatedData(
        id=record.id,
        calories=float(record.calories),
        today_intake=res.intake,
        today_left=res.today_left,
    )


async def delete_meal(session: AsyncSession, user_id: int, meal_id: int) -> MealDeleteData:
    """行级隔离删除饮食记录；不存在/越权 → 3001。"""
    record = await _get_own_meal(session, user_id, meal_id)
    day = record.record_date
    await session.execute(delete(MealRecord).where(MealRecord.id == meal_id))
    await session.flush()
    await account.upsert_snapshot(session, user_id, day)
    return MealDeleteData(id=meal_id, deleted=True)


async def list_meals(
    session: AsyncSession,
    user_id: int,
    day: date | None = None,
    meal_type: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> MealPageData:
    """饮食记录分页（user_id 行级隔离，created_at DESC）。"""
    conds = [MealRecord.user_id == user_id]
    if day is not None:
        conds.append(MealRecord.record_date == day)
    if meal_type is not None:
        conds.append(MealRecord.meal_type == meal_type)
    total = await session.scalar(select(func.count()).select_from(MealRecord).where(*conds))
    rows = (
        (
            await session.execute(
                select(MealRecord)
                .where(*conds)
                .order_by(MealRecord.created_at.desc(), MealRecord.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return MealPageData(
        items=[_meal_out(r) for r in rows],
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )


# 运动记录


def resolve_met(sport_name: str | None, met: float | None) -> float:
    """MET 解析：入参优先 → 名字映射 → 默认。"""
    if met is not None:
        return float(met)
    if sport_name:
        matched = SPORT_MET.get(sport_name.strip())
        if matched is not None:
            return matched
    return DEFAULT_SPORT_MET


def compute_sport_calories(met: float, weight_kg: float, duration_min: int) -> float:
    """运动消耗【假设】= MET × 体重(kg) × 时长(h)。"""
    return round(met * weight_kg * (duration_min / 60.0), 1)


def _sport_out(record: SportRecord) -> SportRecordOut:
    return SportRecordOut(
        id=record.id,
        sport_name=record.sport_name,
        met=float(record.met) if record.met is not None else None,
        duration_min=int(record.duration_min),
        calories=float(record.calories),
        record_at=record.record_at,
        created_at=record.created_at,
    )


async def create_sport(session: AsyncSession, user_id: int, payload) -> SportCreatedData:
    """新增运动记录 → 落库并重算当日消耗（同一事务）。"""
    profile = await account.get_body_profile(session, user_id)
    weight = (
        float(profile.current_weight) if profile and profile.current_weight else DEFAULT_WEIGHT_KG
    )
    met = resolve_met(payload.sport_name, payload.met)
    calories = compute_sport_calories(met, weight, payload.duration_min)
    record_at = _ensure_aware(payload.record_at) if payload.record_at else datetime.now(TZ)

    record = SportRecord(
        user_id=user_id,
        sport_name=payload.sport_name,
        met=met,
        duration_min=payload.duration_min,
        calories=calories,
        record_at=record_at,
    )
    session.add(record)
    await session.flush()
    day = record_at.astimezone(TZ).date()
    # 当日运动合计上限校验（同一事务内 SUM，超限抛异常且不 commit → 回滚）
    if await _day_eat_total(session, user_id, day) > DAILY_EAT_MAX:
        raise AppException(ErrorCode.VALIDATION_ERROR, "当日运动消耗合计超出合理范围")
    res = await account.upsert_snapshot(session, user_id, day)
    # res.eat 即当日运动消耗合计（EAT 口径）
    return SportCreatedData(id=record.id, calories=calories, today_burnt=res.eat)


async def list_sports(
    session: AsyncSession,
    user_id: int,
    day: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> SportPageData:
    """运动记录分页（行级隔离；按 record_at DESC）。"""
    conds = [SportRecord.user_id == user_id]
    if day is not None:
        start = datetime.combine(day, time.min, tzinfo=TZ)
        conds.append(SportRecord.record_at >= start)
        conds.append(SportRecord.record_at < start + timedelta(days=1))
    total = await session.scalar(select(func.count()).select_from(SportRecord).where(*conds))
    rows = (
        (
            await session.execute(
                select(SportRecord)
                .where(*conds)
                .order_by(
                    SportRecord.record_at.desc(),
                    SportRecord.created_at.desc(),
                    SportRecord.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return SportPageData(
        items=[_sport_out(r) for r in rows],
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )
