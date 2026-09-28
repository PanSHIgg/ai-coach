"""本地 Mock 实现：无 Key / 测试环境使用，仅标准库、零网络依赖。

按关键词返回预置回答（docs/split/06-AI服务.md §4.3 示例话术）；
识别返回 3 个固定条目，置信度同时覆盖 ≥0.7 与 <0.7（need_confirm）分支。
"""

from .base import LLMClient, VisionClient
from .prompts import AI_DISCLAIMER

# 疾病类规则置顶，避免被普通问题抢先命中
_FAQ_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        ("病", "疼", "药", "诊断", "就医"),
        "涉及健康与疾病的问题请咨询专业医生，我不提供诊断或用药建议。",
    ),
    (
        ("饿", "能吃什么", "还吃"),
        "建议先喝一杯水，15分钟还不饱再吃个水煮蛋或黄瓜，热量低还顶饱。",
    ),
    (
        ("油", "热量", "卡", "肥"),
        "优先选清蒸、白灼、凉拌做法，油炸和糖醋类每份热量通常翻倍，尽量少选。",
    ),
    (
        ("没瘦", "平台", "为什么"),
        "体重有波动很正常，先看连续 7 天趋势；保持热量缺口、足量饮水并保证睡眠。",
    ),
]

_FALLBACK_REPLY = "请补充你的目标体重和当日已摄入热量，我可以给出更具体的建议。"


class MockLLMClient(LLMClient):
    """按关键词返回预置回答，永远可用。"""

    def chat(self, messages: list[dict]) -> str:
        question = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        for keywords, answer in _FAQ_RULES:
            if any(k in question for k in keywords):
                return answer
        return _FALLBACK_REPLY


class MockVisionClient(VisionClient):
    """返回 3 个固定食物条目，不依赖网络。

    calorie_estimate 为估算值（kcal，份量按 06 文档 §4.2 示例）。
    """

    def recognize_food(self, image_bytes: bytes) -> list[dict]:
        return [
            {"name": "清蒸鱼", "confidence": 0.88, "calorie_estimate": 180},
            {"name": "米饭", "confidence": 0.72, "calorie_estimate": 174},
            {"name": "红烧肉", "confidence": 0.61, "calorie_estimate": 320},
        ]
