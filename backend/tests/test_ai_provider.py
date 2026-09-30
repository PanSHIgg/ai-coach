"""AI provider 路由测试（F3）：只测本项目行为，不测第三方 SDK、不联网。

覆盖：① 各 provider 无 Key → 回落 mock；② factory 按配置选到预期适配器类；
③ 文档指定 provider 名称（deepseek/qwen/tencent/aliyun）均可被识别。
同类边界用 parametrize 合并（AGENTS §2.9，一个行为一个测试）。
"""

import pytest

from app.ai.aliyun_vision import AliyunVisionClient
from app.ai.deepseek import DeepSeekClient
from app.ai.factory import get_llm_client, get_vision_client
from app.ai.mock import MockLLMClient, MockVisionClient
from app.ai.modelscope import ModelScopeLLMClient, ModelScopeVisionClient
from app.ai.qwen import QwenClient
from app.ai.tencent_vision import TencentVisionClient
from tests.conftest import make_settings

# 显式清空所有 Key，避免本机环境变量干扰「无 Key」判定
_NO_KEYS = {"AI_API_KEY": "", "AI_LLM_API_KEY": "", "AI_VISION_API_KEY": "", "MS_API_KEY": ""}


def _settings(**overrides):
    return make_settings(**{**_NO_KEYS, **overrides})


# ---------------------------------------------------------------------------
# ② provider → 适配器映射（含共享 AI_API_KEY 兜底）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "keys", "expected"),
    [
        ("deepseek", {"AI_LLM_API_KEY": "k"}, DeepSeekClient),
        ("qwen", {"AI_LLM_API_KEY": "k"}, QwenClient),
        ("deepseek", {"AI_API_KEY": "shared"}, DeepSeekClient),  # 共享 Key 兜底
        ("modelscope", {"MS_API_KEY": "k"}, ModelScopeLLMClient),
        ("mock", {}, MockLLMClient),
    ],
    ids=["deepseek", "qwen", "shared_key", "modelscope", "mock"],
)
def test_chat_provider_routing(provider, keys, expected):
    assert isinstance(get_llm_client(_settings(AI_LLM_PROVIDER=provider, **keys)), expected)


@pytest.mark.parametrize(
    ("provider", "keys", "expected"),
    [
        ("tencent", {"AI_VISION_API_KEY": "id:secret"}, TencentVisionClient),
        ("aliyun", {"AI_VISION_API_KEY": "id:secret"}, AliyunVisionClient),
        ("tencent", {"AI_API_KEY": "id:secret"}, TencentVisionClient),  # 共享 Key 兜底
        ("modelscope", {"MS_API_KEY": "k"}, ModelScopeVisionClient),
        ("mock", {}, MockVisionClient),
    ],
    ids=["tencent", "aliyun", "shared_key", "modelscope", "mock"],
)
def test_vision_provider_routing(provider, keys, expected):
    assert isinstance(get_vision_client(_settings(AI_VISION_PROVIDER=provider, **keys)), expected)


# ---------------------------------------------------------------------------
# ① 无 Key → 回落 mock（含未知 provider）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider", ["deepseek", "qwen", "modelscope", "mock", "unknown-xyz"]
)
def test_chat_without_key_falls_back_to_mock(provider):
    assert isinstance(get_llm_client(_settings(AI_LLM_PROVIDER=provider)), MockLLMClient)


@pytest.mark.parametrize(
    "provider", ["tencent", "aliyun", "modelscope", "mock", "unknown-xyz"]
)
def test_vision_without_key_falls_back_to_mock(provider):
    assert isinstance(get_vision_client(_settings(AI_VISION_PROVIDER=provider)), MockVisionClient)


@pytest.mark.parametrize("provider", ["tencent", "aliyun"])
def test_vision_malformed_key_falls_back_to_mock(provider):
    """Key 存在但非 '{Id}:{Secret}' 格式 → 回落 mock，不抛异常阻断记录流程。"""
    settings = _settings(AI_VISION_PROVIDER=provider, AI_VISION_API_KEY="no-colon")
    assert isinstance(get_vision_client(settings), MockVisionClient)
