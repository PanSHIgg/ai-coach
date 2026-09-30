"""核销后三件套（BE6 补齐）：摄入自动写入 + 商家贡献分 + 社区经验卡。

文档依据：docs/split/01-整体架构与产品需求.md §2.3.2「订单完成 → 商家获贡献分 +
摄入记录自动写入 + 生成社区经验卡」；docs/split/03-页面布局与交互说明.md §5.7
「订单核销：下单→支付→核销码→商家扫码→订单完成→结算」。

由 `order_service.redeem_order` 在核销成功分支、与状态流转 **同一事务** 内调用
（本模块不 commit）：任一子步骤异常 → 整体回滚，订单停留 2已支付待核销，
无任何三件套残留。

【假设】（文档未细化处，按最简可行）：
- meal_record.source 扩展枚举 5=订单核销自动写入（04 文档枚举 1拍照 2语音 3手动 4AI推荐，
  代码侧扩展不回改文档，改动点由主 Agent 同步）；
- 卡路里按 sku_catalog.calories_low/high 的中位数 × 数量估算；目录缺失计 0；
- 订单无克重信息，amount_g 记占位 1（库内 CHECK(amount_g>0)）；food_id 不关联
  （sku_catalog 与 food 无外键）；
- 餐次按核销时刻（UTC+8）划分：<11 早餐 / <16 午餐 / <21 晚餐 / 其余加餐；
- 贡献分：merchant.contribution_points 每成功核销一单 +1（04 文档 merchant 表无此列，
  走 0003 迁移加列，001_schema.sql 同源更新）；
- 经验卡 = community_post(post_type=2)，与读取侧 community_service.list_experience 对齐；
  内容全部由系统拼装（商家名已经入驻审核），免内容安全审核，audit_status 直接置 1。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CommunityPost,
    MealRecord,
    Merchant,
    MerchantSku,
    Order,
    OrderItem,
    SkuCatalog,
)

_TZ = timezone(timedelta(hours=8))  # 业务时区（UTC+8），与 record_service.today_tz 一致
SOURCE_ORDER_REDEEM = 5  # 【假设】meal_record.source 扩展：5=订单核销自动写入
CONTRIBUTION_PER_REDEEM = 1  # 【假设】每成功核销一单，商家贡献分 +1
EXPERIENCE_POST_TYPE = 2  # 经验卡（community_post.post_type，读取侧 list_experience 口径）


def _biz_now() -> datetime:
    """业务当前时刻（UTC+8）。"""
    return datetime.now(_TZ)


def resolve_meal_type(now: datetime) -> int:
    """核销时刻 → 餐次（1早餐 2午餐 3晚餐 4加餐）。"""
    if now.hour < 11:
        return 1
    if now.hour < 16:
        return 2
    if now.hour < 21:
        return 3
    return 4


def _estimate_calories(catalog: SkuCatalog | None, quantity: int) -> float:
    """目录热量区间中位 × 数量；目录缺失计 0。"""
    if catalog is None or catalog.calories_low is None or catalog.calories_high is None:
        return 0.0
    return round((float(catalog.calories_low) + float(catalog.calories_high)) / 2 * quantity, 1)


async def _load_items(session: AsyncSession, order: Order) -> list[OrderItem]:
    return (
        (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id)))
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# 三件套 ①：摄入记录自动写入
# ---------------------------------------------------------------------------


def write_meal_records(
    session: AsyncSession, order: Order, items: list[OrderItem], catalogs: dict[int, SkuCatalog]
) -> list[MealRecord]:
    """按订单项逐条写 meal_record（source=5，卡路里按 SKU 目录热量区间中位×数量）。"""
    now = _biz_now()
    records: list[MealRecord] = []
    for it in items:
        catalog = catalogs.get(it.sku_id) if it.sku_id is not None else None
        record = MealRecord(
            user_id=order.user_id,
            record_date=now.date(),
            meal_type=resolve_meal_type(now),
            food_id=None,  # 【假设】sku_catalog 与 food 无外键，不关联
            food_name_snapshot=it.sku_name_snapshot,
            amount_g=1,  # 【假设】订单无克重信息；库内 CHECK(amount_g>0)，记最小占位 1
            calories=_estimate_calories(catalog, it.quantity),
            source=SOURCE_ORDER_REDEEM,
        )
        session.add(record)
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# 三件套 ②：商家贡献分
# ---------------------------------------------------------------------------


def add_contribution_points(session: AsyncSession, merchant: Merchant) -> int:
    """商家贡献分累加（每成功核销一单 +1【假设】），返回累加后的分值。"""
    merchant.contribution_points = int(merchant.contribution_points or 0) + CONTRIBUTION_PER_REDEEM
    return merchant.contribution_points


# ---------------------------------------------------------------------------
# 三件套 ③：社区经验卡
# ---------------------------------------------------------------------------


def create_experience_card(
    session: AsyncSession, order: Order, merchant: Merchant, items: list[OrderItem]
) -> CommunityPost:
    """生成经验卡：community_post(post_type=2)，内容含商家/订单/菜品/实付信息。"""
    desc = "、".join(f"{it.sku_name_snapshot}×{it.quantity}" for it in items) or "健康餐"
    post = CommunityPost(
        user_id=order.user_id,
        title=f"我在「{merchant.name}」吃上了健康餐",
        content=(
            f"通过 AI 教练下单，在「{merchant.name}」完成到店核销"
            f"（订单号 {order.order_no}）：{desc}，实付 ¥{float(order.pay_amount):.2f}。"
            "减脂期也能好好吃饭，同款减友冲！"
        ),
        images=[],
        post_type=EXPERIENCE_POST_TYPE,
        audit_status=1,  # 【假设】系统拼装内容免内容安全审核
    )
    session.add(post)
    return post


# ---------------------------------------------------------------------------
# 入口：三件套统一编排（不 commit，由调用方在核销事务末尾统一提交）
# ---------------------------------------------------------------------------


async def apply_redeem_aftercare(session: AsyncSession, order: Order, merchant: Merchant) -> None:
    """核销成功后的三件套：写摄入 → 加贡献分 → 生成经验卡。

    仅 add/flush 级操作、不 commit；任一步骤异常向上抛出，
    由「未提交即关闭会话」的语义保证核销整体回滚。
    """
    items = await _load_items(session, order)

    # 订单项 sku_id → SKU 目录（热量区间），一次批量取
    sku_ids = {it.sku_id for it in items if it.sku_id is not None}
    catalog_by_sku: dict[int, SkuCatalog] = {}
    if sku_ids:
        rows = (
            await session.execute(
                select(MerchantSku.id, SkuCatalog)
                .join(SkuCatalog, SkuCatalog.id == MerchantSku.catalog_id)
                .where(MerchantSku.id.in_(sku_ids))
            )
        ).all()
        catalog_by_sku = {sku_id: catalog for sku_id, catalog in rows}

    write_meal_records(session, order, items, catalog_by_sku)
    add_contribution_points(session, merchant)
    create_experience_card(session, order, merchant, items)
