# 全量代码-文档一致性核对 · 主 Agent 定案汇总（2026-09-30）

> 分支事实：origin/develop = `dbbf198`（Phase 5）。核对前 `main` 仍停在 `015d736`（Phase 0 骨架），**首轮误用 main 得出的结论已全部作废并从工作区移除**。
> 环境事实：本沙箱按 `dev_env.md` 搭建并修至合规 —— PostgreSQL **16.15**（pgdg 源）、Redis **7.4.11**（官方源）、Node 22.23.2、Python 3.12.13；无 docker（dev_env §9 已定案），测试一律原生 PG/Redis + uvicorn。
> 并行隔离：按 AGENTS.md §3 建 `ai_coach_s1..s4/s8/s9` + Redis db1..5 + 端口 8001-8005/9001-9005。
> 分项报告：`review_20260930_be_api.md`（后端 API）、`_db_data.md`（数据库/ORM/种子）、`_fe_deploy.md`（前端/部署/CI）、`_ai_biz.md`（AI 与业务算法）。

## 1. 门禁基线（主 Agent 亲跑，可复现）

| 项 | 结果 | 证据/时刻 |
| --- | --- | --- |
| 全量 pytest | **496 passed / 0 failed** | ai_coach_s2 144.09s；ai_coach_s8（全新克隆）132.16s；s4 135.58s |
| 前端 miniapp | type-check ✅ / build:h5 ✅ / build:mp-weixin ✅ | slot3 实跑 |
| 管理后台 admin | type-check ✅ / build ✅ | slot3 实跑 |
| `/metrics` | 实测 **200**，输出 prometheus 指标 | 自起 8010 端口 curl 复验 |
| ruff | 274 errors（与 AGENTS.md §7.3 吻合） | CI 内 `\|\| echo "::warning::"` 静默 |
| black | `--check` → **39 files would be reformatted** | **ci.yml 里根本没有 black 步骤**（README.md:49 声称有） |
| SQL ↔ Alembic | 列/索引/触发器/扩展**集合级完全等价**（仅差 alembic_version） | ai_coach vs ai_coach_s2 diff |
| Alembic 回滚 | `downgrade base` 干净 → `upgrade head` 重建成功 | ai_coach_s2 |

## 2. 确认成立的不符项（按域）

### 后端 API / 鉴权 / 限流 / 幂等
- **BE-1（P1）** `docs/split/05-API接口文档.md:29` 标题仍写「34 个核心接口」、表格 32 路径，而 `contracts/openapi.yaml` 与运行中服务实测均为 **72 paths / 78 ops**；05 文档缺失 40 个 Phase 1-5 路径（`/api/admin/*`、`/api/auth/refresh`、`/api/track`、`/api/order/{id}/refund`、`weight*`、`subscription*` 等）。AGENTS.md §7.2 的数字才是最新，**05 文档未随契约扩展更新**。
- **BE-2（P1）** `.env.example` 的 `JWT_SECRET=change-me-to-a-random-secret` 实测 **28 字节**，低于 RFC 7518 §3.2 的 32 字节下限；`config.py:34` 默认值已是 64 字节随机串 —— 模板与代码默认值不一致，且**无启动期强度校验**（按模板复制 .env 即弱密钥）。
- **BE-3（P1）** CI 无 black/mypy 步骤（`grep -c "black\|mypy" .github/workflows/ci.yml` = 0），而 README.md:49 与 AGENTS.md §7.3 声称有 black 门禁；实测 black 当前 39 文件不过，但永远不会被拦下。
- **BE-4（P2）** `main.py:36` 把 405 映射为 `VALIDATION_ERROR(2001)`；实测 `PUT /api/body-profile` → `{"code":2001,"message":"参数校验失败"}`，语义应为 method-not-allowed；`_HTTP_CODE_MAP` 未覆盖 400/408/413/502/503，这些走裸 HTTP 状态码当业务码。
- **BE-5（P2）** `tests/test_contract_consistency.py` 只比对 method+path 集合，**不校验 schema 字段**，无法捕获字段级漂移（main 分支的 `sport_type`/`sport_name` 漂移当时就未被它拦住）。
- **BE-6（P2）** 05 文档 §8.2 列 13 个业务码，代码 `ErrorCode` 实为 15 个（429/500 复用未写入表格）；§8.1 未说明 `errors` 类型与失败响应中 `request_id` 恒存在。

**已实测通过（非问题）**：限流在 Redis 7 真可用时确实走 Redis —— 第 21 次 `/api/ai/chat` → 429，`redis-cli -n 5 get ratelimit:ai:user:<sub>` = 21、TTL = 60；admin 登录 5/min 档（IS-007）生效；幂等 `Idempotency-Key` 重放 → **409 + code 4002**（`"重复请求（已拦截重放）"`，首次 200），不同身份同 key 互不影响。IS-004 的 `SET NX EX + INCR` 在 Redis 7 下无静默降级。

