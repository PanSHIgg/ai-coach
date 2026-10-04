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
  - AI 调用：`ai_calls_total{task,degraded}`（次数）、
    `ai_tokens_total{task,type}`（type=input/output/cached，cached 是 input 的子集）、
    `ai_cost_usd_total{task}`（= token × 牌价，供直接出成本曲线）。
    只统计**真实厂商调用**：无 Key 的 Mock/模板降级不发 HTTP，因此不计入（口径是"花钱的调用"）。
    `task` 由调用方用 `ai_task()` 声明（chat / weekly_comment / recommend / vision），
    经 contextvar 穿过 `asyncio.to_thread` 到达 HTTP 出口。
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
from contextvars import ContextVar
from typing import TYPE_CHECKING, NamedTuple

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

# AI 调用次数（task 例：chat/vision/recommend/weekly_comment；
# degraded=true 表示厂商侧请求失败、上层降级 FAQ）
ai_calls_total = Counter(
    "ai_calls_total",
    "AI 调用次数（按任务/是否降级）",
    labelnames=("task", "degraded"),
)

# token 用量：input/output 为厂商 usage 原值，cached 为其中命中前缀缓存的部分
ai_tokens_total = Counter(
    "ai_tokens_total",
    "AI 调用 token 用量（按任务/类型，type=input|output|cached）",
    labelnames=("task", "type"),
)

# AI 成本估算（美元）= Σ(token × 牌价)；供 Grafana 直接出成本曲线与预算告警
ai_cost_usd_total = Counter(
    "ai_cost_usd_total",
    "AI 调用成本估算（美元）",
    labelnames=("task",),
)


class TokenUsage(NamedTuple):
    """一次厂商返回的 token 用量（OpenAI 兼容 `usage`）；缺字段一律按 0。"""

    input: int = 0
    output: int = 0
    cached: int = 0


def token_usage_from_response(data: dict) -> TokenUsage:
    """OpenAI 兼容响应体 → TokenUsage；端点不回传 `usage` 或字段缺失一律按 0。

    前缀缓存命中数在 OpenAI 兼容端点（DeepSeek / 百炼 / Moonshot / vLLM）统一落在
    `prompt_tokens_details.cached_tokens`，它是 `prompt_tokens` 的子集而非额外量。
    放在这里而不是 ai_service：两个厂商出口（单轮 `_openai_compatible_chat` 与工具循环
    `tools._openai_chat_with_tools`）都要用，而 tools 反向 import ai_service 会成环。
    """
    usage = data.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return TokenUsage(
        input=int(usage.get("prompt_tokens") or 0),
        output=int(usage.get("completion_tokens") or 0),
        cached=int(details.get("cached_tokens") or 0),
    )


# 当前 AI 任务标签：HTTP 出口在客户端线程里读它，客户端本身无需感知调用方是谁
_AI_TASK: ContextVar[str] = ContextVar("ai_task", default="chat")


@contextmanager
def ai_task(name: str) -> Iterator[None]:
    """声明作用域内的 AI 调用属于哪个任务（`with ai_task("recommend"):`）。"""
    token = _AI_TASK.set(name)
    try:
        yield
    finally:
        _AI_TASK.reset(token)


def current_ai_task() -> str:
    return _AI_TASK.get()


def record_ai_call(
    task: str, *, degraded: bool = False, usage: TokenUsage | None = None
) -> None:
    """记录一次真实厂商调用：次数 → token 用量 → 按牌价折算的成本估算。

    成本 = [（input − cached）× `AI_PRICE_INPUT_USD_PER_MTOKEN`
    + cached × `AI_PRICE_CACHED_INPUT_USD_PER_MTOKEN`
    + output × `AI_PRICE_OUTPUT_USD_PER_MTOKEN`] / 1e6。
    牌价为 0 时仍 `.inc(0)`：让序列存在，看板画出 0 线而不是 No data。
    """
    ai_calls_total.labels(task=task, degraded="true" if degraded else "false").inc()
    if usage is None:
        return
    ai_tokens_total.labels(task=task, type="input").inc(usage.input)
    ai_tokens_total.labels(task=task, type="output").inc(usage.output)
    ai_tokens_total.labels(task=task, type="cached").inc(usage.cached)
    s = get_settings()
    cost = (
        (usage.input - usage.cached) * s.AI_PRICE_INPUT_USD_PER_MTOKEN
        + usage.cached * s.AI_PRICE_CACHED_INPUT_USD_PER_MTOKEN
        + usage.output * s.AI_PRICE_OUTPUT_USD_PER_MTOKEN
    ) / 1_000_000
    ai_cost_usd_total.labels(task=task).inc(cost)


# AI 计数器的标签集有限且固定，启动时先把子序列预置为 0。
# 为什么必须预置：Prometheus 把「序列首次出现」当基线，首次抓取前发生的增量永远算不出来。
# 本机实测踩过：一次提问的工具循环在同一个 15s 抓取间隙里连调 3 次，
# `/metrics` 上 ai_calls_total 直接是 3，而 `increase(ai_calls_total[1h])` 恒为 0。
AI_TASKS = ("chat", "weekly_comment", "recommend", "vision")
AI_TOKEN_TYPES = ("input", "output", "cached")


def prime_ai_counters() -> None:
    """把 AI 相关计数器的全部子序列建成 0（幂等；`install_metrics` 装配时调用）。"""
    for task in AI_TASKS:
        ai_calls_total.labels(task=task, degraded="false").inc(0)
        ai_calls_total.labels(task=task, degraded="true").inc(0)
        ai_cost_usd_total.labels(task=task).inc(0)
        for token_type in AI_TOKEN_TYPES:
            ai_tokens_total.labels(task=task, type=token_type).inc(0)


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
    每个 uvicorn worker 各调一次，`prime_ai_counters()` 幂等，多进程下各自建自己的子文件。
    """
    prime_ai_counters()
    app.add_middleware(MetricsMiddleware)
    app.add_route(METRICS_PATH, metrics_endpoint, include_in_schema=False)
