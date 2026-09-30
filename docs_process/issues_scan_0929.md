# issues_scan_0929.md — develop 分支 Phase 0/1/2/3 扫描问题清单

> ⚠️ **已过期归档（2026-09-30）**：本清单 IS-001 ~ IS-012 已全部由 `a11a2d3` 修复闭环，文中「当次实测」环境数值（PG/Redis/Node 版本、端口、库名）已失效。最新一期核对见 `docs_process/review_20260930_summary.md`，环境真源见仓库根 `dev_env.md`。本文仅留档，按 `AGENTS.md` docs/ 目录纪律由仓库根迁至 `docs_process/`。

**扫描日期**：2026-09-29
**被测分支**：`develop` @ `a2708b3`
**扫描方式**：按 `dev_env.md` 配置环境后，4 个测试子代理并行验收 Phase 0/1/2/3（各自独立 DB / Redis db / 端口，遵守 `AGENTS.md §3` 隔离契约），再由 2 个独立核验子代理逐条复现核验。网页部分统一用 `agent-browser`（H5 + 管理后台）。

**核验原则**：所有条目均以「亲手复现成功」为准，不采信仅读代码的结论。原始报告主张中有 **4 条经复现判定为误报**，已单列于 §4，不计入问题清单。

---

## 0. 环境事实（本次实测，与 dev_env.md 的差异）

| 组件 | dev_env.md 要求 | 本次实测 | 说明 |
| --- | --- | --- | --- |
| Python | ≥3.12 | 3.12.13 | ✓ |
| Node / npm | ≥20 / ≥10 | 22.23.2 / 10.9.8 | ✓ |
| PostgreSQL | 16.x | 16.15 | ✓（沙箱原为 14，已装 PGDG 升级） |
| Redis | 7.x | **6.0.16** | ✗ 沙箱 apt 源最高 6.0.16；触发 IS-004 |
| agent-browser | 最新 | 0.27.0 | ✓（走系统 Chrome 152） |
| Docker | 需要 | **无** | compose 起服务无法实跑，仅静态校验 |
| 微信开发者工具 | 需要 | **无** | mp-weixin 真机验收无法实跑 |
| AI API Key | 需要 | **无** | AI 走仓库内 mock 降级（设计预期） |

**基线实跑（主 Agent 串行干净环境）**：后端 `pytest -q` → **198 passed, 338 warnings**；`miniapp` `type-check` 0 错误；`build:mp-weixin` 与 `build:h5` 均通过；真后端 `/openapi.json` 48 路径 == `contracts/openapi.yaml` 48 路径；`001_schema.sql` 与 Alembic 0001 约束级比对 **156 约束 / 89 索引 / 327 列 100% 一致**。

---

## 1. 问题汇总

| 级别 | 数量 | 编号 |
| --- | --- | --- |
| **P0 阻断** | 1 | IS-001 |
| **P1 真实缺陷** | 2 | IS-002, IS-003 |
| **P2 一般** | 5 | IS-004 ~ IS-008 |
| **P3 轻微** | 4 | IS-009 ~ IS-012 |
| 误报（已剔除） | 4 | §4 |

**总体判定**：Phase 0 / 1 / 2 / 3 的功能性退出标准**基本达成**（热量引擎误差 0、交易闭环与并发安全、AI 配额与降级、契约五方一致均复现通过），但存在 **1 个 P0 支付安全问题**，按 `AGENTS.md §5.3` 属阻断级，**建议在任何生产部署前优先修复 IS-001**。

---

## 2. 问题清单

### IS-001 · P0 · 产品缺陷（安全）

**标题**：`PAY_MOCK_MODE` 默认开启且无生产守卫，默认配置下可零支付完成订单并拿到核销码

**位置**：`backend/app/core/config.py:41`、`backend/app/services/order_service.py:295`、`backend/app/api/v1/endpoints/orders.py:73`

**问题**
`PAY_MOCK_MODE: bool = True` 是**代码级默认值**，为真时 `POST /api/order/{id}/pay` 直接调用 `_mark_paid()` 推进为已支付，**不经过微信支付、不经过 notify 回调、不做验签**。同时：
- `.env.example` **完全没有** `PAY_MOCK_MODE` 这一项（Phase 0 核验统计的「13 个 config 有、.env.example 无」字段之一）；
- `deploy/docker-compose.yml` 的 api 服务**不注入**该变量，且 `env_file: ../.env` 标记为 `required: false`（.env 不存在时照常启动、全部走代码默认值）；
- 代码中**没有任何** `ENV` / `DEBUG` 守卫或启动告警来阻止生产环境使用默认值。

