# AI 服务 + 核心业务算法与业务规则 · 代码-文档一致性核对报告

> ⚠️ **已过期归档**（2026-09-30 迁入 `docs_process/archive/`）：本报告为 2026-09-30 分域核对分报告（slot4，AI 与业务算法，基线 `dbbf198`），结论已并入同日主 Agent 定案汇总。**取代真源：`docs_process/archive/review_20260930_summary.md`**。本文仅留档。

> **审查 Agent**：slot=4（只读审查）  
> **审查日期**：2026-09-30  
> **仓库分支**：`docs/env-check-0930`（内容 = `origin/develop`，`dbbf198`，Phase 5）  
> **审查范围**：AI provider 层、AI 接口端到端、AI 次数与权益、热量账户算法、RAG、业务规则差集、测试覆盖  
> **真源**：`docs/split/06-AI服务.md` + `docs/split/01-整体架构与产品需求.md` + `docs/split/04-后端技术架构与数据库.md` + `ai_api.md` + `AGENTS.md`

---

## 1. 结论摘要

| 维度 | 结果 |
| --- | --- |
| **总不符项** | **11 条** |
| P0（阻断） | **0 条** |
| P1（真实缺陷） | **5 条** |
| P2（轻微/文档陈旧） | **6 条** |
| **整体结论** | **PASS（附 P1 待修）** |

pytest **496 passed / 0 failed**（130.05s，库 `ai_coach_s4`，2026-09-30 07:25 UTC）。  
ai_hello.py chat/vision 均正常（mock 模式）。  
热量对拍 **50/50 误差 0**。  
AI 接口真落库（ai_dialog 写入 user+assistant 双行）、真扣次数（10→9→8）、真限流（Redis db4 可见 key）。

---

## 2. 实跑原始摘要

### 2.1 pytest（2026-09-30 07:25 UTC，库 ai_coach_s4）

```
496 passed in 130.05s (0:02:10)
```

测试文件 35 个，覆盖：`test_ai_chat` / `test_recognize` / `test_recommend` / `test_calorie_engine` / `test_subscription` / `test_invite_flow` / `test_content_security` / `test_orders` / `test_community` / `test_track` 等——文档承诺的核心行为均有对应测试文件。

### 2.2 ai_hello.py

```
[chat] client = MockLLMClient
[chat] reply: 建议先喝一杯水，15分钟还不饱再吃个水煮蛋或黄瓜，热量低还顶饱。（AI 输出仅供参考，具体请遵医嘱）

[vision] client = MockVisionClient
[vision] items: [{'name': '清蒸鱼', 'confidence': 0.88, 'calorie_estimate': 180}, ...]
[vision] need_confirm = True（置信度 < 0.7 需用户确认）
```

→ 无 Key 自动落 mock，不崩，符合 AGENTS.md §7.3。

### 2.3 AI 接口 curl 关键响应

**POST /api/ai/chat**（session_id="s-1", message="下午饿了能吃什么"）：
```json
{"code":0,"data":{"reply":"建议先喝一杯水...（AI 输出仅供参考，具体请遵医嘱）","intent":"hunger_rescue","times_left":9,"references":["knowledge:16","knowledge:27","knowledge:28"]}}
```

**GET /api/ai/times**：`{"times_left":9}` → 第二次调用后变 8 → 第三次变 7。**递减确认**。

**POST /api/ai/recommend**（meal_type=2）：返回 3 个组合（高蛋白/均衡/低碳），带 `[推荐]`/`[可接受]`/`[建议少吃]` 前缀。

**POST /api/meal/recognize**（multipart image 上传）：
```json
{"code":0,"data":{"request_id":"...","items":[{"food_id":null,"name":"清蒸鱼","confidence":0.88,...},{"food_id":1,"name":"白米饭","confidence":0.72,...},{"food_id":null,"name":"红烧肉","confidence":0.61,...}],"need_confirm":true}}
```

→ multipart 上传可用，字段名 `image` 与契约一致，识别结果结构匹配。

### 2.4 热量对拍

`data/testcases/calorie_test_cases.xlsx`（DATA4，50 行）存在且可读。  
**50/50 误差 0**（tolerance 0.15 kcal）。BMR/TDEE/NEAT/TEF/PAL/步数校准/缺口/today_left 全口径一致。

