"""限流：Redis INCR+EXPIRE 窗口计数；Redis 不可用时降级进程内字典。

默认阈值（04 文档 §6.3.6，均可经环境变量配置）：
- 全局 100 次/分钟/IP
- 登录 10 次/分钟/IP（/api/auth/*）
- admin 登录 5 次/分钟/IP（/api/admin/login）
- AI 对话 20 次/分钟/用户（/api/ai/*，按 JWT sub，无 token 回退 IP）

IS-004 修复：兼容 Redis 6.x（不支持 EXPIRE NX），改用 SET NX EX + INCR 原子方案。
"""

import time

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError, RedisError, ResponseError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.core.config import Settings, get_settings
from app.core.context import get_request_id
from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.redis import get_redis
from app.schemas.common import ErrorCode, fail

logger = get_logger(__name__)

# 进程内兜底：key -> (count, window_start_monotonic)
_memory_windows: dict[str, tuple[int, float]] = {}

_redis_version_checked = False


async def _check_redis_version(redis) -> None:
    """IS-004: 启动时检查 Redis 版本，低于 7.0 打明确告警。"""
    global _redis_version_checked
    if _redis_version_checked:
        return
    try:
        info = await redis.info("server")
        version = info.get("redis_version", "unknown")
        major = int(version.split(".")[0]) if version != "unknown" else 0
        if major < 7:
            logger.warning(
                f"Redis 版本 {version} < 7.0，限流已降级兼容模式（SET NX EX + INCR）。"
                "建议升级至 Redis 7+ 以获得最佳性能。"
            )
        _redis_version_checked = True
    except Exception as exc:
        logger.debug(f"检查 Redis 版本失败: {exc}")


async def incr_window(key: str, window: int) -> int | None:
    """原子递增计数器，首次调用时设置 TTL。

    使用 SET NX EX + INCR 原子执行，兼容 Redis 6.x。
    返回当前计数，Redis 不可用时返回 None。
    """
    try:
        redis = await get_redis()
        if redis is None:
            return None
        await _check_redis_version(redis)
        async with redis.pipeline(transaction=False) as pipe:
            pipe.set(key, 0, nx=True, ex=window)
            pipe.incr(key)
            _, count = await pipe.execute()
        return int(count)
    except (ConnectionError, TimeoutError) as exc:
        logger.warning(
            "Redis 连接不可用", extra={"key": key, "reason": str(exc)}
        )
    except ResponseError as exc:
        logger.error(
            "Redis 命令不兼容（需 Redis 6+）",
            extra={"key": key, "reason": str(exc)},
        )
    except RedisError as exc:
        logger.warning("Redis 错误", extra={"key": key, "reason": str(exc)})
    return None


async def check_rate_limit(key: str, limit: int, window: int = 60) -> bool:
    """窗口内计数 <= limit 放行。Redis SET NX EX + INCR 原子执行，异常降级进程内字典。

    IS-004: 兼容 Redis 6.x（不支持 EXPIRE NX）。
    """
    redis_key = f"ratelimit:{key}"
    count = await incr_window(redis_key, window)
    if count is not None:
        return count <= limit

    # Redis 不可用，降级进程内字典
    now = time.monotonic()
    count, window_start = _memory_windows.get(key, (0, now))
    if now - window_start >= window:
        count, window_start = 0, now
    count += 1
    _memory_windows[key] = (count, window_start)
    return count <= limit


def _jwt_sub(request: Request) -> str | None:
    """轻量解析 Bearer JWT 的 sub（不查库），失败返回 None。"""
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        try:
            return str(decode_token(authorization[7:].strip(), "access").get("sub"))
        except Exception:  # noqa: BLE001 - 无效 token 回退 IP 维度
            return None
    return None


def resolve_limit(
    path: str, client_ip: str, jwt_sub: str | None, settings: Settings
) -> tuple[str, int]:
    """按路径解析 (限流 key, 每分钟阈值)。

    IS-007: /api/admin/login 纳入严格档（5/min/IP）。
    """
    prefix = f"{settings.API_PREFIX}/"
    if path == f"{prefix}admin/login":
        return f"admin_login:ip:{client_ip}", getattr(settings, "RATE_LIMIT_ADMIN_LOGIN_PER_MIN", 5)
    if path.startswith(f"{prefix}auth/"):
        return f"auth:ip:{client_ip}", settings.RATE_LIMIT_AUTH_PER_MIN
    if path.startswith(f"{prefix}ai/"):
        return f"ai:user:{jwt_sub or client_ip}", settings.RATE_LIMIT_AI_PER_MIN
    return f"global:ip:{client_ip}", settings.RATE_LIMIT_GLOBAL_PER_MIN


class RateLimitMiddleware(BaseHTTPMiddleware):
    """仅作用于 API_PREFIX 下路径；/healthz 等运维端点不限流。"""

    def __init__(self, app: ASGIApp, settings: Settings | None = None) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        settings = self.settings or get_settings()
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        path = request.url.path
        if not path.startswith(f"{settings.API_PREFIX}/"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "anonymous"
        key, limit = resolve_limit(path, client_ip, _jwt_sub(request), settings)
        if not await check_rate_limit(key, limit, settings.RATE_LIMIT_WINDOW_SECONDS):
            logger.warning(
                "请求触发限流",
                extra={"path": path, "limit": limit, "key": key},
            )
            return JSONResponse(
                status_code=429,
                content=fail(ErrorCode.RATE_LIMITED, request_id=get_request_id()),
                headers={"Retry-After": str(settings.RATE_LIMIT_WINDOW_SECONDS)},
            )
        return await call_next(request)
