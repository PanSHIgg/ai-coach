"""微信登录服务：code2session（httpx）+ mock 分支 + 用户/身份/权益 upsert + JWT 签发。"""

import hashlib

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models import BodyProfile, User, UserAuth, UserBenefit
from app.schemas.auth import LoginData, RefreshData, UserBrief
from app.schemas.common import ErrorCode

CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"

PROVIDER_WECHAT_MP = "wechat_mp"  # 登录渠道（001_schema.sql user_auth.provider 约定）
INIT_AI_TIMES = 10  # 新用户初始 AI 对话次数（user_benefit.ai_times_left 默认）


async def code2session(code: str, settings: Settings | None = None) -> dict:
    """wx.login code 换 openid/session_key。

    WECHAT_APPID/SECRET 未配置时走 mock：openid 由 code 确定性派生，
    本地与测试环境零依赖可跑（P0 默认决策，Phase1 联调后关闭）。
    """
    s = settings or get_settings()
    if not s.WECHAT_APPID or not s.WECHAT_SECRET:
        openid = "mock-" + hashlib.md5(code.encode()).hexdigest()[:16]
        return {"openid": openid, "session_key": "", "mock": True}

    params = {
        "appid": s.WECHAT_APPID,
        "secret": s.WECHAT_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(CODE2SESSION_URL, params=params)
        resp.raise_for_status()
        payload = resp.json()
    if payload.get("errcode"):
        # 登录失败统一按未认证处理（错误码表未细分微信侧错误）
        raise AppException(ErrorCode.UNAUTHORIZED, f"微信登录失败: {payload.get('errmsg')}")
    return {
        "openid": payload["openid"],
        "session_key": payload.get("session_key", ""),
        "unionid": payload.get("unionid"),
        "mock": False,
    }


async def _ensure_user_auth(
    session: AsyncSession, user_id: int, openid: str, unionid: str | None
) -> None:
    """按 (provider, openid) 幂等补建 user_auth（ON CONFLICT DO NOTHING，防并发唯一冲突 500）。"""
    await session.execute(
        pg_insert(UserAuth)
        .values(
            user_id=user_id,
            provider=PROVIDER_WECHAT_MP,
            openid=openid,
            unionid=unionid,
        )
        .on_conflict_do_nothing(index_elements=["provider", "openid"])
    )


async def _ensure_user_benefit(session: AsyncSession, user_id: int) -> None:
    """一人一条 user_benefit（初始 tier=0、ai_times_left=10）；ON CONFLICT DO NOTHING 保证幂等。"""
    await session.execute(
        pg_insert(UserBenefit)
        .values(user_id=user_id, tier=0, ai_times_left=INIT_AI_TIMES)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )


async def login(session: AsyncSession, code: str, settings: Settings | None = None) -> LoginData:
    """code → code2session → upsert user/user_auth/user_benefit → 签发 access(2h)/refresh(7d)。

    幂等：同一 openid 重复登录不重复建 user/user_auth/user_benefit（一人一条）。
    is_new=是否本次新建 user；need_profile=body_profile 是否存在。
    """
    s = settings or get_settings()
    session_data = await code2session(code, s)
    openid = session_data["openid"]
    unionid = session_data.get("unionid")

    user = (await session.execute(select(User).where(User.openid == openid))).scalar_one_or_none()
    is_new = user is None
    if user is None:
        # 并发首登：ON CONFLICT DO NOTHING 避免两个请求同时 INSERT 触发唯一约束 → 500
        await session.execute(
            pg_insert(User)
            .values(openid=openid, unionid=unionid, gender=0, status=1)
            .on_conflict_do_nothing(index_elements=["openid"])
        )
        user = (await session.execute(select(User).where(User.openid == openid))).scalar_one()
    if not user.nickname:
        user.nickname = f"减友{user.id % 10000:04d}"

    await _ensure_user_auth(session, user.id, openid, unionid)
    await _ensure_user_benefit(session, user.id)

    profile = (
        await session.execute(select(BodyProfile).where(BodyProfile.user_id == user.id))
    ).scalar_one_or_none()
    need_profile = profile is None

    await session.commit()

    return LoginData(
        token=create_access_token(str(user.id), s, openid=openid),
        refresh_token=create_refresh_token(str(user.id), s, openid=openid),
        is_new=is_new,
        need_profile=need_profile,
        user=UserBrief(id=user.id, nickname=user.nickname, avatar_url=user.avatar_url),
    )


async def refresh(session: AsyncSession, refresh_token: str) -> RefreshData:
    """refresh_token（typ=refresh）换发新 access + refresh；失效/类型不符统一 1001。"""
    payload = decode_token(refresh_token, expected_type="refresh")
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise AppException(ErrorCode.UNAUTHORIZED) from exc
    user = await session.get(User, user_id)
    if user is None:
        raise AppException(ErrorCode.UNAUTHORIZED)
    return RefreshData(
        token=create_access_token(str(user.id), openid=user.openid),
        refresh_token=create_refresh_token(str(user.id), openid=user.openid),
    )
