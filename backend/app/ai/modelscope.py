"""ModelScope（魔搭）Qwen3.8-Flash-Next 客户端——对话 + 视觉统一走同一个 VLM。

真源：`ai_api.md`（连接参数、enable_thinking、取 content 而非 reasoning_content、
视觉用 base64 data URI）。模型自带视觉能力，故对话与拍照识别复用同一端点，
无需再接腾讯云/阿里云图像识别（06 文档 AI 行的备选降级路径保留在 factory）。

协议：OpenAI Chat Completions 兼容（`POST {base_url}/chat/completions`，base_url 必须带 /v1）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Any

import httpx

from .base import LLMClient, VisionClient

# 视觉识别提示词：要求纯 JSON 输出，便于后端解析并匹配 food 表
_VISION_PROMPT = (
    "你是食物识别助手。识别图片中的食物，只输出 JSON，不要任何解释文字，格式：\n"
    '{"items":[{"name":"食物中文名","confidence":0.0-1.0,"portion_g":整数克重,'
    '"kcal_100g":每100克热量整数}]}\n'
    "最多 5 项，按画面占比从大到小排序。"
)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """从模型输出中抠出 JSON：优先 ```json 代码块，其次首尾括号之间的片段。"""
    text = (text or "").strip()
    m = _JSON_BLOCK.search(text)
    if m:
        return json.loads(m.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError(f"模型未返回 JSON：{text[:200]}")
    return json.loads(text[start : end + 1])


class ModelScopeLLMClient(LLMClient):
    """对话客户端（OpenAI 兼容）。无 Key 时由 factory 降级为 Mock，不应实例化本类。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api-inference.modelscope.cn/v1",
        model: str = "Qwen/Qwen3.8-Flash-Next",
        *,
        timeout: float = 20.0,
        max_tokens: int = 1024,
        temperature: float = 0.5,
        enable_thinking: bool = False,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.enable_thinking = enable_thinking

    def chat(self, messages: list[dict]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "enable_thinking": self.enable_thinking,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=3.0)) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        message = data["choices"][0]["message"]
        # 关键：取 content，不能误用 reasoning_content（ai_api.md §2）
        content = (message.get("content") or "").strip()
        if not content and message.get("reasoning_content"):
            content = message["reasoning_content"].strip()
        return content

    async def achat(self, messages: list[dict]) -> str:
        """异步包装：同步 httpx 放线程池，避免阻塞事件循环。"""
        return await asyncio.to_thread(self.chat, messages)


class ModelScopeVisionClient(VisionClient):
    """视觉识别客户端：同一 VLM，图片以 base64 data URI 传入（远程 URL 会超时）。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api-inference.modelscope.cn/v1",
        model: str = "Qwen/Qwen3.8-Flash-Next",
        *,
        timeout: float = 20.0,
        max_tokens: int = 1024,
        enable_thinking: bool = False,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.enable_thinking = enable_thinking

    def recognize_food(self, image_bytes: bytes) -> list[dict]:
        b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                        {"type": "text", "text": _VISION_PROMPT},
                    ],
                }
            ],
            "enable_thinking": self.enable_thinking,
            "max_tokens": self.max_tokens,
        }
        with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=3.0)) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        message = data["choices"][0]["message"]
        raw = (message.get("content") or "").strip() or (message.get("reasoning_content") or "")
        return _normalize_items(_extract_json(raw))

    async def arecognize_food(self, image_bytes: bytes) -> list[dict]:
        return await asyncio.to_thread(self.recognize_food, image_bytes)


def _normalize_items(parsed: Any) -> list[dict]:
    """归一化模型输出 → [{name, confidence, portion_g, kcal_100g}]，最多 5 项。"""
    if isinstance(parsed, dict):
        raw_items = parsed.get("items") or []
    elif isinstance(parsed, list):
        raw_items = parsed
    else:
        raw_items = []

    items: list[dict] = []
    for raw in raw_items[:5]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(max(confidence, 0.0), 1.0)
        try:
            portion_g = int(float(raw.get("portion_g") or 0))
        except (TypeError, ValueError):
            portion_g = 0
        try:
            kcal_100g = float(raw.get("kcal_100g") or 0)
        except (TypeError, ValueError):
            kcal_100g = 0.0
        items.append(
            {
                "name": name,
                "confidence": round(confidence, 2),
                "portion_g": portion_g if portion_g > 0 else 150,
                "kcal_100g": round(kcal_100g, 1),
            }
        )
    return items