### 2.5 DB 落库验证

```
ai_dialog: 2 rows (user + assistant) after 1 chat → 4 rows after 2 chats
user_benefit: user_id=2, tier=0, ai_times_left=9 (after 1 chat, was 10)
Redis db4: ratelimit:ai:chat:user:2, ratelimit:ai:user:2  ← 限流 key 存在
```

---

## 3. 分级问题清单

| # | 级别 | 文档出处 | 代码位置 | 问题 | 证据 | 建议修法 |
|---|------|---------|---------|------|------|---------|
| 1 | **P1** | 06 §2.3 "RAG 检索知识库"；04 §6.3.2 "PGVector 首期可 jsonb 占位" | `app/services/ai_service.py:96` `retrieve_knowledge` | **RAG 全文检索实质失效**：`ai_knowledge.search_vec` 用 `to_tsvector('simple', title\|\|' '\|\|content)` 生成，但 `simple` 配置不做中文分词——整段中文被当作单个 token。实测 `plainto_tsquery('simple','热量')` 无法匹配任何行（0 rows），每次都降级到 ILIKE 兜底。ILIKE 用 2 字滑窗匹配，精度有限且不走索引。 | `psql`: `SELECT count(*) FROM ai_knowledge WHERE search_vec @@ plainto_tsquery('simple','热量')` → **0**；`search_vec::text` 显示整段内容为一个 lexeme。curl 实测 references 变化但靠 ILIKE 兜底。 | ① 改用 `jieba` 或 PG `zhparser` 扩展做中文分词；② 或首期直接用 `pg_trgm` 的 `similarity()` + GIN 索引替代 tsvector；③ 至少在 `ai_knowledge` 上建 `gin (title gin_trgm_ops)` 索引。 |
| 2 | **P1** | 06 §4.2 拍照识别示例含 `food_id:208 "清蒸鱼"` | `app/ai/mock.py:53` `MockVisionClient` | **Mock 视觉返回的食物名大部分不在 food 表中**：mock 固定返回"清蒸鱼/米饭/红烧肉"，但 food 表无"清蒸鱼"（只有"清蒸三文鱼"等具体菜名）、无"红烧肉"（只有"红烧鸡胸肉"等）。实测识别结果 2/3 条 `food_id=null`。 | curl 实测：`清蒸鱼→null, 白米饭→food_id=1, 红烧肉→null`。`psql`: `SELECT * FROM food WHERE name='清蒸鱼'` → 0 rows。 | 将 mock 返回改为 food 表中实际存在的食物名（如"白米饭""清蒸三文鱼""红烧鸡胸肉"），使 mock 环境也能走通"识别→匹配→落库"全链路。 |
| 3 | **P1** | `docs_process/ai-provider-spike.md` §一 "LLM 默认 DeepSeek" | `app/ai/factory.py:22-42` `get_llm_client` | **spike 文档与代码不一致**：spike 文档（最后更新约 Phase 2）声明"LLM 默认 DeepSeek"，但 `factory.py` 实际只检查 `MS_API_KEY`（ModelScope Qwen），DeepSeek/QwenClient 类存在于 `llm.py` 但 factory 从不路由到它们。`ai_api.md`（develop 新增）已更新为 ModelScope 为准，但 spike 文档未同步。 | `factory.py:22`: `def _use_modelscope(settings): return bool(settings.MS_API_KEY)`；无 `AI_LLM_PROVIDER` 分支。`llm.py` 的 `DeepSeekClient`/`QwenClient` 是死代码（factory 不引用）。 | ① 在 spike 文档末尾追加"已废弃，以 `ai_api.md` 为准"；② 或清理 `llm.py` 的 DeepSeek/Qwen 死代码（factory 已不路由）；③ 保留 `vision.py` 的 `TencentVisionClient` 作为降级备选是合理的，但应在 factory 注释中说明。 |
| 4 | **P1** | 01 §1.2 "分层收费+邀请解锁"；04 §7.2 `user_benefit` 表 | `app/services/ai_service.py:164-197` `ensure_benefit` | **订阅权益不影响 AI 每日次数**：`ensure_benefit` 固定用 `settings.AI_DAILY_TIMES`（=10）重置，不区分 tier 0/1/2/3。文档 01 §1.2 暗示高级 tier 应有更多 AI 次数，但代码无此逻辑。subscription 表存在但从未被 AI 服务引用。 | `ai_service.py:186`: `ai_times_left=s.AI_DAILY_TIMES`（固定 10）；全文无 `tier` 分支。`grep subscription ai_service.py` → 0 hits。 | 按 tier 设置不同 `AI_DAILY_TIMES`（如 tier0=10, tier1=20, tier2=50, tier3=无限），在 `ensure_benefit` 重置时按 tier 取对应值。 |
| 5 | **P1** | 05 §8.4.6 "流式 SSE 或普通 JSON"；01 §2.1 "AI 对话" | `app/api/v1/endpoints/ai.py:25` `ai_chat` | **SSE 流式未实现**：05 文档声明"流式 SSE 或普通 JSON"，但 `ai_chat` 端点只返回普通 JSON。openapi.yaml 已标注"【假设】首期统一返回 JSON；SSE 后续另行扩展"——但 05 文档原文未更新，存在矛盾。 | `ai.py:25`: `response_model=Envelope[AiChatData]`，无 `EventSourceResponse` 或 `text/event-stream`。`grep stream backend/app/api/v1/endpoints/ai.py` → 0 hits。 | ① 在 05 文档 §8.4.6 追加"SSE 首期不实现，统一 JSON"；② 或在 `openapi.yaml` 的假设注释中提升为正式决策并同步 05 文档。 |
| 6 | P2 | 06 §2.1 "视觉识别：腾讯云/阿里云" | `app/ai/factory.py:45-60` | **06 文档视觉选型陈旧**：06 文档仍写"腾讯云/阿里云图像识别"，但 `ai_api.md` 已确定 ModelScope VLM 统一对话+视觉。代码 `factory.py` 只路由到 ModelScope（有 Key 时），`TencentVisionClient` 存在但 factory 不路由。 | `factory.py:46`: `if _use_modelscope(settings): return ModelScopeVisionClient(...)`；无 `AI_VISION_PROVIDER` 分支。 | 在 06 §2.1 追加更新说明："实际选型见 `ai_api.md`，ModelScope Qwen VLM 统一对话+视觉"。 |
| 7 | P2 | 04 §6.3.1 "TEE = BMR×PAL + EAT + TEF" | `app/services/calorie.py:171-173` | **文档 TEE 公式与代码一致**，但 `calorie.py` docstring 额外说明"NEAT 不叠加进 TEE"——这个设计决策在 04 文档中未明确说明（04 只说 TEE = BMR×PAL + EAT + TEF，未提 NEAT 与 TEE 的关系）。代码注释已解释，但文档应补充。 | `calorie.py:172`: "NEAT 为「非睡眠时段总消耗」展示/校准量（含基础代谢），不叠加进 TEE"。 | 在 04 §6.3.1 补充一句："NEAT 仅用于展示与步数校准参考，不计入 TEE 避免重复计基础代谢"。 |
| 8 | P2 | plan.md DATA4 "识别测试图 30 张" | `data/testcases/` | **DATA4 交付物缺失**：plan.md 要求"30 张测试图（食堂/外卖/便利店各 10）"用于识别准确率测试，但 `data/testcases/` 只有 `calorie_test_cases.xlsx` 和 `gen_calorie_cases.py`，无测试图。 | `ls data/testcases/` → 只有 xlsx + py，无图片文件。 | 补充 30 张测试图（或至少标注"延期到 P1"），否则 06 §五 "识别测试集准确率 ≥85%" 无法验证。 |
| 9 | P2 | 01 §1.2 "五种社交：监督、兴趣社群、约战、挑战赛、动态" | `app/api/v1/endpoints/community.py` | **五种社交代码齐备**但文档中"动态"既是社交之一又是社区主体（`community_post`），概念有重叠。代码实现正确（supervise/group/battle/challenge/post 五类均有独立端点），但文档分类可更清晰。 | `community.py` 含 37 个 `@router` 端点，覆盖全部五类。 | 在 01 §1.2 补充说明"动态（community_post）为社区主体，其余四种为社交子功能"。 |
| 10 | P2 | 06 §3.1 "ai_dialog.session_id UUID DEFAULT uuid_generate_v4()" | `app/models/__init__.py:305-306` | **ORM 模型与建表 SQL 一致**：session_id 为 UUID，server_default `uuid_generate_v4()`。但 `ai_service.py:214` 对非 UUID 字符串（如前端占位 "s-1"）用 `uuid5` 派生——这是合理的兼容处理，文档未提及。 | `ai_service.py:214`: `uuid.uuid5(uuid.NAMESPACE_URL, str(session_id))`。 | 在 06 §3.1 补充："前端可传非 UUID 字符串，服务端用 uuid5 稳定派生"。 |
| 11 | P2 | AGENTS.md §7.2 错误码 7001 "邀请已达上限" | `app/services/invite_service.py` | **7001 错误码未在邀请服务中使用**：`invite_service.py` 的 `next_tier_for` 和 `grant_pending_invite_rewards` 无上限校验（无"单人奖励上限 180 天"的硬阻断）。01 §2.3.3 提到"单人奖励上限 180 天"但代码中 `TIER_THRESHOLDS` 最高档为 `None`（永久），无累计上限检查。 | `invite_service.py:31`: `TIER_THRESHOLDS = ((2,1,90),(5,2,180),(10,3,None))`；无累计天数检查。`grep 7001 invite_service.py` → 0 hits。 | 在 `grant_pending_invite_rewards` 中增加累计天数检查（如已获 180 天则不再发放时间型奖励），超限返回 7001。 |