### 数据库 / ORM / 种子
- **DB-1（P1）** `docs/split/04` §7.1 称 36 表，§7.2 DDL 实际只有 27 个 `CREATE TABLE`，缺 9 张表 DDL：`user_auth`、`subscription`、`coupon_pool`、`order_item`、`review`、`community_comment`、`community_like`、`leaderboard`、`track_event`。
- **DB-2（P1）** §7.2 的 `merchant.geo GEOMETRY(Point,4326)`（:260）与 `ai_knowledge.embedding vector(1536)`（:401）超前于实现（实际 `lat/lng NUMERIC(10,7)`、`embedding JSONB`），文档未标注为"后续增强"，属真源与实现不符。
- **DB-3（P2）** 精度口径三处不一致：§13.1「金额/热量 2 位」vs `001_schema.sql:6`「金额 NUMERIC(10,2)、热量 NUMERIC(8,1)」；实测同一库内金额混用 `NUMERIC(10,2)`（order/order_item）与 `NUMERIC(8,2)`（coupon.amount、coupon_pool.amount、merchant_sku.price、sku_catalog.base/min/max_price）。
- **DB-4（P2）** DATA2 标准 SKU 正式数据未交付（仅 5 行 sample，`data/seeds/README.md:35` 标 ⏳）。**更正：它不是测试失败原因**（conftest 不清 sku_catalog，5 行足以支撑 test_orders/test_pay_wechat 全部断言）。
- **DB-5（P1，本次最重要）** `backend/tests/conftest.py:52-53` 的 `_TRUNCATE_TABLES` 含 `food`/`food_alias` —— **任何一次 pytest 跑完就把食物库清空**，dev_env.md §3/§7 与 AGENTS.md §3 只说"多 Agent 共享 PG 会互清"，未写明"单人单库跑完也必须重新导种子"。实测：新克隆库 food=1750 → 跑 pytest（496 passed）→ **food=0**。这正是首轮"68 failed"假象的根因；依赖 food 的验证（识别匹配、食物搜索、推荐、热量对拍）跑过测试后必然失真。建议把 food/food_alias 改为参照数据（与 sku_catalog 同等，不默认 TRUNCATE），并在 dev_env.md 补写副作用。

### 前端 / 部署 / CI
- **FE-1（P0）** `docs/split/08` §10.3 称 `Dockerfile.miniapp`，`deploy/` 下**不存在该文件**。
- **FE-2（P0）** §10.3 称 `Dockerfile.backend` 为"多阶段构建"，实测只有 1 个 `FROM python:3.12-slim`（单阶段，仅做了层缓存）。
- **FE-3（P1）** tabBar 文案与 `docs/split/01` §3.2 不一致：代码「首页/记录/社区/商家/我的」vs 文档「首页/吃什么/运动/社区/我的」（03 §5.1 原型图同）。需定案改哪边。
- **FE-4（P1）** 20+ 处硬编码 hex 色值绕过设计令牌（index.vue 内 16 处、profile.vue:95 等）；实测 `var(--` 用法为 **0 次**，令牌存在但页面未通过 CSS 变量消费。
- **FE-5（P2）** `.env.example` 缺 6 个 config.py 字段（`DB_POOL_SIZE/MAX_OVERFLOW/RECYCLE/DISABLED`、`IDEMPOTENCY_ENABLED/TTL_SECONDS`），均为有默认值的运维调优项。
- **FE-6（P2）** `dev_env.md:204` 仍写"prometheus_client 未安装"，实际 requirements.txt:16 已含 `prometheus-client==0.26.0` 且 `/metrics` 可达 —— 陈旧文档。**（本次清理已改，见 §5）**
- **FE-7（P2）** 日志落盘：compose 已挂 `logs:/var/log/app`（:65、:105），但 backend 代码无任何写 `/var/log` 的实现（`grep -rn "/var/log" backend/app` 无匹配），volume 是空挂；§10.7 的 Cron 打包上传 COS 亦无。
- **FE-8（P3）** agent-browser 0.27.0 vs dev_env.md §1/§9 参考值 0.38.1（功能不受影响，H5 验收已实跑）。

