"""AI Provider SDK 抽象层（P0-h spike）。

用法：
    from app.ai import get_llm_client, get_vision_client

配置读取 .env.example 的 AI_* 命名；provider 未知或无 Key 一律回落 mock 并打日志。
选型结论与切换另一家的改动点见 docs/ai-provider-spike.md、本包 README.md。
"""

import logging
import os

from .base import LLMClient, VisionClient
from .mock import MockLLMClient, MockVisionClient

logger = logging.getLogger("app.ai")

__all__ = [
    "LLMClient",
    "VisionClient",
    "MockLLMClient",
    "MockVisionClient",
    "get_llm_client",
    "get_vision_client",
]


def get_llm_client() -> LLMClient:
    """按 AI_LLM_PROVIDER 构建对话客户端；无 Key / 未知 provider / 依赖缺失均落 mock。"""
    provider = os.getenv("AI_LLM_PROVIDER", "deepseek").strip().lower()
    api_key = (os.getenv("AI_LLM_API_KEY") or os.getenv("AI_API_KEY") or "").strip()
    base_url = (os.getenv("AI_LLM_BASE_URL") or os.getenv("AI_BASE_URL") or "").strip() or None
    model = (os.getenv("AI_LLM_MODEL") or "").strip() or None

    if not api_key:
        logger.warning("[ai] LLM Key 未配置（AI_LLM_API_KEY/AI_API_KEY），回落 MockLLMClient")
        return MockLLMClient()

    try:
        if provider == "deepseek":
            from .llm import DeepSeekClient

            return DeepSeekClient(api_key=api_key, base_url=base_url, model=model)
        if provider == "qwen":
            from .llm import QwenClient

            return QwenClient(api_key=api_key, base_url=base_url, model=model)
    except (ImportError, ValueError) as exc:
        logger.warning("[ai] LLM provider=%s 初始化失败(%s)，回落 MockLLMClient", provider, exc)
        return MockLLMClient()

    logger.warning("[ai] 未知 AI_LLM_PROVIDER=%s，回落 MockLLMClient", provider)
    return MockLLMClient()


def get_vision_client() -> VisionClient:
    """按 AI_VISION_PROVIDER 构建视觉客户端；无 Key / 未知 provider / 依赖缺失均落 mock。"""
    provider = os.getenv("AI_VISION_PROVIDER", "tencent").strip().lower()
    api_key = (os.getenv("AI_VISION_API_KEY") or os.getenv("AI_API_KEY") or "").strip()
    base_url = (os.getenv("AI_VISION_BASE_URL") or os.getenv("AI_BASE_URL") or "").strip() or None

    if not api_key:
        logger.warning("[ai] Vision Key 未配置（AI_VISION_API_KEY/AI_API_KEY），回落 MockVisionClient")
        return MockVisionClient()

    if provider == "tencent":
        try:
            from .vision import TencentVisionClient

            return TencentVisionClient(api_key=api_key, base_url=base_url)
        except (ImportError, ValueError) as exc:
            logger.warning("[ai] Vision provider=tencent 初始化失败(%s)，回落 MockVisionClient", exc)
    else:
        logger.warning(
            "[ai] 视觉 provider=%s spike 未实现（切换点见 docs/ai-provider-spike.md），回落 MockVisionClient",
            provider,
        )
    return MockVisionClient()
