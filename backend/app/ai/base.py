"""AI 客户端抽象基类：只定义协议，不绑定具体厂商。

选型结论与切换方法见 docs/ai-provider-spike.md、本包 README.md。
"""

from abc import ABC, abstractmethod


class LLMClient(ABC):
    """对话/推荐统一接口。"""

    @abstractmethod
    def chat(self, messages: list[dict]) -> str:
        """messages 为 OpenAI 格式 [{"role": "system"|"user"|"assistant", "content": str}]，
        返回助手回复纯文本。调用失败由调用方捕获并降级 FAQ（错误码 6001）。"""


class VisionClient(ABC):
    """视觉识别统一接口：拍照 → 候选食物条目。"""

    @abstractmethod
    def recognize_food(self, image_bytes: bytes) -> list[dict]:
        """返回 [{name, confidence, calorie_estimate}]；
        confidence < 0.7 时上层必须让用户确认/修正（默认规则，06 文档）。"""