---

## 4. 已验证一致的部分

| 检查项 | 结论 | 证据 |
|--------|------|------|
| AI 无 Key 降级 mock | ✅ 一致 | factory.py 检查 MS_API_KEY，无则返回 MockLLMClient/MockVisionClient |
| 系统提示词固定"AI 饮食教练" | ✅ 一致 | `prompts.py:8-13` AI_COACH_SYSTEM_PROMPT 含"AI 饮食教练"身份、只答体重管理、疾病引导就医 |
| 免责声明 | ✅ 一致 | `ai_service.py:159-160` 自动追加 AI_DISCLAIMER；curl 实测回复末尾含"（AI 输出仅供参考，具体请遵医嘱）" |
| 超时降级预设 FAQ（6001） | ✅ 一致 | `ai_service.py:151-157` TimeoutError/Exception → AppException(AI_UNAVAILABLE, FAQ) |
| 次数不足返回 4001 | ✅ 一致 | `ai_service.py:235-236` → `ErrorCode.QUOTA_EXCEEDED`（=4001） |
| 每日 0 点重置次数 | ✅ 一致 | `ai_service.py:192-196` 检查 `ai_times_reset_at < today_start` 则重置 |
| 置信度 <0.7 需确认 | ✅ 一致 | `recognize_service.py:146-150` `resolve_need_confirm` 检查 confidence < threshold |
| BMR Mifflin-St Jeor 公式 | ✅ 一致 | `calorie.py:69-72` 男+5/女-161，与 04 §6.3.1 一致 |
| PAL 表 5 档 | ✅ 一致 | `calorie.py:30` {1:1.2, 2:1.4, 3:1.6, 4:1.8, 5:2.0} 与 10 §13.3 一致 |
| 步数校准加权（0.6/0.4） | ✅ 一致 | `calorie.py:44-45,121` STEP_WEIGHT=0.6, STATE_WEIGHT=0.4 |
| MET 档（散步2.5/快走4.3/跑步8.0） | ✅ 一致 | `calorie.py:39-42` |
| 缺口 = 摄入 - TEE | ✅ 一致 | `calorie.py:174` `deficit = intake - tee` |
| today_left = 预算 - 摄入 + 运动 - TEF | ✅ 一致 | `calorie.py:176` `today_left = budget - intake + eat - tef` |
| 热量对拍 50 行误差 0 | ✅ 一致 | 实跑 xlsx 50 行全通过 |
| 邀请裂变：首次拍照激活 | ✅ 一致 | `invite_service.py:133-158` `activate_invitee` 由 `create_meal` 调用 |
| 邀请档位 2→90天/5→180天/10→永久 | ✅ 一致 | `invite_service.py:31` TIER_THRESHOLDS |
| 订单金额服务端重算 | ✅ 一致 | `order_service.py:178-194` 按 merchant_sku.price 重算 total/discount/pay |
| 核销码唯一+一次性 | ✅ 一致 | `order.redeem_code` unique 约束；`redeem_order` 状态机 2→3，重复→5004 |
| 退款 2→5 幂等 | ✅ 一致 | `order_service.py:413-435` 已退款直接返回成功 |
| 商家权重排序（拉新40%+券40%+过程20%） | ✅ 一致 | `merchant_service.py:40-43,109-113` |
| 埋点 /api/track | ✅ 一致 | `endpoints/track.py` 存在，curl 实测返回 `{"accepted":1}` |
| 内容安全（msgSecCheck 降级 mock） | ✅ 一致 | `content_security.py` 无凭据走本地违规词 |
| 五种社交全部有端点 | ✅ 一致 | community.py 含 supervise/group/battle/challenge/post 五类 37 个端点 |
| 限流 20/min/user（AI） | ✅ 一致 | `config.py:87` RATE_LIMIT_AI_PER_MIN=20；Redis db4 可见 key |
| ai_dialog 落库（user+assistant 双行） | ✅ 一致 | psql 实测 2 rows after 1 chat |
| ai_times_left 递减落库 | ✅ 一致 | psql 实测 10→9→8 |
| python-multipart 已装（multipart 上传可用） | ✅ 一致 | curl -F 实测成功 |
| 36 表与 001_schema.sql 对齐 | ✅ 一致 | models/__init__.py 含 36 个 ORM 类 |
| food 1750 / food_alias 342 / sku_catalog 5 / ai_knowledge 50 | ✅ 一致 | load_seeds.py 导入确认 |

