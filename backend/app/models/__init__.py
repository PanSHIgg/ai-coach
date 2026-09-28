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
    func,
)
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
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invite_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    created_at: Mapped[datetime] = _ts()


class Invite(Base):
    __tablename__ = "invite"
    __table_args__ = (UniqueConstraint("invitee_id", name="invite_invitee_id_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inviter_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"), index=True)
    invitee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user.id"))
    status: Mapped[int] = mapped_column(SmallInteger, server_default="0", default=0)
    reward_granted: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
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


__all__ = [
    "Base",
    "BodyProfile",
    "DailySnapshot",
    "Food",
    "FoodAlias",
    "Invite",
    "MealRecord",
    "SportRecord",
    "StepRecord",
    "Subscription",
    "User",
    "UserAuth",
    "UserBenefit",
    "WeightRecord",
]