**复现（真实执行）**
```bash
B=http://127.0.0.1:8000/api   # 默认配置启动，未设 PAY_MOCK_MODE=false
T=$(curl -sS -X POST $B/auth/login -H 'Content-Type: application/json' \
     -d '{"code":"paymock_probe3"}' | jq -r .data.token)
curl -sS -X POST $B/body-profile -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
     -d '{"gender":1,"height_cm":175,"current_weight":70,"birth_year":1995,"target_type":1,"activity_level":3}'
OID=$(curl -sS -X POST $B/order -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
     -d '{"merchant_id":9901,"items":[{"sku_id":99011,"qty":1}]}' | jq -r .data.order_id)
curl -sS -X POST $B/order/$OID/pay -H "Authorization: Bearer $T"
```
落库核对：
```
支付前: id=3 | status=1 | pay_amount=25.00 | pay_at=null | redeem_code=null
支付后: id=3 | status=2 | pay_amount=25.00 | paid=t      | redeem_code=RDW2MKC4NTCG
```

**实际结果**：未支付订单调用一次 `/pay` 即变 `status=2`（已支付）、`pay_at` 写入、**核销码下发**，全程无真实支付。
**期望结果**：默认配置不得允许零支付完成交易；mock 支付必须是显式开启的演示开关。

**建议修法**（任一即可，建议组合 1+2+3）
1. 默认值改为 `PAY_MOCK_MODE: bool = False`，演示环境显式开启；
2. 加启动守卫：`ENV=prod` 且 `PAY_MOCK_MODE=True` 时直接抛错拒绝启动；
3. 把 `PAY_MOCK_MODE` 写入 `.env.example` 并注明「生产必须 false」，同时在 `docker-compose.yml` api 服务显式注入 `PAY_MOCK_MODE: ${PAY_MOCK_MODE:-false}`；
4. 补一条回归测试断言生产默认值不为 true。

---

### IS-002 · P1 · 产品缺陷

**标题**：AI 客户端存在两套工厂，`.env.example` 教的配置方式对生产服务完全无效

**位置**：`backend/app/ai/__init__.py:28`（旧）vs `backend/app/ai/factory.py:22`（新）

**问题**
两个同名 `get_llm_client()` 走完全不同的配置来源：

| | 读取的配置 | 谁在用 |
| --- | --- | --- |
| `ai/__init__.py:28` | `AI_LLM_PROVIDER`（默认 `deepseek`）、`AI_LLM_API_KEY`、`AI_VISION_PROVIDER`（默认 `tencent`） | **仅** `scripts/ai_hello.py` |
| `ai/factory.py:22` | **只看** `MS_API_KEY`（ModelScope Qwen） | 全部 service：`ai_service`、`recognize_service`、`recommend_service` |

后果：按 `.env.example`（`AI_LLM_PROVIDER=deepseek` + `AI_LLM_API_KEY=...`）配置真实 Key 后，**线上服务仍然返回 Mock 结果**，且因 `factory.py` 无 Key 时静默落 Mock、不告警，故障表现为「AI 一直答非所问的 FAQ」而非报错。同时 `app/ai/llm.py`（DeepSeek/Qwen）与 `app/ai/vision.py`（腾讯云）在生产路径上成为**死代码**，但 `app/ai/README.md` 仍写「默认 DeepSeek + 腾讯云」，与实际选型（`ai_api.md` 的 ModelScope Qwen3.8-Flash-Next）矛盾。

**实际结果**：配 `AI_LLM_PROVIDER=deepseek` + `AI_LLM_API_KEY` → 服务仍走 `MockLLMClient`。
**期望结果**：配置生效，或文档/契约明确唯一支持的 provider。

**建议修法**：删除 `ai/__init__.py` 的工厂函数（或标记 deprecated 并让 `ai_hello.py` 改用 `factory`），一并清理 `llm.py` / `vision.py` 死代码或将其接入 `factory.py`；同步更新 `app/ai/README.md` 与 `.env.example` 的 `AI_*` 段。

