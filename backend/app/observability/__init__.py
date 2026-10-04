"""可观测性（Phase 5 / F9）：Prometheus 指标与 `/metrics` 运维端点。

对外入口：`install_metrics(app)` 一次性装配（注册路由 + 请求计时/计数中间件）。
业务侧埋点辅助：`record_ai_call`（厂商出口自动调用）、`ai_task`（声明任务标签）、
`observe_calorie_calc` / `track_calorie_calc`（热量引擎耗时）。
"""

from app.observability.metrics import (
    METRICS_PATH,
    TokenUsage,
    ai_calls_total,
    ai_cost_usd_total,
    ai_task,
    ai_tokens_total,
    calorie_calc_seconds,
    current_ai_task,
    http_request_duration_seconds,
    http_requests_total,
    install_metrics,
    observe_calorie_calc,
    prime_ai_counters,
    record_ai_call,
    track_calorie_calc,
)

__all__ = [
    "METRICS_PATH",
    "TokenUsage",
    "ai_calls_total",
    "ai_cost_usd_total",
    "ai_task",
    "ai_tokens_total",
    "calorie_calc_seconds",
    "current_ai_task",
    "http_request_duration_seconds",
    "http_requests_total",
    "install_metrics",
    "observe_calorie_calc",
    "prime_ai_counters",
    "record_ai_call",
    "track_calorie_calc",
]
