"""微信登录服务：code2session（httpx）+ 用户/身份/权益 upsert + JWT 签发 + session_key 持久化。"""

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.db.redis import get_redis
from app.models import BodyProfile, User, UserAuth, UserBenefit
from app.schemas.auth import LoginData, RefreshData, UserBrief
from app.schemas.common import ErrorCode

logger = get_logger(__name__)

CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"

PROVIDER_WECHAT_MP = "wechat_mp"  # 登录渠道（001_schema.sql user_auth.provider 约定）
INIT_AI_TIMES = 10  # 新用户初始 AI 对话次数（user_benefit.ai_times_left 默认）

# 无微信凭证属**部署缺陷**，不该把配置项名投给终端用户：该 message 经 envelope 直达
# login.vue 的 toast.error(e.message)。故对外只给通用文案，缺哪个变量只写进日志。
LOGIN_UNAVAILABLE_MSG = "登录服务未就绪，请稍后重试"

# ---- 微信运动 session_key 持久化（F-09 解密链路的唯一合法密钥来源）----
# 官方口径：session_key 来自 code2Session，**会话态**、每次 wx.login 都会换发新的，
# 解密敏感数据必须用"同一次登录"拿到的 key，且服务端绝不可下发给客户端。
# TTL 取 24h 的理由：
#   1) 微信运动是**按天**数据（stepInfoList 固定 31 条按天记录，无逐时），一次登录到
#      当次 /api/steps/sync 落在同一自然日内，24h 已覆盖真实使用窗口；
#   2) 每次登录都会覆盖写新值，所以 TTL 只决定"用户不再登录时旧 key 还能被读多久"——
#      key 一旦被微信轮换，旧值只会让解密失败（无正确性收益、只有长期存密钥的风险）；
#   3) 上限按任务口径压到 ≤24h，与 access(2h)/refresh(7d) 相比取"一天"这个数据粒度。
SESSION_KEY_TTL_SECONDS = 24 * 3600
SESSION_KEY_REDIS_PREFIX = "wx:session_key"


def session_key_redis_key(user_id: int) -> str:
    """按用户存取的 Redis 键名（user_id 维度：与 openid 一对一，解密侧只拿得到 user_id）。"""
    return f"{SESSION_KEY_REDIS_PREFIX}:{user_id}"


async def store_session_key(user_id: int, session_key: str) -> None:
    """登录后按用户持久化 session_key，供微信运动步数解密读取。

    敏感凭据：**只落 Redis，绝不下发客户端、绝不写进日志**（日志只记失败原因）。
    Redis 不可用 / 写失败一律吞掉并 warning——不能因为存不下 key 就把用户挡在登录外
    （步数解密会明确降级为客户端传入值，见 `app/services/steps.py`）。
    """
    if not session_key:
        return  # code2session 未返回 key（微信侧异常/测试桩），无值可存
    try:
        redis = await get_redis()
        if redis is None:
            logger.warning("Redis 不可用，session_key 未持久化（微信步数解密将明确降级为传入值）")
            return
        await redis.set(session_key_redis_key(user_id), session_key, ex=SESSION_KEY_TTL_SECONDS)
    except Exception as exc:  # Redis 异常一律降级，不影响登录
        logger.warning("session_key 持久化失败，登录不受影响", extra={"reason": str(exc)})


async def get_session_key(user_id: int) -> str:
    """取该用户最近一次登录的 session_key；无值 / 已过期 / Redis 不可用 → 返回 ""（调用方降级）。"""
    try:
        redis = await get_redis()
        if redis is None:
            return ""
        return await redis.get(session_key_redis_key(user_id)) or ""
    except Exception as exc:  # 读取失败按"无 key"处理，由调用方明确降级
        logger.warning("session_key 读取失败，按无 key 降级", extra={"reason": str(exc)})
        return ""


async def code2session(code: str, settings: Settings | None = None) -> dict:
    """wx.login code 换 openid/session_key（真实调用微信 sns/jscode2session）。

    WECHAT_APPID/SECRET 任一为空即视为部署缺陷：**明确 1001 失败，不派生 openid**
    （原 mock 分支会伪造身份，已删除；测试改由 conftest 打桩 code2session）。
    缺哪个变量只记日志，对外给通用文案（见 LOGIN_UNAVAILABLE_MSG 注释）。
    """
    s = settings or get_settings()
    if not s.WECHAT_APPID or not s.WECHAT_SECRET:
        missing = [k for k in ("WECHAT_APPID", "WECHAT_SECRET") if not getattr(s, k)]
        logger.warning("微信登录未配置，拒绝派生身份", extra={"missing_config": ",".join(missing)})
        raise AppException(ErrorCode.UNAUTHORIZED, LOGIN_UNAVAILABLE_MSG)

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

    # 官方口径：微信运动等敏感数据的解密必须用**同一次** code2Session 的 session_key，
    # 而它每次 wx.login 都会轮换 —— 故登录成功后立刻按用户持久化（Redis + TTL，见上）。
    # 放在 commit 之后：用户行没落盘就先存密钥会留下无主 key；持久化失败不影响登录。
    await store_session_key(user.id, session_data.get("session_key") or "")

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
