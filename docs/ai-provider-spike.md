# AI Provider 选型 spike（P0-h）

> 结论先行：**LLM 默认 DeepSeek（OpenAI 兼容 `/chat/completions`），视觉默认腾讯云 tiia 菜品识别**；
> 全部客户端经 `backend/app/ai` 工厂获取，无 Key / 未知 provider 一律回落 mock，不卡死（错误码 6001）。
> 切换另一家 = 改环境变量为主、新增一个子类 + 工厂一个分支为辅。自检：`python3 backend/scripts/ai_hello.py --task chat|vision`（已实跑通过）。

## 一、LLM：DeepSeek vs 通义千问

| 维度 | DeepSeek（默认） | 通义千问（备选） |
| --- | --- | --- |
| 协议 | OpenAI 兼容 `/chat/completions`，base_url `https://api.deepseek.com` | 百炼 DashScope OpenAI 兼容模式 `compatible-mode/v1` |
| 价格 | 官网 2026-09 报价：deepseek-flash 输入 $0.15/M（off-peak）~$0.3/M（peak）、输出 $0.6~$1.2/M；另有 2026-08 涨价报道（未缓存输入 ¥3/M、输出 ¥6/M 档）——两处口径不一致，【假设】按较贵档估算 | 【假设】未核实到官网现价，按同量级估；切换前按百炼计费页核对 |
| 上下文 | 1M（deepseek-flash） | 【假设】qwen-plus 同量级，未核实 |
| 合规 | 国内可直连；2026-08 涨价需关注 | 阿里云备案主体，企业合规/数据驻留更成熟 |

**改动点（切千问）**：`.env` 设 `AI_LLM_PROVIDER=qwen`、填 `AI_LLM_API_KEY`，`AI_LLM_BASE_URL` 可省（工厂走 DashScope 默认地址）——代码零改动（`QwenClient` 已实现，仅默认 base_url/model 不同）。

## 二、视觉识别：腾讯云 tiia vs 阿里云视觉智能

| 维度 | 腾讯云 tiia（默认） | 阿里云 viapi |
| --- | --- | --- |
| 接口 | `DetectFood`（2019-05-29 版，ImageBase64 入参） | DetectFood（RPC 签名） |
| 计费 | **2026-08 计费列表未单列菜品识别**【待确认在售】；同类 CV 接口阶梯约 ¥2.5/千次、免费额度 1000 次/月【假设】 | 计费页仅见按量/资源包/QPS 三模式，未取到菜品条目【假设】同量级 |
| 替代路线 | 视觉理解大模型 vita-video-3.0：¥1.2/M 输入 + ¥3.5/M 输出——按本模型用量粗算反比传统接口更省 | 同理可走 qwen-vl |
| SDK | TC3-HMAC-SHA256 自签名即可（`vision.py` 已写完整签名函数） | 官方 SDK 成熟但引新依赖，spike 未引入 |

**改动点（切阿里云/大模型）**：新增 `VisionClient` 子类 + `get_vision_client()` 工厂加一个 provider 分支；`MockVisionClient` 与上层调用零改动。

## 三、成本估算（1000 DAU）

【假设】人均 2 次对话/天 + 3 次识别/天；单次对话 ~1.2K 输入 + 0.5K 输出 tokens；单次识别 ~800 输入 + 200 输出 tokens（大模型路线）。

- 对话：6 万次/月 → DeepSeek 按 peak 档 ≈ **¥420/月**（off-peak/缓存命中更低）
- 识别：9 万次/月 → 传统接口 ¥2.5/千次 ≈ ¥225/月；大模型路线 ≈ ¥150/月
- 合计 ≈ **¥450~700/月**（P0 验证期可接受；后续按真实用量修正）

## 四、降级策略（06 文档 §六）

1. LLM 调用失败/超时 → 返回 `AI_UNAVAILABLE_FAQ`（`app/ai/prompts.py`），错误码 6001，不卡死；
2. 视觉识别失败 → 提示手动录入，不阻塞记录流程；
3. 置信度 < 0.7 → `need_confirm=True`，必须用户确认/修正（mock 已覆盖该分支）；
4. 无 Key / 未知 provider / httpx 缺失 → 工厂一律回落 mock 并打 warning 日志。

## 五、Key / 额度申请 checklist

- [ ] DeepSeek：开放平台注册 → 充值 → 建 Key → `AI_LLM_API_KEY`（模型名按官网校正，`deepseek-chat` 为遗留名仍接受【待确认】）
- [ ] 腾讯云：开通图像分析（tiia）→ **确认 DetectFood 在售** → CAM 建子账号密钥（仅授权 tiia）→ `AI_VISION_API_KEY`
- [ ] （备选）百炼：开通 DashScope → 建 Key → `AI_LLM_PROVIDER=qwen`
- [ ] `.env` 按 `code/.env.example` 的 AI_* 命名填写，不入库

## 六、【假设】清单

1. `AI_VISION_API_KEY` 格式为 `{SecretId}:{SecretKey}`（TC3 签名需两值，.env.example 仅一个变量，用冒号拼接）；
2. 用量假设：1000 DAU × 2 次对话 + 3 次识别/天；
3. 腾讯 DetectFood 单价按同类 CV 接口阶梯估，2026-08 计费列表未单列，开通时需确认；
4. 阿里云/Qwen 价格未核实到官网现价，按同量级估算；
5. 识别接口不返回份量，`calorie_estimate` 统一按 150g 份量 × 每 100g 粗估表计算。

> 价格与接口在售状态随时间变化，上线前以官网实时页为准。