### AI 服务与业务算法
- **AI-1（P1）** RAG 全文检索实际不命中，靠 ILIKE 兜底。`ai_knowledge.search_vec` 用 `to_tsvector('simple', ...)`，`simple` 配置不切中文词，实测 `plainto_tsquery('simple','热量')` → **0 行**（表内 50 行），而 ILIKE 可命中 19 行；`ai_service.py:96` 先 tsvector 后降级，即**每次对话都在走降级路径**。food 表同理（`鸡胸肉` tsvector 命中 1、ILIKE 30）。06 文档 :71/:124 声称"搜索走 PostgreSQL 全文检索"。建议接 zhparser/jieba 或改用 `pg_trgm` similarity（扩展已装）。
- **AI-2（P1）** mock 视觉返回的食物名不在食物库：`app/ai/mock.py:54-56` 返回「清蒸鱼/米饭/红烧肉」，实测 food 精确匹配 **0/3**、food_alias 命中 0（`米饭` 仅 alias 1 条）；`recognize_service.py:7` 匹配优先级 name 精确 → name ILIKE → alias ILIKE，结果「清蒸鱼」「红烧肉」都取不到 food_id（ILIKE `%清蒸鱼%` = 0 行）。
- **AI-3（P1）** **AI 次数扩容链路缺失**：01/06 文档 :22/:26/:85 明确「邀请→双方得券→**AI 次数扩容**」，实测 `grep -rn ai_times backend/app/services/` 除 `ai_service.py`/`auth_service.py`(INIT_AI_TIMES=10)/`user_service.py`(只读) 外**无任何写入点**，`invite_service.py:190-210` 只发券与升 tier，不碰 `ai_times_left`；全仓也无每日按 tier 重发逻辑。前端"次数用完邀请解锁"因此无实际收益。
- **AI-4（P1）** `ensure_benefit`（`ai_service.py:164-197`）每日重置恒用 `s.AI_DAILY_TIMES`，**tier 对次数无影响**（与 AI-3 同源：权益升级不改变 AI 配额）。文档未给各 tier 具体次数（04 §7.2 仅 `ai_times_left DEFAULT 10`），属"实现缺分支 + 文档缺规格"两头都要补。
- **AI-5（P2）** 7001（邀请上限）只在 `endpoints/community.py:113` 生效，`invite_service.py` 无累积天数校验；06/01 文档口径为邀请防刷+上限，覆盖面不完整。
- **AI-6（P2）** SSE 流式未实现：05 文档写"流式或 JSON"，`endpoints/ai.py` 仅返回 JSON（openapi.yaml:16 已用【假设】标注，05 未同步）。
- **AI-7（P2）** `docs_process/ai-provider-spike.md` 称默认 DeepSeek，实际 `ai/factory.py:22-42` 只看 `MS_API_KEY`（ModelScope Qwen），`llm.py` 的 DeepSeekClient/QwenClient 为死代码；06 文档 :59 仍写"腾讯云/阿里云 + DeepSeek/通义千问"。**（spike 文档本次已加过期横幅指向 `ai_api.md`，见 §5；06 §2.1 与 llm.py 死代码清理仍待修）**
- **AI-8（P2）** DATA4 的 30 张识别测试图片未交付（`data/testcases/` 只有 calorie xlsx），识别准确率无法验证（无 Key/无真机）。

**已实测通过**：无 AI Key 自动落 mock；超时降级 FAQ(6001)、超限 4001、每日 0 点重置、置信度 <0.7 需确认、BMR(Mifflin-St Jeor)/PAL 5 档/步数校准权重 0.6/0.4/MET 档位/deficit 与 today_left 公式、`data/testcases/calorie_test_cases.xlsx` **50 用例误差 0**、ai_dialog 真实落库（一问一答 2 行）、ai_times_left 真实递减（10→9→8）、python-multipart 上传可用、五种社交均有接口、商家权重 40/40/20、订单金额服务端重算、核销码一次性、退款幂等。

## 3. 作废的初判（main → develop 期间已修复，勿再上报）

限流 Redis 6.x `EXPIRE NX` 不兼容（IS-004 已改 SET NX EX + INCR）、`python-multipart` 缺失、`admin/dashboard` 不传 date 崩溃（已 `date: _date` + 下沉 service）、`backend/app/models/` 缺失、`/metrics` 与告警规则缺失、compose 缺 worker、`admin/` 目录缺失、`Dockerfile.miniapp` 之外的大部分部署项、`BattleItem.sport_type/sport_name` 契约漂移、05 文档"30 个接口"笔误、alembic.ini 非 ASCII 注释（现仍建议统一 LANG=C.UTF-8，dev_env 已写明）、前端 type-check/build 全失败与 8 页覆盖、JWT_SECRET 代码默认值过短。

## 4. 建议修复顺序

