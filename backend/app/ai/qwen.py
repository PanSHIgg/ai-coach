"""通义千问（阿里云百炼 DashScope OpenAI 兼容模式）对话客户端。

选型依据：主文档 §6.1 AI 行「DeepSeek / 通义千问 API（对话+RAG）」。
与 DeepSeek 同为 OpenAI 兼容协议，仅默认 base_url / model 不同。
"""

from .deepseek import DeepSeekClient

_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class QwenClient(DeepSeekClient):
    """通义千问（百炼 DashScope OpenAI 兼容模式），仅默认地址/模型不同。"""

    default_base_url = _QWEN_BASE_URL
    default_model = "qwen-plus"
