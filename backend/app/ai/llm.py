"""DeepSeek / 通义千问同步客户端（OpenAI 兼容 /chat/completions，httpx）。

切换说明见 docs/ai-provider-spike.md 与本包 README.md。
"""

import httpx

from .base import LLMClient

# 超时：连接 3s / 读 30s（AI 对话 P95 < 3s 的服务端预算，06 文档 §五）
_TIMEOUT = httpx.Timeout(30.0, connect=3.0)

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class DeepSeekClient(LLMClient):
    """DeepSeek 对话客户端；同样适用于任何 OpenAI 兼容网关。"""

    default_base_url = _DEEPSEEK_BASE_URL
    # deepseek-chat 为遗留名仍被接受；当前官网主推 deepseek-flash（1M 上下文），
    # 上线前按官网校正模型名（见 docs/ai-provider-spike.md【假设】）
    default_model = "deepseek-chat"

    def __init__(self, api_key: str, base_url: str | None = None, model: str | None = None):
        self.api_key = api_key
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.model = model or self.default_model

    def chat(self, messages: list[dict]) -> str:
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class QwenClient(DeepSeekClient):
    """通义千问（百炼 DashScope OpenAI 兼容模式），仅默认地址/模型不同。"""

    default_base_url = _QWEN_BASE_URL
    default_model = "qwen-plus"