---

### IS-003 · P1 · 产品缺陷（需求冲突）

**标题**：AI 超时上限 20s，与「AI 对话 P95 < 3s」的硬性需求冲突，注释却自称已对齐

**位置**：`backend/app/core/config.py:67`

**问题**
```python
MS_TIMEOUT: float = 20.0  # 对齐 plan.md：AI P95 < 3s，超时降级预置 FAQ
```
`plan.md:175` 与 `plan.md:253`、`docs/split/06-AI服务.md:198` 均要求 **AI 对话 P95 < 3s**。实际 `ai_service.py:244` 用 `timeout=s.MS_TIMEOUT` 即 **20s** 作为 `asyncio.wait_for` 上限，是需求的 **6.7 倍**。注释声称「对齐 plan.md」但取值与之矛盾，属误导性注释。此外 `admin` 侧 axios 超时 10s（`admin/src/api/client.ts:9`），20s 的 AI 调用会先被前端断开。

**实际结果**：AI 慢时最长阻塞 20s 才降级 FAQ。
**期望结果**：超时阈值与 P95<3s 一致（建议 3s 或留少量余量至 5s），或明确记录该偏差及理由。

**建议修法**：将 `MS_TIMEOUT` 调整为符合 P95 目标的值；修正注释；若因真实 LLM 首字延迟必须 >3s，则应回改需求文档并在 Phase 5 性能测试（F5）中显式跟踪。

---

### IS-004 · P2 · 产品缺陷（可移植性 + 日志误导）

**标题**：限流使用 Redis 7.0+ 才支持的 `EXPIRE ... NX`，在 Redis 6.x 下被宽泛 except 吞掉并误报为「Redis 不可用」

**位置**：`backend/app/core/rate_limit.py:38`（异常捕获在 `:41`）、`backend/app/db/redis.py:36`

**问题**
`pipe.expire(redis_key, window, nx=True)` 需要 Redis ≥7.0。Redis 6.x 下 pipeline 抛 `ResponseError: wrong number of arguments for 'expire' command`，该异常被 `except Exception` 捕获后记录为「限流 Redis 不可用，降级进程内字典」——**归因错误**。

**复现（真实执行）**
```bash
cd backend && REDIS_URL="redis://127.0.0.1:6379/5" python -c "
import asyncio; from app.db.redis import get_redis
async def m():
    r = await get_redis(); print('client ok:', r is not None)      # -> True（连接正常）
    async with r.pipeline(transaction=True) as p:
        p.incr('probe:x'); p.expire('probe:x', 60, nx=True); await p.execute()
asyncio.run(m())
"
# ResponseError: Command # 2 (EXPIRE probe:x 60 NX) of pipeline caused error:
#   ("wrong number of arguments for 'expire' command",)
```
即：Redis 连接完全正常，但 `check_rate_limit()` 每次调用都走内存兜底。

**影响**：Redis 6.x 环境下限流静默退化为**单进程内存计数**，多实例部署时限流实际失效；日志把「版本不兼容」指向「Redis 挂了」，会误导运维排查方向。

**定级说明**：`deploy/docker-compose.yml:30` 已锁 `redis:7-alpine`、CI 用 `redis:7`，故正常部署路径不受影响 → 定 P2 而非 P1。但代码对版本要求**零校验**，任何非 compose 的部署（云厂商托管 Redis 6、自建旧版）都会静默中招。

**建议修法**：① 启动时读 `INFO server` 校验 Redis ≥7.0，不满足则打印明确错误或告警；② 或降级兼容（6.x 用 `SET key val NX EX ttl` + `INCR`）；③ 收窄 `except` 范围，区分「连接不可用」与「命令不兼容」两类日志。

---

### IS-005 · P2 · 产品缺陷（契约与实现语义冲突）

**标题**：契约允许 `birth_year` 最小 1900，但热量引擎对 age>120 静默回退 30，用户不知情

**位置**：`backend/app/services/calorie.py:58-66`、`contracts/openapi.yaml:1968`

