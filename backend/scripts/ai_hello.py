#!/usr/bin/env python3
"""AI 能力 hello-world：验证 provider 选型层可跑通。

无 Key / 无 httpx 时走 mock（仅标准库即可运行）；配置 MS_API_KEY 后走真实调用。
用法：
    python3 backend/scripts/ai_hello.py --task chat
    python3 backend/scripts/ai_hello.py --task vision [--image path/to.jpg]
"""

import argparse
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from app.ai.factory import get_llm_client, get_vision_client  # noqa: E402
from app.ai.prompts import (  # noqa: E402
    AI_COACH_SYSTEM_PROMPT,
    AI_DISCLAIMER,
    AI_UNAVAILABLE_FAQ,
)
from app.core.config import get_settings  # noqa: E402

# 1x1 透明 PNG，供 vision 冒烟（真实识别请 --image 传照片）
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def run_chat() -> None:
    settings = get_settings()
    client = get_llm_client(settings)
    print(f"[chat] client = {type(client).__name__}")
    messages = [
        {"role": "system", "content": AI_COACH_SYSTEM_PROMPT},
        {"role": "user", "content": "下午饿了能吃什么？"},
    ]
    try:
        reply = client.chat(messages)
    except Exception as exc:  # 真实调用失败 → 降级 FAQ（错误码 6001）
        print(f"[chat] 调用失败({type(exc).__name__}: {exc})，降级 6001")
        print(f"[chat] 降级回复: {AI_UNAVAILABLE_FAQ}")
        return
    print(f"[chat] reply: {reply}{AI_DISCLAIMER}")


def run_vision(image_path: str | None) -> None:
    settings = get_settings()
    client = get_vision_client(settings)
    print(f"[vision] client = {type(client).__name__}")
    image = Path(image_path).read_bytes() if image_path else _TINY_PNG
    try:
        items = client.recognize_food(image)
    except Exception as exc:
        print(f"[vision] 识别失败({type(exc).__name__}: {exc})，请提示用户手动录入")
        return
    need_confirm = any(i["confidence"] < 0.7 for i in items)
    print(f"[vision] items: {items}")
    print(f"[vision] need_confirm = {need_confirm}（置信度 < 0.7 需用户确认）")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI provider hello-world（P0-h spike）")
    parser.add_argument("--task", choices=["chat", "vision"], default="chat")
    parser.add_argument("--image", help="vision 冒烟图片路径（默认 1x1 PNG）")
    args = parser.parse_args()
    if args.task == "chat":
        run_chat()
    else:
        run_vision(args.image)


if __name__ == "__main__":
    main()
