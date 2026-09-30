"""向后兼容 shim：DeepSeek / 通义千问对话客户端已拆分至 `deepseek.py` / `qwen.py`。

保留本模块仅为不破坏既有导入路径（`from app.ai.llm import DeepSeekClient`）。
"""

from .deepseek import DeepSeekClient
from .qwen import QwenClient

__all__ = ["DeepSeekClient", "QwenClient"]
