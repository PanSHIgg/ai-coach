"""请求级上下文（contextvars），供日志与响应 envelope 注入 request_id。"""

from contextvars import ContextVar

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """获取当前请求的 request_id（无请求上下文时为 None）。"""
    return request_id_ctx.get()
