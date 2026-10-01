"""SQLAlchemy ORM 模型（Phase 1 落地）。

真源：`code/data/sql/001_schema.sql`（Alembic 0001 迁移同源）。本模块只映射
Phase 1 需要的表；后续阶段新增表在此按域追加即可（additive）。

约定：
- 数值列 NUMERIC 统一 `asdecimal=False` → Python float，便于热量计算；
- 时间列 TIMESTAMPTZ → `DateTime(timezone=True)`；
- 多状态用 `SmallInteger`；动态结构用 `JSONB`；
- `food.search_vec` 为生成列（GENERATED ALWAYS），模型侧只读映射、不写。
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from geoalchemy2 import Geometry, WKTElement
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """声明式基类。"""


def _ts() -> Mapped[datetime]:
    """created_at 默认（服务端 NOW()）。"""
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# 用户域
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    openid: Mapped[str | None] = mapped_column(String(64), unique=True)
    unionid: Mapped[str | None] = mapped_column(String(64))
    phone_hash: Mapped[str | None] = mapped_column(String(128))
    nickname: Mapped[str | None] = mapped_column(String(64))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    gender: Mapped[int] = mapped_column(SmallInteger, server_default="0", default=0)
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserAuth(Base):
    __tablename__ = "user_auth"
    __table_args__ = (UniqueConstraint("provider", "openid", name="user_auth_provider_openid_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    openid: Mapped[str] = mapped_column(String(64), nullable=False)
    unionid: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()


class UserBenefit(Base):
    __tablename__ = "user_benefit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.id"), unique=True)
    tier: Mapped[int] = mapped_column(SmallInteger, server_default="0", default=0)
    ai_times_left: Mapped[int] = mapped_column(Integer, server_default="10", default=10)
    ai_times_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 权益无期限（docs/changes/2026-10-01-邀请规则变更记录.md）：valid_from/valid_to 已删列
    invite_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    created_at: Mapped[datetime] = _ts()


class Invite(Base):
    """邀请关系（新口径）：注册绑定即有效（status 恒为 1，保留为扩展位）。"""

    __tablename__ = "invite"
    __table_args__ = (
        UniqueConstraint("invitee_id", name="invite_invitee_id_key"),
        CheckConstraint("inviter_id <> invitee_id", name="invite_inviter_id_invitee_id_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inviter_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"), index=True)
    invitee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"))
    # 恒为 1（注册即有效）；保留为扩展位（变更记录 §7.2 审查批注 4）
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    # 同设备防刷标识（可空）：同设备只计 1 次，重复 → 4102
    device_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------------------
# 身体档案与记录域
# ---------------------------------------------------------------------------


class BodyProfile(Base):
    __tablename__ = "body_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), unique=True
    )
    gender: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    height_cm: Mapped[float] = mapped_column(Numeric(5, 1, asdecimal=False), nullable=False)
    birth_year: Mapped[int | None] = mapped_column(SmallInteger)
    age: Mapped[int | None] = mapped_column(SmallInteger)
    current_weight: Mapped[float | None] = mapped_column(Numeric(5, 1, asdecimal=False))
    target_weight: Mapped[float | None] = mapped_column(Numeric(5, 1, asdecimal=False))
    target_type: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    activity_level: Mapped[int] = mapped_column(SmallInteger, server_default="2", default=2)
    bmr: Mapped[float | None] = mapped_column(Numeric(7, 1, asdecimal=False))
    target_calories: Mapped[int | None] = mapped_column(Integer)
    goal_pace: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WeightRecord(Base):
    __tablename__ = "weight_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    weight: Mapped[float] = mapped_column(Numeric(5, 1, asdecimal=False), nullable=False)
    record_at: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class Food(Base):
    __tablename__ = "food"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    calories_100g: Mapped[float] = mapped_column(Numeric(7, 1, asdecimal=False), nullable=False)
    protein_100g: Mapped[float | None] = mapped_column(Numeric(6, 2, asdecimal=False))
    fat_100g: Mapped[float | None] = mapped_column(Numeric(6, 2, asdecimal=False))
    carb_100g: Mapped[float | None] = mapped_column(Numeric(6, 2, asdecimal=False))
    gi: Mapped[int | None] = mapped_column(SmallInteger)
    is_standard: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    # 用户自定义食物（F-02）：平台食物 owner 为 NULL；自定义食物仅本人可见
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"), index=True)
    audit_status: Mapped[int] = mapped_column(
        SmallInteger, server_default="0", default=0
    )  # 0待审 1通过 2驳回（仅自定义食物有业务含义）
    # 生成列（GENERATED ALWAYS ... STORED）：只读映射，写入时由数据库维护
    search_vec: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(name, ''))", persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = _ts()


class FoodAlias(Base):
    __tablename__ = "food_alias"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    food_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("food.id", ondelete="CASCADE")
    )
    alias: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)


class MealRecord(Base):
    __tablename__ = "meal_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    food_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("food.id"))
    food_name_snapshot: Mapped[str | None] = mapped_column(String(128))
    amount_g: Mapped[float] = mapped_column(Numeric(7, 1, asdecimal=False), nullable=False)
    calories: Mapped[float] = mapped_column(Numeric(8, 1, asdecimal=False), nullable=False)
    protein: Mapped[float | None] = mapped_column(Numeric(7, 2, asdecimal=False))
    fat: Mapped[float | None] = mapped_column(Numeric(7, 2, asdecimal=False))
    carb: Mapped[float | None] = mapped_column(Numeric(7, 2, asdecimal=False))
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 2, asdecimal=False))
    source: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    image_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class SportRecord(Base):
    __tablename__ = "sport_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    sport_name: Mapped[str | None] = mapped_column(String(128))
    met: Mapped[float | None] = mapped_column(Numeric(4, 2, asdecimal=False))
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    calories: Mapped[float] = mapped_column(Numeric(8, 1, asdecimal=False), nullable=False)
    source: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    record_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _ts()


class StepRecord(Base):
    __tablename__ = "step_record"
    __table_args__ = (
        UniqueConstraint("user_id", "record_date", name="step_record_user_id_record_date_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    steps: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    hourly_json: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", default=dict)
    calibrated_met: Mapped[float | None] = mapped_column(Numeric(4, 2, asdecimal=False))
    created_at: Mapped[datetime] = _ts()


class DailySnapshot(Base):
    __tablename__ = "daily_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "snapshot_date", name="daily_snapshot_user_id_snapshot_date_key"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    bmr: Mapped[float | None] = mapped_column(Numeric(7, 1, asdecimal=False))
    pal: Mapped[float | None] = mapped_column(Numeric(3, 2, asdecimal=False))
    neat: Mapped[float | None] = mapped_column(Numeric(7, 1, asdecimal=False))
    eat: Mapped[float | None] = mapped_column(Numeric(7, 1, asdecimal=False))
    tef: Mapped[float | None] = mapped_column(Numeric(7, 1, asdecimal=False))
    tee: Mapped[float | None] = mapped_column(Numeric(7, 1, asdecimal=False))
    intake: Mapped[float] = mapped_column(
        Numeric(7, 1, asdecimal=False), server_default="0", default=0
    )
    deficit: Mapped[float] = mapped_column(
        Numeric(8, 1, asdecimal=False), server_default="0", default=0
    )
    steps: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    calories_burnt: Mapped[float] = mapped_column(
        Numeric(8, 1, asdecimal=False), server_default="0", default=0
    )
    calibration_used: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    # 当日所选活动状态：1卧床 2久坐 3轻度 4中度 5高度；NULL=未选（回退建档 activity_level）。
    # NEAT 四层融合第一层「状态选择（粗调）」（§2.3.1 / §6.3.3，F-01，0006 迁移加列）。
    activity_level: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = _ts()


class Subscription(Base):
    __tablename__ = "subscription"
    __table_args__ = (
        UniqueConstraint("user_id", "template_type", name="subscription_user_id_template_type_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    template_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    subscribe_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    last_subscribe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# AI 域（Phase 2：对话流水 + RAG 知识库）
# ---------------------------------------------------------------------------


class AiDialog(Base):
    """AI 对话流水（ai_dialog）：按 session_id 串会话，user/assistant 各一行。"""

    __tablename__ = "ai_dialog"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[Uuid | None] = mapped_column(  # type: ignore[valid-type]
        Uuid, server_default=text("uuid_generate_v4()"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64))
    tokens: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()


class AiKnowledge(Base):
    """RAG 知识库（ai_knowledge）：embedding 为 JSONB 占位，检索走 search_vec。"""

    __tablename__ = "ai_knowledge"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[dict | None] = mapped_column(JSONB)  # 【假设】向量占位，不做检索
    source: Mapped[str | None] = mapped_column(String(256))
    # 生成列：只读映射，写入时由数据库维护
    search_vec: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))",
            persisted=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------------------
# 商家与交易域（Phase 3：BE5 商家 / BE6 订单支付核销 / BE9 管理）
# ---------------------------------------------------------------------------


class Merchant(Base):
    """商家（merchant）：LBS 用 PostGIS geo（§7.2 主口径 GEOMETRY(Point,4326)），入驻走审核。"""

    __tablename__ = "merchant"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    address: Mapped[str | None] = mapped_column(Text)
    # 位置（N-7 对齐 §7.2 DDL）：PostGIS 空间列 + GIST 索引（迁移/schema.sql 建）；
    # spatial_index=False 防止 ORM create_all 重复建索引；API 出入参仍 lat/lng 数值
    geo: Mapped[WKTElement | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    phone: Mapped[str | None] = mapped_column(String(32))
    rating: Mapped[float] = mapped_column(
        Numeric(3, 1, asdecimal=False), server_default="5.0", default=5.0
    )
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)  # 1营业 0停业
    audit_status: Mapped[int] = mapped_column(
        SmallInteger, server_default="0", default=0
    )  # 0待审 1通过 2驳回
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"))
    contribution_points: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0
    )  # 贡献分：核销成功累计（每单 +1，0003 迁移加列）
    partner_level: Mapped[int] = mapped_column(
        SmallInteger, server_default="0", default=0
    )  # 合作层级：0普通 1优选合作 2战略合作（R-01，0005 迁移加列）
    last_contribution_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )  # 最近一次贡献（成功核销）时间；连续零贡献清退判定依据（R-01）
    created_at: Mapped[datetime] = _ts()


class SkuCatalog(Base):
    """标准 SKU 目录（sku_catalog）：平台运营维护，商家只选不建。"""

    __tablename__ = "sku_catalog"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    calories_low: Mapped[int | None] = mapped_column(Integer)
    calories_high: Mapped[int | None] = mapped_column(Integer)
    base_price: Mapped[float] = mapped_column(Numeric(8, 2, asdecimal=False), nullable=False)
    min_price: Mapped[float] = mapped_column(Numeric(8, 2, asdecimal=False), nullable=False)
    max_price: Mapped[float] = mapped_column(Numeric(8, 2, asdecimal=False), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    created_at: Mapped[datetime] = _ts()


class MerchantSku(Base):
    """商家 SKU（merchant_sku）：从目录选品定价，(merchant_id, catalog_id) 唯一。"""

    __tablename__ = "merchant_sku"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("merchant.id", ondelete="CASCADE"), index=True
    )
    catalog_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sku_catalog.id"))
    price: Mapped[float] = mapped_column(Numeric(8, 2, asdecimal=False), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, server_default="-1", default=-1)  # -1 无限
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (UniqueConstraint("merchant_id", "catalog_id", name="uk_ms"),)


class CouponPool(Base):
    """券池（coupon_pool）：券发放源头，用户只能经邀请任务/平台补贴获得。"""

    __tablename__ = "coupon_pool"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1满减 2折扣 3免费 4体验
    scope: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1吃 2动 3异业 4通用
    amount: Mapped[float] = mapped_column(
        Numeric(8, 2, asdecimal=False), server_default="0", default=0
    )
    discount_rate: Mapped[float | None] = mapped_column(Numeric(4, 2, asdecimal=False))
    min_spend: Mapped[float] = mapped_column(
        Numeric(8, 2, asdecimal=False), server_default="0", default=0
    )
    merchant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("merchant.id"))
    sponsor: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    total_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)  # -1 不限
    granted_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    created_at: Mapped[datetime] = _ts()


class Coupon(Base):
    """用户券（coupon）：code 为核销码 UUID，唯一索引防重复核销。"""

    __tablename__ = "coupon"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pool_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("coupon_pool.id"))
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scope: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    amount: Mapped[float] = mapped_column(
        Numeric(8, 2, asdecimal=False), server_default="0", default=0
    )
    discount_rate: Mapped[float | None] = mapped_column(Numeric(4, 2, asdecimal=False))
    min_spend: Mapped[float] = mapped_column(
        Numeric(8, 2, asdecimal=False), server_default="0", default=0
    )
    merchant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("merchant.id"))
    sponsor: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    obtain_way: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    obtain_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id"), index=True
    )
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)  # 1未用..
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[int | None] = mapped_column(BigInteger)  # 无 FK，避免循环引用
    created_at: Mapped[datetime] = _ts()


class Order(Base):
    """订单（order）：金额服务端重算（CHECK 强制 pay=total-discount），核销码唯一。"""

    __tablename__ = "order"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"), index=True)
    merchant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("merchant.id"), index=True
    )
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=False)
    discount_amount: Mapped[float] = mapped_column(
        Numeric(10, 2, asdecimal=False), server_default="0", default=0
    )
    pay_amount: Mapped[float] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=False)
    coupon_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("coupon.id"))
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    pay_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeem_code: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OrderItem(Base):
    """订单项（order_item）：SKU 名称/单价快照，防目录变更。"""

    __tablename__ = "order_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("order.id", ondelete="CASCADE"), index=True
    )
    sku_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("merchant_sku.id"))
    sku_name_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=False)
    created_at: Mapped[datetime] = _ts()


class RedeemLog(Base):
    """核销日志（redeem_log）：成功/失败全留痕。"""

    __tablename__ = "redeem_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("order.id"))
    merchant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("merchant.id"))
    operator_user_id: Mapped[int | None] = mapped_column(BigInteger)
    result: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)  # 1成功 2失败
    fail_reason: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = _ts()


class AdminUser(Base):
    """管理后台账号（admin_user）：账号密码登录，role 决定可见范围。"""

    __tablename__ = "admin_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[int] = mapped_column(SmallInteger, server_default="2", default=2)  # 1超管 2运营 3商家
    merchant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("merchant.id"))
    created_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------------------
# 社区与社交域（Phase 4：BE7a 动态 / BE7b 五种社交 / BE7c 内容审核）
# ---------------------------------------------------------------------------


class CommunityPost(Base):
    """社区动态（community_post）：仅 audit_status=1 对外可见，违规进审核队列。"""

    __tablename__ = "community_post"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"))
    title: Mapped[str | None] = mapped_column(String(256))
    content: Mapped[str | None] = mapped_column(Text)
    images: Mapped[list] = mapped_column(JSONB, server_default="'[]'::jsonb", default=list)
    post_type: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    like_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    comment_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    anonymous: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    audit_status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    created_at: Mapped[datetime] = _ts()


class CommunityComment(Base):
    """社区评论（community_comment）：违规内容走审核（msgSecCheck）。"""

    __tablename__ = "community_comment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("community_post.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    anonymous: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    audit_status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    created_at: Mapped[datetime] = _ts()


class CommunityLike(Base):
    """社区点赞（community_like）：(post_id, user_id) 唯一，一人一赞。"""

    __tablename__ = "community_like"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="community_like_post_id_user_id_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("community_post.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()


class CommunityGroup(Base):
    """兴趣社群（community_group）：长期打卡/活动（BE7b）。"""

    __tablename__ = "community_group"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    member_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    city: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()


class Supervise(Base):
    """监督关系（supervise）：互看记录/提醒打卡（BE7b），一人一对唯一。"""

    __tablename__ = "supervise"
    __table_args__ = (UniqueConstraint("user_a", "user_b", name="supervise_user_a_user_b_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_a: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"))
    user_b: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"))
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    days: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    created_at: Mapped[datetime] = _ts()


class Battle(Base):
    """约战（battle）：LBS 匹配/加入/关联场馆券（BE7b）。"""

    __tablename__ = "battle"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(String(256))
    sport_type: Mapped[str | None] = mapped_column(String(64))
    merchant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("merchant.id"))
    city: Mapped[str | None] = mapped_column(String(64), index=True)
    meet_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    need_count: Mapped[int] = mapped_column(Integer, server_default="2", default=2)
    join_count: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    creator_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"))
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    created_at: Mapped[datetime] = _ts()


class Challenge(Base):
    """限时挑战赛（challenge）：进度/排行榜/徽章（BE7b）。"""

    __tablename__ = "challenge"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    badge_image: Mapped[str | None] = mapped_column(Text)
    join_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    created_at: Mapped[datetime] = _ts()


class ChallengeJoin(Base):
    """挑战赛参与（challenge_join）：(challenge_id, user_id) 唯一，一人一赛一次。"""

    __tablename__ = "challenge_join"
    __table_args__ = (
        UniqueConstraint("challenge_id", "user_id", name="challenge_join_challenge_id_user_id_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    challenge_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("challenge.id"))
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"))
    rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Numeric(8, 1, asdecimal=False))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Leaderboard(Base):
    """热量控制榜（leaderboard）：按期（日/周/月）预聚合名次。"""

    __tablename__ = "leaderboard"
    __table_args__ = (
        UniqueConstraint(
            "period_type",
            "period_key",
            "user_id",
            name="leaderboard_period_type_period_key_user_id_key",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_key: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE")
    )
    score: Mapped[float] = mapped_column(
        Numeric(10, 1, asdecimal=False), server_default="0", default=0
    )
    rank: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Review(Base):
    """审核队列（review）：msgSecCheck/imgSecCheck 违规内容与商家入驻审核（BE7c/ADM）。"""

    __tablename__ = "review"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1动态 2评论 3图 4商家
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"))
    content_snapshot: Mapped[str | None] = mapped_column(Text)
    sec_check_result: Mapped[int | None] = mapped_column(SmallInteger)  # 1通过 2可疑 3不通过
    status: Mapped[int] = mapped_column(SmallInteger, server_default="0", default=0)
    reject_reason: Mapped[str | None] = mapped_column(String(256))
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()


class TrackEvent(Base):
    """埋点事件（track_event）：6 项核心指标数据源（F3）。

    user_id 可空（登录前/匿名），高频写入不建 FK（对齐 001_schema.sql 表注释）。
    """

    __tablename__ = "track_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    device_id: Mapped[str | None] = mapped_column(String(64))
    platform: Mapped[int] = mapped_column(SmallInteger, server_default="1", default=1)
    properties: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = _ts()


__all__ = [
    "AdminUser",
    "AiDialog",
    "AiKnowledge",
    "Base",
    "Battle",
    "BodyProfile",
    "Challenge",
    "ChallengeJoin",
    "CommunityComment",
    "CommunityGroup",
    "CommunityLike",
    "CommunityPost",
    "Coupon",
    "CouponPool",
    "DailySnapshot",
    "Food",
    "FoodAlias",
    "Invite",
    "Leaderboard",
    "MealRecord",
    "Merchant",
    "MerchantSku",
    "Order",
    "OrderItem",
    "RedeemLog",
    "Review",
    "SportRecord",
    "StepRecord",
    "Subscription",
    "Supervise",
    "SkuCatalog",
    "TrackEvent",
    "User",
    "UserAuth",
    "UserBenefit",
    "WeightRecord",
]
