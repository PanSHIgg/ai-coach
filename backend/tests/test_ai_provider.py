"""AI 客户端装配与 OpenAI 兼容协议测试（D-09）：只测本项目行为，不联网。

覆盖：① LLM_*/VLM_* 未配置 → 降级 Mock；② 配置齐备 → OpenAI 兼容客户端（三件套透传）；
③ `_openai_compatible_chat` 标准请求/响应结构（mock httpx.Client.post）；
④ vision 消息格式（base64 data URL 与 https URL）。同类边界用 parametrize 合并（AGENTS §2.9）。
"""

import base64
import json

import httpx
import pytest

from app.ai.mock import MockLLMClient, MockVisionClient
from app.services import ai_service, recognize_service
from tests.conftest import make_settings


def _settings(**overrides):
    # 显式清空 AI 连接信息，避免本机环境变量干扰「未配置」判定
    defaults = {
        "LLM_BASE_URL": "",
        "LLM_API_KEY": "",
        "LLM_MODEL": "",
        "VLM_BASE_URL": "",
        "VLM_API_KEY": "",
        "VLM_MODEL": "",
    }
    return make_settings(**{**defaults, **overrides})


# ① 未配置 → 降级 Mock（明确降级，不崩）


def test_llm_unconfigured_falls_back_to_mock():
    assert isinstance(ai_service.llm_client_for(_settings()), MockLLMClient)


@pytest.mark.parametrize("overrides", [{}, {"VLM_BASE_URL": "http://x/v1"}, {"VLM_API_KEY": "k"}])
def test_vision_unconfigured_falls_back_to_mock(overrides):
    assert isinstance(recognize_service.vision_client_for(_settings(**overrides)), MockVisionClient)


# ② 配置齐备 → OpenAI 兼容客户端（三件套透传）


def test_llm_configured_returns_openai_compat_client():
    client = ai_service.llm_client_for(
        _settings(LLM_BASE_URL="http://llm.test/v1", LLM_API_KEY="k", LLM_MODEL="m-1")
    )
    assert isinstance(client, ai_service._OpenAICompatLLM)
    assert (client.base_url, client.api_key, client.model) == ("http://llm.test/v1", "k", "m-1")


def test_vision_configured_returns_openai_compat_client():
    client = recognize_service.vision_client_for(
        _settings(VLM_BASE_URL="http://vlm.test/v1", VLM_API_KEY="k", VLM_MODEL="v-1")
    )
    assert isinstance(client, ai_service._OpenAICompatVLM)
    assert (client.base_url, client.api_key, client.model) == ("http://vlm.test/v1", "k", "v-1")


# ③ OpenAI 兼容请求/响应结构（POST {base_url}/chat/completions → choices[0].message.content）


def _patch_post(monkeypatch, reply: str) -> list[dict]:
    """mock 同步 httpx.Client.post 并记录请求；只 patch 同步 Client，不影响 db_client（AsyncClient）。"""
    calls: list[dict] = []

    def fake_post(self, url, *, headers=None, json=None, **kwargs):
        calls.append({"url": url, "headers": headers, "json": json})
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": reply}}]},
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    return calls


def test_openai_compatible_chat_request_and_response(monkeypatch):
    calls = _patch_post(monkeypatch, "  你好，先喝水。 ")
    messages = [{"role": "user", "content": "饿了"}]
    text = ai_service._openai_compatible_chat(
        "http://llm.test/v1", "secret-key", "deepseek-chat", messages, timeout=5.0
    )
    assert text == "你好，先喝水。"  # 取 choices[0].message.content 并 strip
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "http://llm.test/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer secret-key"
    assert call["json"]["model"] == "deepseek-chat"
    assert call["json"]["messages"] == messages
    assert {"temperature", "max_tokens"} <= set(call["json"])


def test_openai_compatible_chat_raises_on_http_error(monkeypatch):
    def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(500, json={"error": "boom"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(httpx.HTTPStatusError):
        ai_service._openai_compatible_chat(
            "http://llm.test/v1", "k", "m", [{"role": "user", "content": "x"}], timeout=5.0
        )


# ④ vision 消息格式（base64 data URL 与 https URL）


def test_vision_message_from_bytes_is_base64_data_url():
    message = ai_service._vision_message(b"\xff\xd8\xff")
    content = message["content"]
    assert content[0]["type"] == "image_url"
    url = content[0]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(url.removeprefix("data:image/jpeg;base64,")) == b"\xff\xd8\xff"
    assert content[1]["type"] == "text"


def test_vlm_client_parses_items_json(monkeypatch):
    """VLM 客户端：content 为 ```json 包裹的 {"items": [...]} → 解析为候选列表。"""
    raw = json.dumps({"items": [{"name": "清蒸鱼", "confidence": 0.9, "portion_g": 150}]})
    _patch_post(monkeypatch, f"```json\n{raw}\n```")
    client = ai_service._OpenAICompatVLM("http://vlm.test/v1", "k", "v-1", timeout=5.0)
    items = client.recognize_food(b"fake-image")
    assert items == [{"name": "清蒸鱼", "confidence": 0.9, "portion_g": 150}]
