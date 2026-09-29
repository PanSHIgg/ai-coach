"""应用入口：create_app 工厂（P0-e）。

中间件顺序（外→内）：Metrics → CORS → RequestId → RateLimit → Idempotency → 路由。
运维端点：/healthz（存活）、/metrics（Prometheus 指标，Phase 5 F9）。
异常处理：AppException → envelope（业务码映射 HTTP 状态）；
RequestValidationError → 422/2001；HTTPException → 映射业务码；兜底 → 500。
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.context import get_request_id
from app.core.errors import AppException
from app.core.idempotency import IdempotencyMiddleware
from app.core.logging import get_logger, setup_logging
from app.core.rate_limit import RateLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.observability.metrics import install_metrics
from app.schemas.common import ErrorCode, fail

logger = get_logger(__name__)

_HTTP_CODE_MAP = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
}


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()

    # IS-001: 生产环境禁止启用 PAY_MOCK_MODE
    if s.ENV == "prod" and s.PAY_MOCK_MODE:
        raise RuntimeError(
            "生产环境禁止启用 PAY_MOCK_MODE=True。"
            "请在 .env 中设置 PAY_MOCK_MODE=false 或设置 ENV=dev/sandbox"
        )

    setup_logging(s.LOG_LEVEL)
    app = FastAPI(title=s.APP_NAME, version="0.1.0", debug=s.DEBUG)

    # ---- 异常处理 ----

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=fail(exc.code, exc.message, errors=exc.errors, request_id=get_request_id()),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=fail(
                ErrorCode.VALIDATION_ERROR,
                errors={"detail": errors},
                request_id=get_request_id(),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _HTTP_CODE_MAP.get(exc.status_code)
        message = None
        if code is None:
            # 未映射的 HTTP 状态需给出明确文案而非"未知错误"
            code = exc.status_code
            message = "请求方法或资源不支持"
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(code, message, request_id=get_request_id()),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常", extra={"path": request.url.path})
        return JSONResponse(
            status_code=500,
            content=fail(ErrorCode.SERVER_ERROR, request_id=get_request_id()),
        )

    # ---- 中间件（add 顺序 = 内→外；执行顺序相反（外→内）：Metrics → CORS →
    # RequestId → RateLimit → Idempotency）----
    # 注：MetricsMiddleware 由 install_metrics() 最后 add → 最外层（最先执行、最后收尾计时）。
    app.add_middleware(IdempotencyMiddleware, settings=s)
    app.add_middleware(RateLimitMiddleware, settings=s)
    app.add_middleware(RequestIdMiddleware)
    origins = [o.strip() for o in s.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- 运维端点（无前缀、不限流、无 envelope）----
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok"}

    # ---- 业务路由（/api 前缀 → openapi.yaml 全部接口）----
    app.include_router(api_router, prefix=s.API_PREFIX)

    # ---- 可观测性（Phase 5 F9）：/metrics + 请求计数/延迟中间件 ----
    install_metrics(app)
    return app


app = create_app()
