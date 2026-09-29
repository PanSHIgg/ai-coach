"""AI 客户端工厂：按配置选真实客户端，缺 Key / 测试环境自动落 Mock。

- 有 `MS_API_KEY` → ModelScope Qwen3.8-Flash-Next（对话 + 视觉同一 VLM，ai_api.md）
- 否则 → 本地 Mock（app/ai/mock.py，零网络依赖，永远可用）

上层（service）只依赖 `LLMClient` / `VisionClient` 抽象（app/ai/base.py）。
"""

from __future__ import annotations

from app.core.config import Settings

from .base import LLMClient, VisionClient
from .mock import MockLLMClient, MockVisionClient
from .modelscope import ModelScopeLLMClient, ModelScopeVisionClient


def _use_modelscope(settings: Settings) -> bool:
    return bool(settings.MS_API_KEY)


def get_llm_client(settings: Settings) -> LLMClient:
    if _use_modelscope(settings):
        return ModelScopeLLMClient(
            api_key=settings.MS_API_KEY,
            base_url=settings.MS_BASE_URL,
            model=settings.MS_MODEL,
            timeout=settings.MS_TIMEOUT,
            max_tokens=settings.MS_MAX_TOKENS,
            enable_thinking=settings.MS_ENABLE_THINKING,
        )
    return MockLLMClient()


def get_vision_client(settings: Settings) -> VisionClient:
    if _use_modelscope(settings):
        return ModelScopeVisionClient(
            api_key=settings.MS_API_KEY,
            base_url=settings.MS_BASE_URL,
            model=settings.MS_MODEL,
            timeout=settings.MS_TIMEOUT,
            enable_thinking=settings.MS_ENABLE_THINKING,
        )
    return MockVisionClient()
