"""JSON 结构化日志。

- 统一 JSON 输出：ts/level/logger/message + request_id/method/path/status/duration_ms 等 extra
- request_id 来自 core.context 的 contextvar（由 RequestIdMiddleware 注入）
- 不打密码、token、手机号原文（10 文档 §13.4）
"""

import json
import logging
import logging.config
from datetime import datetime, timezone

from .context import request_id_ctx

# LogRecord 标准属性（format 时跳过，只保留业务 extra）
_RESERVED_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """把 LogRecord（含 extra）序列化为单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_ctx.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    """dictConfig 装配 root logger；重复调用安全（测试/多入口）。"""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"level": level.upper(), "handlers": ["console"]},
            "loggers": {
                # uvicorn access 与自定义 access 日志重复，静默
                "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": False},
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