---

## 5. 未执行/待确认项

| 项 | 原因 | 替代验证 |
|---|------|---------|
| 真实 AI provider（ModelScope Qwen）端到端 | 无 MS_API_KEY | 代码走查确认 ModelScopeLLMClient/VisionClient 实现完整；ai_api.md 已实跑验证（文档记录） |
| 微信支付真机联调 | 无微信商户号/开发者工具 | mock pay 模式验证状态机 1→2→3 全链路；pay_sign HMAC 伪造仅供测试 |
| 微信内容安全（msgSecCheck） | 无 WECHAT_APPID/SECRET | 本地违规词 mock 已验证；代码走查确认有凭据时走真实接口 |
| 30 张识别测试图（DATA4） | 文件不存在 | plan.md 标注 P2 交付物；mock 模式已验证识别→匹配→落库链路 |
| pgvector 引入决策 | 首期 jsonb 占位 | 06 §2.3 已标注【假设】；当前 search_vec 用 tsvector 但中文分词失效（P1-1） |
| 前端 H5/小程序渲染 | 审查 Agent 不含前端验收 | 由主 Agent 在 H5 产物上复跑 agent-browser |

---

## 附录：关键命令与输出

### pytest
```
cd /data/ai-coach/backend && DATABASE_URL="postgresql+asyncpg://..." .venv/bin/python -m pytest -q
496 passed in 130.05s (0:02:10)
```

### ai_hello.py
```
.venv/bin/python scripts/ai_hello.py --task chat
[chat] client = MockLLMClient
[chat] reply: 建议先喝一杯水...（AI 输出仅供参考，具体请遵医嘱）

.venv/bin/python scripts/ai_hello.py --task vision
[vision] client = MockVisionClient
[vision] need_confirm = True
```

### 热量对拍
```
Total: 50 cases, 0 mismatches (tolerance 0.15 kcal)
```

### AI chat curl（节选）
```
curl -X POST http://127.0.0.1:8004/api/ai/chat -H "Authorization: Bearer $TOKEN" \
  -d '{"session_id":"s-1","message":"下午饿了能吃什么"}'
→ times_left:9, intent:hunger_rescue, references:[knowledge:16,27,28]
```

### RAG search_vec 失效证据
```sql
SELECT count(*) FROM ai_knowledge WHERE search_vec @@ plainto_tsquery('simple','热量');
→ 0  （全文检索无命中，每次降级 ILIKE）
```
