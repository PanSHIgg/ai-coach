"""微信登录服务：code2session（httpx）+ mock 分支 + JWT 签发。"""

import hashlib

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.core.security import create_access_token, create_refresh_token
from app.schemas.auth import LoginData, UserBrief
from app.schemas.common import ErrorCode

CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


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


def _stable_user_id(openid: str) -> int:
    """openid → 稳定伪用户 id（P0 无库；Phase1 落 user 表后改为真实自增 id）。"""
    return int(hashlib.md5(openid.encode()).hexdigest()[:12], 16) % 1_000_000_000


async def login(code: str, settings: Settings | None = None) -> LoginData:
    """code → 签发 access(2h)/refresh(7d) JWT。

    TODO(Phase1): 首次登录 upsert user/user_auth 行，need_profile 依 body_profile 是否存在。
    """
    session = await code2session(code, settings)
    user_id = _stable_user_id(session["openid"])
    token = create_access_token(str(user_id), settings, openid=session["openid"])
    refresh = create_refresh_token(str(user_id), settings, openid=session["openid"])
    return LoginData(
        token=token,
        refresh_token=refresh,
        is_new=True,
        need_profile=True,
        user=UserBrief(id=user_id, nickname=f"减友{user_id % 10000:04d}", avatar_url=None),
    )
