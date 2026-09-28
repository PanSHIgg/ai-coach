# backend/app/ai · AI Provider SDK 抽象层

P0-h spike 交付：统一 LLM 对话与视觉识别接口，默认 DeepSeek（OpenAI 兼容）+ 腾讯云图像识别，无 Key 时一律落 mock。

## 模块

| 文件            | 说明                                                                 |
| --------------- | -------------------------------------------------------------------- |
| `base.py`       | `LLMClient.chat(messages)->str`、`VisionClient.recognize_food(bytes)->list[dict]` 抽象 |
| `llm.py`        | `DeepSeekClient` / `QwenClient`（httpx 同步，OpenAI 兼容 `/chat/completions`，超时 连接 3s/读 30s） |
| `vision.py`     | `TencentVisionClient`（httpx + TC3-HMAC-SHA256 签名，tiia `DetectFood` 骨架） |
| `mock.py`       | `MockLLMClient`（关键词 FAQ）/ `MockVisionClient`（3 固定条目，含 <0.7 置信度） |
| `prompts.py`    | 系统提示词、免责声明、降级 FAQ（6001）常量                           |
| `__init__.py`   | 工厂 `get_llm_client()` / `get_vision_client()`                      |

## 用法

```python
from app.ai import get_llm_client, get_vision_client

reply = get_llm_client().chat([
    {"role": "system", "content": AI_COACH_SYSTEM_PROMPT},
    {"role": "user", "content": "下午饿了能吃什么？"},
])
items = get_vision_client().recognize_food(image_bytes)
# items: [{"name", "confidence", "calorie_estimate"}]，confidence < 0.7 需用户确认
```

## 配置（对齐 code/.env.example 的 AI_* 命名）

| 变量                                    | 说明                                                       |
| --------------------------------------- | ---------------------------------------------------------- |
| `AI_LLM_PROVIDER`                       | `deepseek`（默认）/ `qwen`；未知值落 mock 并打日志         |
| `AI_LLM_API_KEY`（回落 `AI_API_KEY`）   | 缺失即落 mock                                              |
| `AI_LLM_BASE_URL`（回落 `AI_BASE_URL`） | OpenAI 兼容网关地址（如 DashScope compatible-mode）        |
| `AI_LLM_MODEL`                          | 默认 `deepseek-chat` / `qwen-plus`                         |
| `AI_VISION_PROVIDER`                    | `tencent`（默认）；其余值暂落 mock（切换点见 spike 文档）  |
| `AI_VISION_API_KEY`                     | 腾讯云格式 `{SecretId}:{SecretKey}`【假设】                |
| `AI_VISION_BASE_URL`                    | 代理/兼容网关地址                                          |

## 切换 provider

- LLM 切通义千问：`AI_LLM_PROVIDER=qwen` + 百炼 Key（`AI_LLM_BASE_URL` 可省，走默认 DashScope 兼容地址），代码零改动。
- 视觉切阿里云：实现新的 `VisionClient` 子类（RPC 签名或视觉理解大模型），工厂加一个分支即可。

## 自检

```bash
python3 -m py_compile backend/app/ai/*.py backend/scripts/ai_hello.py
python3 backend/scripts/ai_hello.py --task chat
python3 backend/scripts/ai_hello.py --task vision
```

选型对比、成本估算、降级策略与 Key 申请清单见 `docs/ai-provider-spike.md`。
