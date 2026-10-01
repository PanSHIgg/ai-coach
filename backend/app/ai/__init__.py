"""AI 客户端抽象层（D-09 收敛后）。

厂商适配器已删除：LLM 与 VLM 统一走 OpenAI 兼容协议（/v1/chat/completions），
客户端装配在 `app/services/ai_service.py`（`llm_client_for`）与
`app/services/recognize_service.py`（`vision_client_for`），连接与模型信息
使用时由 env 设置（LLM_*/VLM_* 三件套）。本包只保留协议抽象、Mock 降级与提示词常量。
"""

from .base import LLMClient, VisionClient
from .mock import MockLLMClient, MockVisionClient

__all__ = [
    "LLMClient",
    "VisionClient",
    "MockLLMClient",
    "MockVisionClient",
]
