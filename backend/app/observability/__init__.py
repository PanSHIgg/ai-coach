"""可观测性（Phase 5 / F9）：Prometheus 指标与 `/metrics` 运维端点。

对外入口：`install_metrics(app)` 一次性装配（注册路由 + 请求计时/计数中间件）。
业务侧埋点辅助：`record_ai_call`、`observe_calorie_calc`、`track_calorie_calc`。
"""

from app.observability.metrics import (
    METRICS_PATH,
    ai_calls_total,
    ai_cost_usd_total,
    calorie_calc_seconds,
    http_request_duration_seconds,
    http_requests_total,
    install_metrics,
    observe_calorie_calc,
    record_ai_call,
    track_calorie_calc,
)

__all__ = [
    "METRICS_PATH",
    "ai_calls_total",
    "ai_cost_usd_total",
    "calorie_calc_seconds",
    "http_request_duration_seconds",
    "http_requests_total",
    "install_metrics",
    "observe_calorie_calc",
    "record_ai_call",
    "track_calorie_calc",
]