**问题**
契约声明 `birth_year: { type: integer, minimum: 1900, maximum: 9999 }`，但引擎 `age_from_birth_year()` 在 `age <= 0 or age > 120` 时返回 `DEFAULT_AGE`（30），**不报错、不提示**。于是 1900–1905 这些契约合法值全部得到同一个 age=30 的 BMR。

**复现（真实执行）**
```
birth_year=1899 -> code 2001（契约拒绝）✓
birth_year=1900 -> code 0, bmr 1648.8   ← 实际 age≈126，被回退为 30
birth_year=1905 -> code 0, bmr 1648.8   ← 与 1900 完全相同，证明均被回退
birth_year=1910 -> code 0, bmr 1218.8   ← 正常计算（age=116）
```

**实际结果**：契约合法输入被静默丢弃，且不同输入返回相同结果，无任何提示。
**期望结果**：契约 `minimum` 与引擎有效年龄范围一致（如 `minimum: 1906`），超出即 2001；或响应中回显实际采用的 age 并提示已回退。

**建议修法**：收紧契约 `birth_year` 下限至引擎支持范围（并同步两份 TS 副本 + pydantic），或在 `body-profile` 响应中返回 `age_used` + 回退标记。

---

### IS-006 · P2 · 产品缺陷（配置文档）

**标题**：`.env.example` 缺失 13 个运行时配置字段

**位置**：`.env.example` vs `backend/app/core/config.py`

**问题**
`config.py` 有、`.env.example` 无的 13 个字段：`API_PREFIX`、`APP_NAME`、`CORS_ALLOW_ORIGINS`、`DEBUG`、`ENV`、`PAY_MOCK_MODE`、`RATE_LIMIT_ENABLED`、`RATE_LIMIT_WINDOW_SECONDS`、`RATE_LIMIT_GLOBAL_PER_MIN`、`RATE_LIMIT_AI_PER_MIN`、`RATE_LIMIT_AUTH_PER_MIN`、`AI_CONFIDENCE_THRESHOLD`、`AI_DAILY_TIMES`。
（反向的 8 个 `POSTGRES_*` / `REDIS_HOST` / `REDIS_PORT` / `NGINX_PORT` 经核实为 docker-compose 专用变量，compose 确实引用，属合理设计，不计问题。）

**影响**：运维无法从模板得知这些可配项；其中 `PAY_MOCK_MODE` 的缺失已升级为 IS-001 的组成部分。`RATE_LIMIT_*` 与 `AI_*` 有安全默认值，风险较低。

**建议修法**：将 13 个字段补入 `.env.example` 并分组注释（应用 / 限流 / AI），安全相关项标注生产建议值。

---

### IS-007 · P2 · 产品缺陷（安全）

**标题**：`/api/admin/login` 未纳入 auth 严格限流档，且无账号锁定

**位置**：`backend/app/core/rate_limit.py` 的 `resolve_limit()`、`backend/app/api/v1/endpoints/admin.py:75-84`

**问题**
`resolve_limit()` 只对 `/api/auth/*` 使用 `RATE_LIMIT_AUTH_PER_MIN`（10/min/IP），`/api/admin/login` 落到全局档 `RATE_LIMIT_GLOBAL_PER_MIN`（100/min/IP）。管理员口令爆破可用速率是 C 端登录的 **10 倍**，且无失败计数 / 账号锁定 / IP 惩罚。

**复现（真实执行）**：连续 25 次错误口令 → 全部 `401`，无限流；约 76 次后才触发全局 429。
（注：Phase 3 原报告称「完全无 rate limit」不准确，故本条描述已修正为「未纳入严格档」。）

**建议修法**：把 `/api/admin/login` 纳入 auth 严格档或单独的更严档（如 5/min/IP），并增加按用户名的失败锁定（Redis 计数，5 次失败锁 15 分钟）。

---

### IS-008 · P2 · 待办（计划内未交付）

**标题**：`/api/admin/dashboard` 返回硬编码占位数据

**位置**：`backend/app/api/v1/endpoints/admin.py:246-266`（`user_count=1200` 等字面量在 `:257`）

**问题**：函数上方注释已写明「Phase 1 stub 保留」，即**计划内未交付**，而非实现错误。实测 DB 有 21 用户 / 10 订单，接口仍返回 1200 / 120 / 3360.0。管理后台 ADM3「数据看板」因此无真实数据可用。

