"""AI 客户端工厂：按 provider 配置选真实客户端，缺 Key / 未知 provider 自动落 Mock。

选型真源：主文档 §6.1 AI 行「视觉识别：腾讯云/阿里云图像识别（食物类目）+
DeepSeek / 通义千问 API（对话+RAG）」。provider → 适配器映射：

- 对话 `AI_LLM_PROVIDER`：
  deepseek  → DeepSeekClient      qwen       → QwenClient
  modelscope→ ModelScopeLLMClient mock       → MockLLMClient
- 视觉 `AI_VISION_PROVIDER`：
  tencent   → TencentVisionClient aliyun     → AliyunVisionClient
  modelscope→ ModelScopeVisionClient          mock → MockVisionClient

回落规则（沿用既有「无 Key 落 mock」机制，不卡死，06 文档 §六）：provider 未知 /
为 mock / 缺对应 Key → Mock；为兼容既有部署（仅有 `MS_API_KEY`），所选 provider 缺 Key
但 `MS_API_KEY` 存在时退回 ModelScope。

上层（service）只依赖 `LLMClient` / `VisionClient` 抽象（app/ai/base.py）。
"""

from __future__ import annotations

import logging

from app.core.config import Settings

from .aliyun_vision import AliyunVisionClient
from .base import LLMClient, VisionClient
from .deepseek import DeepSeekClient
from .mock import MockLLMClient, MockVisionClient
from .modelscope import ModelScopeLLMClient, ModelScopeVisionClient
from .qwen import QwenClient
from .tencent_vision import TencentVisionClient

logger = logging.getLogger("app.ai")

# 默认按文档选型（主文档 §6.1）：对话 DeepSeek、视觉腾讯云
DEFAULT_CHAT_PROVIDER = "deepseek"
DEFAULT_VISION_PROVIDER = "tencent"
# 文档指定 + 该项目既有 provider 全集（mock 为无 Key 兜底）
CHAT_PROVIDERS = frozenset({"deepseek", "qwen", "modelscope", "mock"})
VISION_PROVIDERS = frozenset({"tencent", "aliyun", "modelscope", "mock"})


def _provider(settings: Settings, field: str, default: str) -> str:
    return (getattr(settings, field, "") or default).strip().lower()


def _chat_key(settings: Settings) -> str:
    # 共享 AI_API_KEY 兜底；provider 专属 Key 优先
    return (settings.AI_LLM_API_KEY or settings.AI_API_KEY or "").strip()


def _vision_key(settings: Settings) -> str:
    return (settings.AI_VISION_API_KEY or settings.AI_API_KEY or "").strip()


def _modelscope_llm(settings: Settings) -> ModelScopeLLMClient:
    return ModelScopeLLMClient(
        api_key=settings.MS_API_KEY,
        base_url=settings.MS_BASE_URL,
        model=settings.MS_MODEL,
        timeout=settings.MS_TIMEOUT,
        max_tokens=settings.MS_MAX_TOKENS,
        enable_thinking=settings.MS_ENABLE_THINKING,
    )


def _modelscope_vision(settings: Settings) -> ModelScopeVisionClient:
    return ModelScopeVisionClient(
        api_key=settings.MS_API_KEY,
        base_url=settings.MS_BASE_URL,
        model=settings.MS_MODEL,
        timeout=settings.MS_TIMEOUT,
        enable_thinking=settings.MS_ENABLE_THINKING,
    )


def _fallback_llm(settings: Settings, provider: str) -> LLMClient:
    """所选 provider 缺 Key：有 `MS_API_KEY` 退回 ModelScope（向后兼容），否则 Mock。"""
    if settings.MS_API_KEY:
        logger.warning("[ai] AI_LLM_PROVIDER=%s 缺 Key，退回 ModelScope（兼容）", provider)
        return _modelscope_llm(settings)
    logger.warning("[ai] AI_LLM_PROVIDER=%s 缺 Key，回落 Mock", provider)
    return MockLLMClient()


def _fallback_vision(settings: Settings, provider: str) -> VisionClient:
    if settings.MS_API_KEY:
        logger.warning("[ai] AI_VISION_PROVIDER=%s 缺 Key，退回 ModelScope（兼容）", provider)
        return _modelscope_vision(settings)
    logger.warning("[ai] AI_VISION_PROVIDER=%s 缺 Key，回落 Mock", provider)
    return MockVisionClient()


def get_llm_client(settings: Settings) -> LLMClient:
    provider = _provider(settings, "AI_LLM_PROVIDER", DEFAULT_CHAT_PROVIDER)
    base_url = settings.AI_LLM_BASE_URL or settings.AI_BASE_URL or None
    model = settings.AI_LLM_MODEL or None
    if provider == "deepseek":
        if key := _chat_key(settings):
            return DeepSeekClient(api_key=key, base_url=base_url, model=model)
        return _fallback_llm(settings, provider)
    if provider == "qwen":
        if key := _chat_key(settings):
            return QwenClient(api_key=key, base_url=base_url, model=model)
        return _fallback_llm(settings, provider)
    if provider == "modelscope":
        if settings.MS_API_KEY:
            return _modelscope_llm(settings)
        return MockLLMClient()
    if provider != "mock":
        logger.warning("[ai] 未知 AI_LLM_PROVIDER=%s，回落 Mock", provider)
    return MockLLMClient()


def get_vision_client(settings: Settings) -> VisionClient:
    provider = _provider(settings, "AI_VISION_PROVIDER", DEFAULT_VISION_PROVIDER)
    base_url = settings.AI_VISION_BASE_URL or settings.AI_BASE_URL or None
    if provider in ("tencent", "aliyun"):
        key = _vision_key(settings)
        if key:
            client_cls = TencentVisionClient if provider == "tencent" else AliyunVisionClient
            try:
                return client_cls(api_key=key, base_url=base_url)
            except ValueError as exc:  # Key 格式非法 → 回落，不阻断记录流程
                logger.warning("[ai] AI_VISION_PROVIDER=%s Key 格式非法(%s)，回落", provider, exc)
                return _fallback_vision(settings, provider)
        return _fallback_vision(settings, provider)
    if provider == "modelscope":
        if settings.MS_API_KEY:
            return _modelscope_vision(settings)
        return MockVisionClient()
    if provider != "mock":
        logger.warning("[ai] 未知 AI_VISION_PROVIDER=%s，回落 Mock", provider)
    return MockVisionClient()
