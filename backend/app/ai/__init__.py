"""AI Provider SDK 抽象层（P0-h spike）。

【已废弃】双工厂已消除，生产唯一入口是 app.ai.factory（传 Settings）。
本文件仅保留向后兼容的导入，实际工厂函数已删除。
"""

from .base import LLMClient, VisionClient
from .mock import MockLLMClient, MockVisionClient

__all__ = [
    "LLMClient",
    "VisionClient",
    "MockLLMClient",
    "MockVisionClient",
]
