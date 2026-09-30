"""Redis 连接管理：惰性连接、不可用不崩（返回 None，由调用方降级）。

连接与**当前运行事件循环**绑定：`redis.asyncio` 的连接池在创建时即绑定当时的事件
循环，跨 loop 复用会在连接回收时抛「RuntimeError: Event loop is closed」。pytest 每个
用例独立事件循环，故缓存「客户端 + 其所属 loop」，仅当 loop 相同才复用；否则丢弃旧
连接并在新 loop 重建。生产单 loop 运行下等价于原「进程级单例」行为。
"""

import asyncio
import time

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: aioredis.Redis | None = None
_client_loop: asyncio.AbstractEventLoop | None = None  # _client 所属事件循环
_init_failed = False  # 连接失败后置位；冷却期后允许重试，避免每请求等待超时
_last_fail_ts = 0.0  # 上次失败时间（monotonic）
_RETRY_INTERVAL = 30.0  # 失败后冷却 30s 才再次尝试连接


async def get_redis() -> aioredis.Redis | None:
    """获取当前事件循环可用的 Redis 客户端；不可用返回 None（不抛异常）。"""
    global _client, _client_loop, _init_failed, _last_fail_ts
    loop = asyncio.get_running_loop()
    if _client is not None:
        # 复用条件：同为当前 loop，或外部注入且尚未绑定 loop（如测试直接赋值 _client）
        if _client_loop is None or _client_loop is loop:
            return _client
        # 事件循环已切换：旧连接绑定旧 loop，禁止复用，丢弃后重建。
        # 不在此处 aclose：旧 loop 可能已关闭，关闭动作会再次触发 Event loop is closed。
        _client = None
        _client_loop = None
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
        _client_loop = loop
        _init_failed = False
        return _client
    except Exception as exc:  # noqa: BLE001 - 连接失败一律降级
        logger.warning("Redis 连接不可用，相关功能降级", extra={"reason": str(exc)})
        _init_failed = True
        _last_fail_ts = time.monotonic()
        return None


async def close_redis() -> None:
    """在**当前**事件循环内释放连接（应用关闭 / 测试用例收尾调用）。"""
    global _client, _client_loop, _init_failed
    loop = asyncio.get_running_loop()
    if _client is not None and _client_loop is loop:
        try:
            await _client.aclose()
        except Exception as exc:  # noqa: BLE001 - 关闭失败不阻断收尾
            logger.debug("Redis 客户端关闭失败", extra={"reason": str(exc)})
    _client = None
    _client_loop = None
    _init_failed = False
