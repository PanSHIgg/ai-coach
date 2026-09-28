# AI API 配置说明（Qwen3.8-Flash-Next · ModelScope）

> 开发期统一使用魔搭社区（ModelScope）托管的 **Qwen3.8-Flash-Next**，通过 **OpenAI Chat Completions 兼容接口**调用。
> 本文档所有参数均已**实测验证通过**（2026-09-28）。

---

## 1. 连接参数（核心）

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `base_url` | `https://api-inference.modelscope.cn/v1` | OpenAI 兼容基址，**必须带 `/v1` 后缀** |
| 完整端点 | `https://api-inference.modelscope.cn/v1/chat/completions` | `POST` |
| `api_key` | `ms-9ea67988-26a6-4823-9213-0801301411cd` | 魔搭 API-Inference 令牌，请求头 `Authorization: Bearer <key>` |
| `model` | `Qwen/Qwen3.8-Flash-Next` | 模型 ID，已在 `/v1/models` 列表中确认存在 |
| 协议 | OpenAI Chat Completions（`openai-completions`） | 与 OpenAI SDK 完全兼容 |
| `context`（上下文长度） | **262,144 tokens（256K）** | 原生支持；经 YaRN 可扩展至约 1M（托管 API 未实测，长文本需自测） |
| `max_tokens`（输出上限） | 最终响应 **131,072**；推理内容 **262,144** | 官方建议值 |
| `stream` | 支持（`stream: true` → SSE） | 实测通过 |
| 多模态（**VLM**） | 输入 **文本 / 图像 / 视频**，输出 文本 | **自带视觉能力**，拍照识别可复用同一模型，无需另接视觉 API（详见 §4.5）|

---

## 2. 请求参数（可选项）

| 参数 | 默认值 | 可选值 | 作用 / 实测结论 |
| --- | --- | --- | --- |
| `enable_thinking` | `true` | `true` / `false` | **关闭思考可大幅省 token**：同一问题实测 `119 tokens → 35 tokens`（省约 70%），且响应更快。对"AI 饮食教练"这类短问答建议 `false` |
| `reasoning_effort` | `xhigh` | `low` / `medium` / `xhigh` | 推理强度。实测 `low` 时推理内容仅一句。复杂推理（热量计算校验、长文档 RAG）才用 `xhigh` |
| `temperature` | 模型默认 | `0 ~ 2` | 建议固定人设场景用 `0.3~0.7` |
| `top_p` | 模型默认 | `0 ~ 1` | — |
| `max_tokens` | — | 正整数 | 单次响应上限，注意别超过 131,072 |

### 响应结构要点
- 思考模式下，响应额外带 **`reasoning_content`** 字段（思维链），正式答案在 `content`。
- **取答案时务必读 `content`，不要误用 `reasoning_content`**，否则会把思考过程返回给用户。

---

## 3. 模型规格速查

| 项 | 值 |
| --- | --- |
| 架构 | MoE（Qwen4 架构预览版） |
| 总参数 / 激活参数 | 125B / 每 token 约 6B |
| 原生上下文 | 262,144 tokens |
| 长上下文扩展 | YaRN → 约 1,000,000 tokens |
| 思考模式 | 默认开启，可 `enable_thinking=false` 关闭 |
| 开源许可 | Qwen Community License 1.0 |

---

## 4. 调用示例

### 4.1 curl（最简验证）

```bash
curl https://api-inference.modelscope.cn/v1/chat/completions \
  -H "Authorization: Bearer ms-9ea67988-26a6-4823-9213-0801301411cd" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3.8-Flash-Next",
    "messages": [
      {"role": "system", "content": "你是AI饮食教练，只回答体重管理相关问题。"},
      {"role": "user", "content": "今天摄入1200大卡，TDEE 2000，缺口是多少？"}
    ],
    "enable_thinking": false,
    "temperature": 0.5,
    "max_tokens": 512
  }'
```

### 4.2 Python（openai SDK）

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://api-inference.modelscope.cn/v1",
    api_key="ms-9ea67988-26a6-4823-9213-0801301411cd",
)

resp = client.chat.completions.create(
    model="Qwen/Qwen3.8-Flash-Next",
    messages=[
        {"role": "system", "content": "你是AI饮食教练，只回答体重管理相关问题。"},
        {"role": "user", "content": "今天摄入1200大卡，TDEE 2000，缺口是多少？"},
    ],
    enable_thinking=False,   # 省 token、降延迟
    temperature=0.5,
    max_tokens=512,
)

