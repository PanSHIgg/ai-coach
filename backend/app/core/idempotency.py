"""幂等 / 防重放中间件（Phase 5 F6）。

**约定**：写接口（POST/PUT/PATCH/DELETE，`/api` 前缀）由客户端携带 `Idempotency-Key`
请求头（每个逻辑操作一个唯一值，通常 UUID）。同一 key 在 `IDEMPOTENCY_TTL_SECONDS`
窗口内重复到达时：**仅首次放行，其余返回 409 + 业务码 4002**，从而阻断请求重放
（plan.md §11 F6：接口重放 1 秒 10 次仅首次成功）。

设计要点：
- **仅当请求带 `Idempotency-Key` 时生效**：不带该头的请求行为完全不变（既有客户端/测试零影响）。
- 去重键含**调用方身份指纹**（Authorization 头的 sha256 前缀），避免他人抢占/预占 key。
- 存储优先 Redis（`SET NX EX`，Redis 7 兼容，不用 `EXPIRE NX`）；Redis 不可用时降级为
  进程内字典（多实例部署下会降级，日志告警）——与 `core/rate_limit.py` 同套路。
- **失败即释放**：key 在进入路由前占用，但若本次响应以 4xx/5xx（含 422/4001/500）结束或
  下游抛异常，则立即释放该 key，使客户端可用**同一个 key** 安全重试；仅成功（<400）保持占用。
  这样「失败重试」不会被 409/4002 误拦，同时成功后的重放仍被拦截。
"""

import hashlib
import json
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.core.context import get_request_id
from app.core.logging import get_logger
from app.db.redis import get_redis
from app.schemas.common import ErrorCode, fail

logger = get_logger(__name__)

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_KEY_HEADER = b"idempotency-key"
_AUTH_HEADER = b"authorization"

# 进程内降级存储：key -> 过期时刻（monotonic）
_local_seen: dict[str, float] = {}


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers") or ():
        if k.lower() == name:
            return v.decode("latin-1")
    return None


def _identity_fingerprint(scope: Scope) -> str:
    auth = _header(scope, _AUTH_HEADER) or "-"
    return hashlib.sha256(auth.encode("latin-1")).hexdigest()[:16]


def _acquire_local(store_key: str, ttl: int) -> bool:
    """进程内兜底：True = 首次（放行），False = 重复（拦截）。"""
    now = time.monotonic()
    for k in [k for k, exp in _local_seen.items() if exp <= now]:
        _local_seen.pop(k, None)
    if store_key in _local_seen:
        return False
    _local_seen[store_key] = now + ttl
    return True


async def _send_conflict(send: Send) -> None:
    payload = fail(ErrorCode.DUPLICATE_REQUEST, request_id=get_request_id())
    body = json.dumps({**payload, "idempotency_replayed": True}, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 409,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class IdempotencyMiddleware:
    """纯 ASGI 中间件：不读请求体，只在进入路由前做一次性去重。"""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.prefix = settings.API_PREFIX
        self.ttl = max(1, int(settings.IDEMPOTENCY_TTL_SECONDS))
        self.enabled = settings.IDEMPOTENCY_ENABLED

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._should_check(scope):
            await self.app(scope, receive, send)
            return

        key_id = _header(scope, _KEY_HEADER)
        store_key = f"idem:{scope['path']}:{_identity_fingerprint(scope)}:{key_id}"
        if not await self._acquire(store_key):
            logger.info(
                "幂等拦截重复请求", extra={"path": scope["path"], "idempotency_key": key_id}
            )
            await _send_conflict(send)
            return

        # 记录下游最终响应状态码：失败（>=400）时释放 key，使同 key 可安全重试
        status_code: int | None = None

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # 异常路径同样释放占用，但异常必须继续向外传播（绝不吞掉）
            await self._release(store_key)
            raise

        if status_code is None or status_code >= 400:
            await self._release(store_key)

    def _should_check(self, scope: Scope) -> bool:
        return (
            self.enabled
            and scope["type"] == "http"
            and scope.get("method") in _WRITE_METHODS
            and str(scope.get("path", "")).startswith(self.prefix)
            and _header(scope, _KEY_HEADER) is not None
        )

    async def _acquire(self, store_key: str) -> bool:
        """True = 首次（放行）；False = 重复（拦截）。"""
        client = await get_redis()
        if client is not None:
            try:
                return bool(await client.set(store_key, "1", nx=True, ex=self.ttl))
            except Exception as exc:  # noqa: BLE001 - 命令不兼容/连接抖动一律降级
                logger.warning("幂等 Redis 存储不可用，降级进程内", extra={"reason": str(exc)})
        return _acquire_local(store_key, self.ttl)

    async def _release(self, store_key: str) -> None:
        """释放占用（首次请求失败/异常时调用），使客户端可用同一 key 重试。"""
        client = await get_redis()
        if client is not None:
            try:
                await client.delete(store_key)
            except Exception as exc:  # noqa: BLE001 - 释放失败不影响响应，降级为进程内清理
                logger.warning("幂等 Redis 释放失败", extra={"reason": str(exc)})
        _local_seen.pop(store_key, None)
