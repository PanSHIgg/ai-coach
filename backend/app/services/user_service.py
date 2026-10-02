"""用户服务：当前用户详情（/auth/me）与身体档案 upsert（服务端算 BMR/目标热量）。

口径（04 §6.3.1）：BMR=Mifflin-St Jeor；每日热量预算 = BMR × PAL。
age 由 birth_year + 当日推算（异常/缺失回退默认 30，见 calorie.age_from_birth_year）。
"""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models import BodyProfile, User
from app.models import UserBenefit as UserBenefitModel
from app.schemas.common import ErrorCode
from app.schemas.profile import BodyProfileIn
from app.schemas.user import UserBenefit as UserBenefitSchema
from app.schemas.user import UserDetail
from app.services import calorie

# 业务日口径 UTC+8（与 account/record/weight 一致）
_TZ = timezone(timedelta(hours=8))


async def get_body_profile(session: AsyncSession, user_id: int) -> BodyProfile | None:
    """按 user_id 查身体档案（行级隔离）。"""
    return (
        await session.execute(select(BodyProfile).where(BodyProfile.user_id == user_id))
    ).scalar_one_or_none()


async def get_me(session: AsyncSession, user_id: int) -> UserDetail:
    """当前用户详情：user + body_profile + user_benefit；无档案时字段合理缺省。"""
    user = await session.get(User, user_id)
    if user is None:
        # token 指向的用户已不存在 → 视作未认证
        raise AppException(ErrorCode.UNAUTHORIZED)

    profile = await get_body_profile(session, user_id)
    benefit = (
        await session.execute(select(UserBenefitModel).where(UserBenefitModel.user_id == user_id))
    ).scalar_one_or_none()

    return UserDetail(
        id=user.id,
        nickname=user.nickname or f"减友{user.id % 10000:04d}",
        avatar_url=user.avatar_url,
        gender=profile.gender if profile is not None else user.gender,
        benefit=UserBenefitSchema(
            tier=int(benefit.tier) if benefit is not None else 0,
            ai_times_left=int(benefit.ai_times_left) if benefit is not None else 0,
        ),
    )


async def update_avatar(session: AsyncSession, user_id: int, avatar_url: str) -> UserDetail:
    """更新当前用户头像（COS 公开读 URL）→ 回吐更新后的 UserDetail。

    user 不存在（token 指向已删用户）→ 1001，与 get_me 同口径。
    """
    user = await session.get(User, user_id)
    if user is None:
        raise AppException(ErrorCode.UNAUTHORIZED)
    user.avatar_url = avatar_url
    user.updated_at = datetime.now(UTC)
    await session.commit()
    return await get_me(session, user_id)


async def upsert_body_profile(
    session: AsyncSession, user_id: int, payload: BodyProfileIn
) -> BodyProfile:
    """upsert body_profile（user_id 唯一）+ 服务端计算 BMR/目标热量。"""
    # 业务日口径 UTC+8（与 account/record/weight 一致），避免跨 UTC 日界时年龄推算不一致
    age = calorie.age_from_birth_year(payload.birth_year, datetime.now(_TZ).date())
    bmr = calorie.bmr_mifflin_st_jeor(
        gender=payload.gender,
        weight_kg=payload.current_weight,
        height_cm=payload.height_cm,
        age=age,
    )
    target_calories = round(bmr * calorie.pal_for_level(payload.activity_level))

    profile = await get_body_profile(session, user_id)
    if profile is None:
        # 并发首建档：ON CONFLICT DO NOTHING 避免同时 INSERT 触发 user_id 唯一约束 → 500
        await session.execute(
            pg_insert(BodyProfile)
            .values(
                user_id=user_id,
                gender=payload.gender,
                height_cm=payload.height_cm,
                birth_year=payload.birth_year,
                age=age,
                current_weight=payload.current_weight,
                target_weight=payload.target_weight,
                target_type=payload.target_type,
                activity_level=payload.activity_level,
                bmr=bmr,
                target_calories=target_calories,
                goal_pace=payload.goal_pace if payload.goal_pace is not None else 1,
            )
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        profile = await get_body_profile(session, user_id)

    profile.gender = payload.gender
    profile.height_cm = payload.height_cm
    profile.birth_year = payload.birth_year
    profile.age = age
    profile.current_weight = payload.current_weight
    profile.target_weight = payload.target_weight
    profile.target_type = payload.target_type
    profile.activity_level = payload.activity_level
    profile.bmr = bmr
    profile.target_calories = target_calories
    # 未填目标节奏默认每周 0.5kg（档位 1，默认决策 §13.3）
    profile.goal_pace = payload.goal_pace if payload.goal_pace is not None else 1
    profile.updated_at = datetime.now(UTC)

    await session.commit()
    return profile
