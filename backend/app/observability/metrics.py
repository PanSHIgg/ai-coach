"""Prometheus 指标定义与 `/metrics` 运维端点（Phase 5 / F9）。

真源：`docs/split/08-部署与运维.md` §10.7。

设计要点：
- `/metrics` 是**运维端点**，不挂 `/api` 契约前缀、不进 OpenAPI、不限流。
- 通过 `install_metrics(app)` 一次性装配：注册 `/metrics` 路由 + ASGI 计时/计数中间件。
- 指标口径：
  - QPS：`http_requests_total{method,path,status}`（`rate()` 即 QPS）；
  - 延迟：`http_request_duration_seconds`（Histogram，buckets 覆盖 P50/P95/P99 计算）；
  - 错误率：由 `http_requests_total` 按 `status` 维度计算（5xx 占比）；
  - 热量计算耗时：`calorie_calc_seconds`（Histogram）；
  - AI 调用成本：`ai_calls_total{task,degraded}`（次数）与
    `ai_cost_usd_total{task}`（= 次数 × 单价，供直接出成本曲线）。
- `path` 标签取**带 `API_PREFIX` 的完整路由模板**（如 `/api/account/today`、
  `/api/community/post/{id}`）而非原始 URL，避免高基数；未匹配到路由（404）时以
  请求 `scope['path']` 为准并把数字段归一为 `{id}`，同样补齐 `API_PREFIX`。

多进程（`uvicorn --workers N`，N>1）：
默认使用进程级 `REGISTRY`（含 process/platform 采集器）。多 worker 下各进程指标独立，
Prometheus 抓取到的只是被命中的那个 worker。需要全量聚合时，设置环境变量
`PROMETHEUS_MULTIPROC_DIR` 指向一个可写目录（启动前清空），`/metrics` 将改用
`MultiProcessCollector` 聚合（详见 `deploy/README.md`）。
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

# 运维端点路径（非 /api 契约前缀）
METRICS_PATH = "/metrics"

# ---- 指标定义（默认注册到进程级 REGISTRY）----

# QPS / 错误率：按方法、路由模板、状态码计数
http_requests_total = Counter(
    "http_requests_total",
    "HTTP 请求总数（按方法/路由模板/状态码）",
    labelnames=("method", "path", "status"),
)

# 延迟：Histogram，buckets 覆盖毫秒~10s，可算 P50/P95/P99
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求耗时（秒）",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# 热量账户计算耗时（纯函数，量级为亚毫秒~毫秒）
calorie_calc_seconds = Histogram(
    "calorie_calc_seconds",
    "热量账户计算耗时（秒）",
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

# AI 调用次数（task 例：chat/vision/recommend/weekly_comment；degraded：true=降级 FAQ）
ai_calls_total = Counter(
    "ai_calls_total",
    "AI 调用次数（按任务类型/是否降级）",
    labelnames=("task", "degraded"),
)

# AI 成本估算（美元）= 调用次数 × 单价；供 Grafana 直接绘制成本曲线与预算告警
ai_cost_usd_total = Counter(
    "ai_cost_usd_total",
    "AI 调用成本估算（美元）",
    labelnames=("task",),
)


def record_ai_call(task: str, *, degraded: bool = False, unit_cost_usd: float = 0.0) -> None:
    """记录一次 AI 调用：累加次数；给定单价时同步累加成本估算。

    :param task: 任务类型（如 chat / vision / recommend / weekly_comment）
    :param degraded: 是否降级命中（超时/异常回退预设 FAQ）
    :param unit_cost_usd: 单次调用成本（美元）；为 0 表示不计成本
    """
    ai_calls_total.labels(task=task, degraded="true" if degraded else "false").inc()
    if unit_cost_usd:
        ai_cost_usd_total.labels(task=task).inc(unit_cost_usd)


def observe_calorie_calc(seconds: float) -> None:
    """记录一次热量计算耗时（秒）。"""
    calorie_calc_seconds.observe(seconds)


@contextmanager
def track_calorie_calc() -> Iterator[None]:
    """上下文管理器：`with track_calorie_calc(): ...` 自动记录耗时。"""
    start = time.perf_counter()
    try:
        yield
    finally:
        calorie_calc_seconds.observe(time.perf_counter() - start)


# ---- 路由模板归一（控制 path 标签基数）----

_DIGITS = re.compile(r"/\d+")

# 不在 /api 下的运维端点：标签保持原样，避免出现 "/api/healthz" 这类不存在的路径
_OPS_PATHS = frozenset({"/healthz"})


def _route_path(scope: dict) -> str:
    """优先取 Starlette 路由模板；未匹配（404）时把数字段归一为 `{id}`。

    统一补齐 `API_PREFIX`：已挂载的业务路由模板为相对路径（如 `/auth/me`，不含 `/api`），
    而 404 的 `scope['path']` 已是完整请求路径（含 `/api`）；两种来源都归一为带前缀口径。
    `_OPS_PATHS` 中的运维端点例外，保持原样。
    """
    template = getattr(scope.get("route"), "path", None)
    path = template or _DIGITS.sub("/{id}", scope.get("path") or "unknown")
    if path in _OPS_PATHS:
        return path
    prefix = get_settings().API_PREFIX
    return path if path.startswith(prefix) else f"{prefix}{path}"


def _registry() -> CollectorRegistry:
    """多进程聚合（设置了 PROMETHEUS_MULTIPROC_DIR）时返回聚合注册表。"""
    if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client.multiprocess import MultiProcessCollector

        registry = CollectorRegistry()
        MultiProcessCollector(registry)
        return registry
    return REGISTRY


async def metrics_endpoint(request: Request) -> Response:  # noqa: ARG001 - ASGI 端点固定签名
    """暴露 Prometheus 文本格式指标。"""
    return Response(generate_latest(_registry()), media_type=CONTENT_TYPE_LATEST)


class MetricsMiddleware:
    """ASGI 中间件：对非 `/metrics` 的 HTTP 请求计时并计数（QPS/延迟/错误率）。"""

    def __init__(self, app) -> None:  # noqa: ANN001 - ASGI app 无稳定类型
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001 - ASGI 接口
        if scope["type"] != "http" or scope.get("path") == METRICS_PATH:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        start = time.perf_counter()
        status_code = 500  # 若响应未正常开始（异常）按 500 计

        async def send_wrapper(message) -> None:  # noqa: ANN001 - ASGI message
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            path = _route_path(scope)
            http_requests_total.labels(method=method, path=path, status=str(status_code)).inc()
            http_request_duration_seconds.labels(method=method, path=path).observe(elapsed)


def install_metrics(app: FastAPI) -> None:
    """一次性装配可观测性：注册 `/metrics` 路由 + 请求计时/计数中间件。

    在 `create_app()` 内、业务路由挂载后调用（见 main.py 装配两行）。
    """
    app.add_middleware(MetricsMiddleware)
    app.add_route(METRICS_PATH, metrics_endpoint, include_in_schema=False)
