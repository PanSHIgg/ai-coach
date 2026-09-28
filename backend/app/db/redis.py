"""Redis 连接管理：惰性连接、不可用不崩（返回 None，由调用方降级）。"""

import time

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: aioredis.Redis | None = None
_init_failed = False  # 连接失败后置位；冷却期后允许重试，避免每请求等待超时
_last_fail_ts = 0.0  # 上次失败时间（monotonic）
_RETRY_INTERVAL = 30.0  # 失败后冷却 30s 才再次尝试连接


async def get_redis() -> aioredis.Redis | None:
    """获取可用 Redis 客户端；不可用返回 None（不抛异常）。"""
    global _client, _init_failed, _last_fail_ts
    if _client is not None:
        return _client
    if _init_failed and time.monotonic() - _last_fail_ts < _RETRY_INTERVAL:
        return None
    try:
        client = aioredis.from_url(
            get_settings().REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        await client.ping()
        _client = client
        _init_failed = False
        return _client
    except Exception as exc:  # noqa: BLE001 - 连接失败一律降级
        logger.warning("Redis 连接不可用，相关功能降级", extra={"reason": str(exc)})
        _init_failed = True
        _last_fail_ts = time.monotonic()
        return None


async def close_redis() -> None:
    """应用关闭时释放连接。"""
    global _client, _init_failed
    if _client is not None:
        await _client.aclose()
    _client = None
    _init_failed = False