answer = resp.choices[0].message.content      # 正式答案
# reasoning = resp.choices[0].message.reasoning_content  # 仅思考模式下有
print(answer)
```

### 4.3 流式输出

```python
stream = client.chat.completions.create(
    model="Qwen/Qwen3.8-Flash-Next",
    messages=[{"role": "user", "content": "给我一份减脂晚餐建议"}],
    stream=True,
    enable_thinking=False,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### 4.4 若用于 `openai-completions` provider 配置（如 opencode / 编码工具）

```json
{
  "provider": "openai-completions",
  "options": {
    "baseURL": "https://api-inference.modelscope.cn/v1",
    "apiKey": "ms-9ea67988-26a6-4823-9213-0801301411cd",
    "model": "Qwen/Qwen3.8-Flash-Next"
  }
}
```

### 4.5 视觉识别（VLM 多模态）

**模型自带视觉能力，对话与拍照识别可统一用同一个模型**，无需再单独接入腾讯云/阿里云图像识别。

图片通过 `content` 数组与文本混排传入：

```python
import base64
from openai import OpenAI

client = OpenAI(
    base_url="https://api-inference.modelscope.cn/v1",
    api_key="ms-9ea67988-26a6-4823-9213-0801301411cd",
)

with open("meal.jpg", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

resp = client.chat.completions.create(
    model="Qwen/Qwen3.8-Flash-Next",
    messages=[{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": "识别图中的食物，输出 JSON：items[{name, portion_g, kcal}]"},
        ],
    }],
    enable_thinking=False,
    max_tokens=1024,
)
print(resp.choices[0].message.content)
```

**关键要点**：

- **推荐 base64 data URI**（`data:image/jpeg;base64,...`）。实测远程 URL 方式**服务端拉取会超时**（境外图床失败），国内 COS 直链可能可用但需自测。
- 图片建议压缩到 **1MB 内、短边 512~1024 px**，控制 token 消耗与延迟。
- 需要结构化结果就在 prompt 里直接要求 JSON，后端再做解析 / 校验。
- 视觉 + OCR 均可用（实测能读出图中文字）。

**对 `plan.md` 的影响**：

- **P0-h 决策点**：视觉与 LLM 可**收敛为同一家（本模型）**，省掉一套视觉 API 的 Key、额度与成本对接。
- **BE4a（`meal/recognize`）**：图片 → COS → 本模型识别 → 匹配 `food` 表；置信度 < 0.7 仍需用户确认（保持原设计不变）。

---

## 5. 接入本项目（ai-coach）

后端为 **Python 3.12 + FastAPI**，Phase 2 的 AI 对话（BE4b）用 **LangChain**。建议配置写入 `.env`（勿提交，参考 `.env.example`）：

```bash
# --- ModelScope / Qwen ---
MS_API_KEY=ms-9ea67988-26a6-4823-9213-0801301411cd
MS_BASE_URL=https://api-inference.modelscope.cn/v1
MS_MODEL=Qwen/Qwen3.8-Flash-Next
MS_ENABLE_THINKING=false      # 对话场景关闭思考，省成本降延迟
MS_MAX_TOKENS=1024
MS_TIMEOUT=20                 # 对齐 plan.md：AI P95 < 3s，超时降级预置 FAQ
```

LangChain 接入要点：

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="Qwen/Qwen3.8-Flash-Next",
    base_url="https://api-inference.modelscope.cn/v1",
    api_key="ms-9ea67988-26a6-4823-9213-0801301411cd",
    temperature=0.5,
    max_tokens=1024,
    timeout=20,
    # 关闭思考（extra_body 透传魔搭私有参数）
    extra_body={"enable_thinking": False},
)
```

---

## 6. 实测验证记录

| 验证项 | 结果 |
| --- | --- |
| `GET /v1/models` 列出模型 | ✅ 通过，`Qwen/Qwen3.8-Flash-Next` 在列表中 |
| 非流式 `chat/completions` | ✅ 通过，正常返回 `content` |
| 流式 `stream=true` | ✅ 通过，SSE 分块返回 |
| `enable_thinking=false` | ✅ 生效，`reasoning_content` 为空串，token 119 → 35 |
| `reasoning_effort=low` | ✅ 生效，推理内容显著缩短 |
| `GET /v1/models/{id}` 单模型信息 | ❌ 返回 404（该端点不存在，忽略即可） |
| **视觉输入（base64 图片）** | ✅ 通过，正确识别形状/颜色，并 OCR 读出图中文字 |
| 视觉输入（远程 `image_url`） | ❌ 服务端拉取超时（境外图床）→ 改用 base64 |

---

## 7. 注意事项

1. **`base_url` 必须带 `/v1`**，否则 404。
2. **默认开启思考模式**，会多消耗一大截 token 并增加延迟。对话类短问答务必显式传 `enable_thinking: false`。
3. **读答案用 `content`**，不要用 `reasoning_content`。
4. `context` 原生 262,144；若需更长必须用 YaRN 且取决于服务端是否支持，**不要直接假设 1M 可用**。
5. `temperature` / `top_p` 二选一调节即可，避免同时乱调。
6. 生产环境应把 key 放进环境变量/密钥管理，不要硬编码；本文件明文记录仅限私有仓库开发环境。
7. 对应 `plan.md` 的 **P0-h（AI spike）决策点**：本模型是 **VLM（自带视觉）**，**对话 + RAG + 拍照识别可统一由它承担**，视觉 provider **无需另选**（腾讯云/阿里云图像识别可作为精度不足时的兜底备选，详见 §4.5）。
