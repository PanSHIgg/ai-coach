# backend/app/ai · AI 客户端抽象层

**D-09 收敛**：LLM 与 VLM 统一走 OpenAI 兼容协议（`/v1/chat/completions`），
DeepSeek/通义/腾讯云/阿里云/ModelScope 专用适配器已删除；换厂商只改 env。

**客户端装配**：
- LLM：`app/services/ai_service.py::llm_client_for(settings)`（LLM_* 三件套）
- VLM：`app/services/recognize_service.py::vision_client_for(settings)`（VLM_* 三件套）

**未配置 base_url/api_key 时**：明确降级 Mock（`mock.py`），零网络依赖，不崩。

## 模块

| 文件          | 说明                                                                                   |
| ------------- | -------------------------------------------------------------------------------------- |
| `base.py`     | `LLMClient.chat(messages)->str`、`VisionClient.recognize_food(bytes)->list[dict]` 抽象 |
| `mock.py`     | `MockLLMClient`（关键词 FAQ）/ `MockVisionClient`（3 固定条目，含 <0.7 置信度）        |
| `prompts.py`  | 系统提示词、免责声明、降级 FAQ（6001）常量                                              |
| `__init__.py` | 抽象与 Mock 的统一导出                                                                  |

## 配置（对齐 .env.example）

| 变量 | 说明 |
| --- | --- |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 对话（ai/chat、ai/recommend、周点评），OpenAI 兼容端点 |
| `VLM_BASE_URL` / `VLM_API_KEY` / `VLM_MODEL` | 拍照识别（meal/recognize），OpenAI vision 消息格式 |
| `AI_TIMEOUT` | 超时秒数（默认 5.0，对齐 P95<3s） |

## 自检

```bash
python3 -m py_compile backend/app/ai/*.py backend/scripts/ai_hello.py
python3 backend/scripts/ai_hello.py --task chat
python3 backend/scripts/ai_hello.py --task vision
```
