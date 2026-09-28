"""统一业务异常。

HTTP 状态码映射（contracts/openapi.yaml 头部约定）：
参数错 422(2001) / 未认证 401(1001) / 无权限 403(1002) / 资源不存在 404(3001) /
业务错 409(4001~7001) / 限流 429 / 服务错 500。
"""

from app.schemas.common import ErrorCode

_HTTP_STATUS_BY_CODE: dict[int, int] = {
    int(ErrorCode.UNAUTHORIZED): 401,
    int(ErrorCode.FORBIDDEN): 403,
    int(ErrorCode.VALIDATION_ERROR): 422,
    int(ErrorCode.NOT_FOUND): 404,
    int(ErrorCode.RATE_LIMITED): 429,
    int(ErrorCode.SERVER_ERROR): 500,
}


def http_status_for(code: int) -> int:
    """业务错误码 → HTTP 状态码；4001~7001 视为业务冲突（409）。"""
    if code in _HTTP_STATUS_BY_CODE:
        return _HTTP_STATUS_BY_CODE[code]
    if 4001 <= code <= 7001:
        return 409
    return 500


class AppException(Exception):
    """业务异常：路由/服务层 raise，由 main.py 的异常处理器转 envelope。"""

    def __init__(
        self,
        code: int,
        message: str | None = None,
        errors: dict | None = None,
    ) -> None:
        self.code = int(code)
        self.message = message or ErrorCode.message(self.code)
        self.errors = errors
        self.http_status = http_status_for(self.code)
        super().__init__(self.message)
