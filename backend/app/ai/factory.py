"""AI 客户端工厂：按配置选真实客户端，缺 Key / 测试环境自动落 Mock。

- 有 `MS_API_KEY` → ModelScope Qwen3.8-Flash-Next（对话 + 视觉同一 VLM，ai_api.md）
- 否则 → 本地 Mock（app/ai/mock.py，零网络依赖，永远可用）

上层（service）只依赖 `LLMClient` / `VisionClient` 抽象（app/ai/base.py）。
"""

from __future__ import annotations

import logging

from app.core.config import Settings

from .base import LLMClient, VisionClient
from .mock import MockLLMClient, MockVisionClient
from .modelscope import ModelScopeLLMClient, ModelScopeVisionClient

logger = logging.getLogger("app.ai")


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
    # 配置错误可发现：若已配置 AI_LLM_API_KEY 但 factory 不读取该字段，打警告
    if hasattr(settings, 'AI_LLM_API_KEY') and settings.AI_LLM_API_KEY:
        logger.warning(
            "[ai] 已配置 AI_LLM_API_KEY 但 factory 不读取该字段，"
            "生产环境请使用 MS_API_KEY 配置 ModelScope Qwen"
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
    # 配置错误可发现
    if hasattr(settings, 'AI_VISION_API_KEY') and settings.AI_VISION_API_KEY:
        logger.warning(
            "[ai] 已配置 AI_VISION_API_KEY 但 factory 不读取该字段，"
            "生产环境请使用 MS_API_KEY 配置 ModelScope Qwen（VLM 统一对话+视觉）"
        )
    return MockVisionClient()