**定级说明**：经核验由 P1 降为 P2 —— 属已知 stub，不计为缺陷；但 `AGENTS.md §5` 门禁要求波次交付可验收，建议显式登记为待办以免长期无人认领。

**建议修法**：改为真实聚合查询（`count(*)` + 按日聚合），或在接口响应中加 `stub: true` 标记并在前端明示「演示数据」。

---

### IS-009 · P3 · 产品缺陷（Mock 覆盖）

**标题**：Mock Server 缺 10 个 admin 接口方法（9 个路径）

**位置**：`contracts/mock/routes.mjs`

**问题**：契约 52 methods / Mock 42，缺的 10 个全为 `/api/admin/*`：`login`、`merchants`、`merchants/{id}/audit`、`merchant-skus`、`merchant-skus/{id}/status`、`coupon-pools`(GET/POST)、`coupon-pools/{id}/grant`、`orders`、`sku-catalog`。
（注：Phase 3 原报告称「FE 管理后台无法对 Mock 开发」不成立 —— `admin/vite.config.ts` 的 proxy 将 `/api` 直连真后端 8000，admin FE 本就不依赖 Mock，故由 P1 降为 P3。）

**建议修法**：补齐 canned data，或在 `contracts/mock/README` 注明 admin 域不走 Mock 的约定。

---

### IS-010 · P3 · 产品缺陷（编码）

**标题**：`backend/alembic.ini` 注释含全角标点，`LC_ALL=C` 下 alembic 崩溃

**复现**：`LC_ALL=C python -m alembic current` → `UnicodeDecodeError: 'ascii' codec can't decode byte 0xef in position 16`；`LC_ALL=C.UTF-8` 正常。文件无 BOM，含 36 个非 ASCII 字节（U+FF1A 全角冒号等）。CI 不跑 alembic，仅影响手动执行。
**建议修法**：注释中的全角 `：，` 替换为半角。

---

### IS-011 · P3 · 契约缺口

**标题**：`merchant/list` 与 `merchant/{id}` 的经纬度未声明范围约束，实现亦不校验

**位置**：`contracts/openapi.yaml`（lat/lng 仅 `type: number, format: double`）、`backend/app/api/v1/endpoints/merchants.py:26-27`、`:45`

**复现**：`lat=999` / `lat=91` / `lat=-91` / `lng=181` 均返回 `200` + 空列表（优雅降级，未见错误距离或异常）。
**定级说明**：属**契约缺口**而非「实现违反契约」，且危害有限（未产生错误排序），故由 P1 降为 P3。
**建议修法**：契约补 `minimum/maximum`（lat ∈ [-90,90]、lng ∈ [-180,180]），实现侧 `Query(ge=-90, le=90)`，两份 TS 副本同步。

---

### IS-012 · P3 · 设计选择（建议文档化）

**标题**：下单校验库存但不预占/不扣减，可创建超出库存的待支付订单

**位置**：`backend/app/services/order_service.py:172`（校验存在）、`_mark_paid()`（扣减在此）

**复现**：`stock=3` 时单发 `qty=5` → `2001 库存不足`（校验生效）；10 并发各 `qty=1` → 10 单全部创建成功、`stock` 仍为 3；随后 10 并发支付 → 3 成功 7 失败、`stock=0`（**无超卖**）。
**定级说明**：Phase 3 原报告表述为「下单时不检查库存」不准确 —— 校验确实存在。实际是「不预占」，配合 15 分钟超时 + 支付时 `FOR UPDATE` 扣减，**不产生资损**，属可接受设计选择 → P3。
**建议修法**：在 `docs/split/05-API接口文档.md` 明确该语义；如需改善用户体验可引入下单预占 + 超时释放。

---

## 3. 各 Phase 退出标准判定（复现核验后）