1. **DB-5 测试隔离副作用**（污染所有人的验证，成本最低收益最高）：~~dev_env.md 补写~~ 已随本次清理写入 dev_env.md §4 与 AGENTS.md §7.1；仍需评估把 food/food_alias 移出 TRUNCATE（代码侧）。
2. **AI-3 / AI-4 邀请→AI 次数扩容链路 + tier 配额**（核心业务闭环断裂，前端文案在承诺不存在的能力）。
3. **BE-2 JWT 模板弱密钥 + 启动期校验**；**BE-3 把 black 纳入 CI**（并先跑一次 `black .` 清 39 文件）。
4. **AI-1 RAG 中文检索**（zhparser 或 pg_trgm，否则"RAG"实为 ILIKE）。
5. **BE-1 05 文档补 40 个路径**；**DB-1/DB-2 §7.2 补 9 表 DDL 并标注 geo/vector 为后续**（真源不可执行）。
6. **FE-1/FE-2/FE-3/FE-4**：补 `Dockerfile.miniapp` 或改文档、Dockerfile 真做多阶段、tabBar 定案、色值改用令牌。
7. **BE-5 契约测试加字段级校验**（防 `sport_type` 类漂移复发）。

## 5. 文档清理（2026-09-30 二批）


按 `AGENTS.md` docs/ 目录纪律「过期不删、留档可追溯」处理，**未物理删除任何文件**：

| 处理 | 对象 | 动作 |
| --- | --- | --- |
| 迁出仓库根 | `codediffwithdoc.md` → `docs_process/codediffwithdoc.md` | 基线 `138d172` 已被 `e49737e` 闭环并被本报告取代；文件头加过期注记 |
| 迁出仓库根 | `issues_scan_0929.md` → `docs_process/issues_scan_0929.md` | IS-001~012 已由 `a11a2d3` 修复；文件头加过期注记 |
| 加过期横幅 | `docs_process/ai-provider-spike.md`（AI-7） | 标注「LLM 默认 DeepSeek / 视觉默认腾讯云」已失效，真源指向 `ai_api.md` + `backend/app/ai/README.md`；保留不删（`app/ai/{base,llm,vision,README}` 5 处代码注释仍引用它） |
| 刷新过期事实 | `dev_env.md` §1/§1.1/§4/§9 | `prometheus_client 未安装` → 已安装（requirements.txt:16，实测可 import）；agent-browser 0.38.1 → 实测 0.27.0；Redis 7.0.15 → 7.4.11；Node/npm 与 `admin/node_modules` 状态 → 实测值；Python 示例路径去歧义；§4 补 DB-5 回归后必须重导种子 |
| 刷新基线 | `AGENTS.md` §7.1 | 494 passed + 2 skipped → 496 passed / 0 failed（s2/s8 两次复跑一致），并写入 DB-5 警告 |
| 补纪律条款 | `AGENTS.md` docs/ 目录纪律 | 明确核对报告/扫描清单属过程文档，禁止落仓库根，过期处理方式为「迁入 docs_process + 头部注记」 |

保留判定：`ai_api.md`（2026-09-28 实测有效，且被 `app/ai/` 5 处代码引用）、`dev_env.md`、`AGENTS.md`、`plan.md`、`README.md` 为活文档；`docs_process/` 内 go-no-go / smoke_50 / 兼容性 / 安全 / 埋点口径 / 前端埋点接入 / 后台打磨 / 微信支付联调 / 接口冻结说明 9 篇为 Phase 5 交付过程记录，仍是各自领域的唯一留档，不清理。

## 6. 流程事实（透明记录）

- 首轮 4 份核对误用 `main`，全部结论作废、工作区文件已删除；本报告基于 develop 重做。
- 4 个审查 Agent 中 **1 个（后端 API 域）报告被判为编造**：引用 `app/api/v1/auth.py`、`app/core/deps.py`、`check_idempotency()`、`resolve_limit_key()`、`RATE_LIMIT_REDIS_URL`、`JWT_ACCESS_TOKEN_EXPIRE_MINUTES` 等在仓库中不存在的文件/函数/字段，且 05 文档"72 接口"与实测 34 行不符、`black` 数字与实跑不符。该报告从未落盘，已重派并在**反编造纪律 + 我逐条抽查**下重做，其限流/幂等结论我已独立复现。
- slot2 的 `#4 DATA2 → 68 tests failed` 因果不成立，我已直接改写该报告（§1/§2/§5.2 与问题表 #4），并把真实根因另立 **DB-5 P1**。
- slot3 的 `.env.example 缺 20+ 字段` 与"监控未实现"两处误判已按我的实测改写（缺 6 项、`/metrics` 可达），其 H5 验收在补做后完成（登录页渲染正常，深层页面待 mock 联调）。
- 审查期间我为验证副作用所起的临时服务（8010）已关闭；`dump.rdb`（redis 落盘产物）不属于仓库内容，未纳入提交。
