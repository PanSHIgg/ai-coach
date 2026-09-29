# backend/app/ai · AI Provider SDK 抽象层

**生产唯一入口**：`app.ai.factory`（传 Settings，读取 `MS_API_KEY`）

**当前 provider**：ModelScope Qwen3.8-Flash-Next（对齐 `ai_api.md`，VLM 统一对话+视觉）

**备用 provider 实现**（未接入生产）：
- `llm.py`：DeepSeek/Qwen（OpenAI 兼容）
- `vision.py`：腾讯云图像识别

**无 Key 时**：自动落 Mock（`mock.py`），零网络依赖。

## 模块

| 文件            | 说明                                                                 |
| --------------- | -------------------------------------------------------------------- |
| `factory.py`    | **生产入口**：`get_llm_client(settings)` / `get_vision_client(settings)` |
| `base.py`       | `LLMClient.chat(messages)->str`、`VisionClient.recognize_food(bytes)->list[dict]` 抽象 |
| `llm.py`        | `DeepSeekClient` / `QwenClient`（备用 provider，未接入生产） |
| `vision.py`     | `TencentVisionClient`（备用 provider，未接入生产） |
| `mock.py`       | `MockLLMClient`（关键词 FAQ）/ `MockVisionClient`（3 固定条目，含 <0.7 置信度） |
| `prompts.py`    | 系统提示词、免责声明、降级 FAQ（6001）常量 |
| `__init__.py`   | 向后兼容导入（工厂函数已删除） |

## 用法

```python
from app.ai.factory import get_llm_client, get_vision_client
from app.core.config import get_settings

settings = get_settings()
llm = get_llm_client(settings)
vision = get_vision_client(settings)

reply = llm.chat([
    {"role": "system", "content": AI_COACH_SYSTEM_PROMPT},
    {"role": "user", "content": "下午饿了能吃什么？"},
])
items = vision.recognize_food(image_bytes)
# items: [{"name", "confidence", "calorie_estimate"}]，confidence < 0.7 需用户确认
```

## 配置（对齐 .env.example）

| 变量 | 说明 |
| --- | --- |
| `MS_API_KEY` | ModelScope API Key（必填，否则落 Mock） |
| `MS_BASE_URL` | ModelScope 推理地址（默认 `https://api-inference.modelscope.cn/v1`） |
| `MS_MODEL` | 模型名（默认 `Qwen/Qwen3.8-Flash-Next`） |
| `MS_ENABLE_THINKING` | 是否启用思考模式（默认 false，省 token） |
| `MS_MAX_TOKENS` | 最大输出 token（默认 1024） |
| `MS_TIMEOUT` | 超时秒数（默认 5.0，对齐 P95<3s） |

**注意**：`AI_LLM_*` / `AI_VISION_*` 配置字段已废弃，factory 不读取。

## 自检

```bash
python3 -m py_compile backend/app/ai/*.py backend/scripts/ai_hello.py
python3 backend/scripts/ai_hello.py --task chat
python3 backend/scripts/ai_hello.py --task vision
```

选型对比、成本估算、降级策略与 Key 申请清单见 `docs/ai-provider-spike.md`。