| Phase | 判定 | 关键依据 |
| --- | --- | --- |
| **Phase 0** | 基本达成 | `001_schema.sql` 与 Alembic 0001 约束级 **100% 一致**（36 表 / 327 列 / 156 约束 / 89 索引，独立建库比对）；契约 48 路径五方一致；两份 TS 副本 MD5 一致；H5 登录→首页、5 Tab + FAB、路由守卫、限流 429、request_id 全链路均实测通过。遗留 IS-009/IS-010 |
| **Phase 1 / M1** | **达成** | 热量引擎 **17 组手算 + DATA4 50 行用例误差 0**（核验 Agent 独立复现 50/50）；写后同步 <1s；步数 0 走 PAL、>0 走 0.6/0.4 加权；越权返 3001；食物库 1750 + 别名 342 无孤儿。遗留 IS-005 |
| **Phase 2 / M2** | 3/4 达成，1 项环境限制 | 配额扣减 10→0 后返 4001；**10 并发 / 配额 5 恰好 5 成功**（FOR UPDATE 有效）；限流第 21 次 429；超时降级 6001 + FAQ；H5 实测配额耗尽后输入框 disabled 且无法发送；RAG 确实检索 `ai_knowledge`；prompt 注入面安全（用户输入在 user role）。识别准确率 ≥85% **因无 AI Key 未执行**。遗留 IS-002、IS-003 |
| **Phase 3 / M3** | 达成 | 下单→支付→核销全链路；重复核销返 5004；越界价 422/2001（18.99 / 32.01 均拒）；服务端重算金额（前端传 0.01 被忽略）；**20 并发领 5 券池 → 恰好 5 成功**；10 并发支付 stock=3 → 3 成功无超卖；越权与回调验签（含篡改金额、错签名）全部拦截。遗留 IS-007、IS-008 |

---

## 4. 误报记录（已复现推翻，不计入问题清单）

记录于此以便追溯，避免后续扫描重复上报：

| 原始主张 | 来源 | 推翻依据 |
| --- | --- | --- |
| 「Redis 连接失败导致限流降级」 | phase0 #5 | Redis 直连 `ping` 正常、`get_redis()` 正常返回客户端；真因是 `EXPIRE NX` 语法不兼容（→ 已改写为 IS-004） |
| 「`steps/sync` 步数无上限校验，100000 被接受」 | phase1 P1-002 | 契约 `StepsSyncIn.steps.maximum: 200000` 存在且生效；实测 200001 / 999999 / -5 均正确返 `2001`。100000 本在契约范围内 |
| 「重复订阅使 `subscribe_count` 递增，不幂等」 | phase1 P1-003 | 契约「幂等」指 `(user_id, template_type)` 不产生重复行；实测 3 次订阅仍仅 1 行，`count` 是累计统计（`notification_service.py:87` 明确设计） |
| 「`order` 表缺 `pay_amount` CHECK 约束」 | phase3 P3-006 | `001_schema.sql:454` 与 `pg_constraint` 均有 `order_check: CHECK (pay_amount = total_amount - discount_amount)`，Alembic 侧同样存在（见 §3 Phase 0 比对） |

---

## 5. 环境限制导致的未执行项（非产品缺陷）

| 项 | 影响 | 说明 |
| --- | --- | --- |
| 无 Docker | P0-g「一键起全套」未实跑 | 已做静态校验：compose YAML 合法、4 服务与依赖链正确、`redis:7-alpine` / `postgres:16-alpine` 版本与 dev_env.md 一致 |
| 无微信开发者工具 | mp-weixin 真机/模拟器未验收 | 仅验证 `build:mp-weixin` 产物生成成功；H5 与小程序的渲染等价性未证明 |
| 无 AI API Key | 识别准确率 ≥85%（30 图）、真实 LLM 回答质量未测 | 降级路径已完整验证；`dev_env.md` 与 `ai_api.md` 的 Key 配置项待补真实凭据后回归 |
| Redis 6.0.16（要求 7.x） | 限流走内存兜底 | 触发 IS-004；生产 compose/CI 为 Redis 7，不受影响 |

---

## 6. 修复优先级建议

1. **立即**：IS-001（P0，支付安全，改默认值 + 启动守卫 + 补 `.env.example`）
2. **M4 前**：IS-002、IS-003（P1，AI 配置生效性与超时需求）
3. **排期内**：IS-004 ~ IS-008（P2）
4. **择机**：IS-009 ~ IS-012（P3）

---

**附：本次扫描产物**（未入库，仅存档于沙箱 `/data/reports/`）
`phase0.md`、`phase1.md`、`phase2.md`、`phase3.md`、`verify-phase3.md`、`verify-phase01.md`
