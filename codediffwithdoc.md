# codediffwithdoc — 文档 vs 代码 一致性全量核对报告

> **核对对象**：`develop` 分支 `HEAD = 138d172`（Phase 0 ~ Phase 5 全部已合入）
> **核对时间**：2026-09-29 UTC（两份审查分别于 18:27–18:56 / 19:10–19:53 实跑）
> **方法**：按 `AGENTS.md §5` 门禁流程 —— 两个**同配置、互不相通**的只读审查 Agent（slot 1 / slot 2，各自独立数据库 `ai_coach_a1` / `ai_coach_a2`）并行全量复核 → 主 Agent 在干净环境对争议项**复跑定案** → 汇总去重。
> **性质**：本报告为**只读审查结论**，未修改任何源码/测试/契约/文档。
> **总体结论**：`FAIL`（无 P0，**10 条 P1**）。功能主干（485 用例、双端构建、78 ops 契约双向对齐、热量引擎数值、支付退款闭环、埋点口径）全部与文档相符；**不一致集中在「邀请裂变」一条业务链路 + 若干契约漂移 + 文档自身数字过期**。

---

## 1. 实测环境事实（当次实跑，勿引用旧值）

| 项 | 实测值 |
| --- | --- |
| Python | `/workspace/.venv312/bin/python` → 3.12.3 |
| PostgreSQL | 16.15，`127.0.0.1:5432`，`postgres/postgres` |
| Redis | 7.0.15，`127.0.0.1:6379` |
| 数据库 | `ai_coach`（主）/ `ai_coach_a1` / `ai_coach_a2`，各 36 业务表，`alembic current = 0002 (head)` |
| 种子 | `food=1750`、`food_alias=342`、`sku_catalog=5`、`ai_knowledge=50` |
| Node / npm | v22.13.1 / 11.9.0 |
| 契约 | `contracts/openapi.yaml` = **72 路径 / 78 ops** |

## 2. 门禁实跑结果（两份审查各自独立跑，结论一致）

| 项 | 结果 |
| --- | --- |
| 全量 pytest（a1 / a2） | **485 passed / 0 failed / 0 skipped**（约 228s），两份一致 |
| `ruff check` | 275 errors（B008 166、UP045 94、E501 7 等）—— B008 属既有风格，不计 P0 |
| 前端 `type-check` | **0 错误** |
| `build:mp-weixin` / `build:h5` | 均 **Build complete** |
| 契约 ↔ 实现路由集合 | **双向全等**（spec-only = ∅，impl-only = ∅） |
| 契约 ↔ pydantic 响应字段 | 78 ops **差异 0** |
| TS 双副本 `contracts/ts/api.d.ts` ↔ `miniapp/src/types/api.d.ts` | **逐字一致**（各 793 行） |
| DB ↔ ORM 列比对（35 表） | **列差异 0** |
| 越权抽查 | 用户 B 读/改/删 A 的 meal → 全部 404/3001，**未越权** |
| SQL 注入抽查（`food/search`、`merchant/list`） | 无注入 |
| 限流 | 全局 100/min/IP 生效（120 连打 → 102×429） |
| 幂等重放 | 同 `Idempotency-Key` → 409 + `code=4002` + `idempotency_replayed:true` |
| `admin` 后台构建 | **未执行**（`admin/node_modules` 不存在，`vue-tsc: not found`） |

## 3. 已核对**相符**的部分（证明覆盖度，非漏检）

- 热量引擎：Mifflin-St Jeor（男 +5 / 女 −161）、PAL 1.2~2.0、MET 档 2.5/4.3/8.0、NEAT 0.6/0.4 加权、TEF 10%、`today_left = budget − intake + eat − tef`，与 `docs/split/04 §6.3.1` 逐项一致（手算对拍通过）。
- 商家权重 40/40/20 + haversine + 同分按距离/id，与 `04 §6.3.4` 一致。
- AI 配额 10 次/日、限流 100/20/10 每分钟，与 `04 §6.3.6`、`06 §3` 一致。
- 埋点：`TrackIn` 1~50 条、event 1~64 字符、platform 1-3、匿名可选鉴权，与 `docs/埋点与指标口径.md §1` 一致。
- `/metrics` 指标、`deploy/` 产物（compose 7 服务、nginx 100r/s、prometheus 4 条告警），与 `docs/split/08 §10.3/10.4/10.7` 一致。
- 退款闭环「2→5 幂等 + `FOR UPDATE` + 不回滚库存/券」，与 `docs/微信支付联调手册.md §5` 一致。
- 错误码 `0/1001/1002/2001/3001/4001/4002/5001~5004/6001/7001` 全部有实际抛出点，HTTP 映射正确。
- 测试质量（AGENTS §2.9）：无重复用例、无断言框架自身行为、边界值已用 `parametrize` 合并，**无问题**。

---

## 4. 不一致清单（两份审查合并去重）

> **✔** = 两个审查 Agent **独立同时报出**（交叉印证，可信度最高）；单标记 = 仅一份报出，主 Agent 已复跑定案。
> 级别：`P0` 阻断 / `P1` 真实缺陷或业务规则与文档不符 / `P2` 轻微或文档自相矛盾。

### 4.1 P1 —— 业务规则与文档不符（集中在邀请裂变链路）

| 编号 | 印证 | 文件:行号 | 文档依据 | 问题 | 建议修法 |
| --- | --- | --- | --- | --- | --- |
| CD-01 | ✔ | `backend/app/api/v1/endpoints/community.py:57` | `docs/split/01:100`「累计达 **2/5/10 人**解锁 90天/180天/**永久**」 | `MAX_INVITEES = 5`，10 人档（永久权益）**永不可达**，7001 提前触发 | 改 `MAX_INVITEES = 10`，或文档改阈值为 2/5 两档 |
| CD-02 | ✔ | `backend/app/api/v1/endpoints/community.py:106`（`status=1` 直接置有效） | `docs/split/01:100`「被邀请人需**完成 1 次拍照记录**才算有效；同设备只算 1 次」；`split/10:39` | 绑定即有效，**无拍照校验、无设备指纹去重**；进度统计不过滤 status → K 因子可刷 | 绑定置 `status=0`，首条 `meal_record` 后转 1；加 `device_id` 去重；统计加 `status=1` 过滤 |
| CD-03 | ✔ | 全仓（**`.tier =` 赋值 0 命中**，主 Agent 复跑确认） | `docs/split/01:122`「邀请 2 人后权益变更为**进阶版 90 天**」、`split/10:40` | **无任何 tier/权益发放代码**，`user_benefit.tier` 恒为 0，AI 次数恒 10，验收条款不可达 | 达标处更新 `user_benefit.tier/valid_to/ai_times_left`，或补次日批量发放任务 |
| CD-04 | ✔ | `community.py:129` | `01:100`「2/5/10 → 90天/180天/永久」 | `next_tier.reward` **恒为字面量**「进阶版90天」，count≥5/10 时文案错误 | 按 `next_need`(2/5/10) 映射 reward |
| CD-05 | ✔ | `miniapp/src/pages.json:8`；`miniapp/src/pages/`（**无 invite 目录**，主 Agent 复跑确认） | `docs/split/01:156`「21 邀请裂变 `/pages/invite`」、`01:67` P0 清单、`03:527`「我的·[立即邀请]」 | 小程序**无邀请页、无任何 invite API 调用**，后端 `/api/invite*` 无消费方 | 新增 `pages/invite`（进度/海报/规则/分享）挂入 `pages.json`，「我的」加入口 |
| CD-06 | 单(A) | `community.py:106` | `01:100`「**双方各得券**」、`04:76` | 绑定只写 `Invite` 记录，**不向双方发券**（全仓 `Coupon(` 仅 `admin_service.py:479` 一处） | 绑定成功后从 `coupon_pool` 向双方各发 1 张 |
| CD-07 | 单(B) | `contracts/openapi.yaml:1934 / 2002 / 2098` | OpenAPI 规范；`AGENTS.md §4.3` 契约纪律 | 3 个 admin 路径含 `{id}` 却**零 parameters 声明**（其余 69 路径均有）→ 生成的 TS/客户端拿不到该参数 | 补 `parameters: [{name: id, in: path, required: true, schema: {type: integer}}]`，同步 TS 与 mock |
| CD-08 | 单(B) | `backend/app/api/v1/endpoints/coupons.py:34`（主 Agent 复跑确认） | `AGENTS.md §4.3`「禁止实现单方面漂移」 | `/api/coupon/list` 实现多出 `scope` 查询参数（代码注释自称「additive，契约向后兼容」），**契约未声明** | 契约补 `scope` 并同步 TS/mock，或实现移除 |
| CD-09 | 单(B) | `backend/app/services/order_service.py:175, 277`（主 Agent 复跑确认，全仓 `QUOTA_EXCEEDED` 仅用于 AI 配额与券池） | `docs/split/05:208`「库存不足返回 **4001**」 | 库存不足实际抛 `2001`（HTTP 422），与文档承诺的 4001 不符 | 改用 `QUOTA_EXCEEDED(4001)`，或文档 §8.6 改为 2001 |
| CD-10 | 单(B) | `order_service.py:373, 399, 400` | `docs/split/05:20`「1002=无权限」、`05:23`「5002=券不可用」 | 商家无核销权限、订单已取消/已退款 → 均映射 `COUPON_UNAVAILABLE(5002)`，语义错配（拦截行为本身正确） | 无权限改 `FORBIDDEN(1002)`；已取消/已退款改用 5003 或新增语义码，同步 openapi |

### 4.2 P2 —— 文档自相矛盾 / 口径漂移 / 轻微问题

| 编号 | 印证 | 文件:行号 | 问题 | 建议修法 |
| --- | --- | --- | --- | --- |
| CD-11 | ✔ | `AGENTS.md:121`（242 passed）、`docs/go-no-go.md:16`（486 passed）、`deploy/README.md:42`（95 全绿） | 三处基线数字互相打架且全部过期；实跑 **485** | 统一刷新为 485 并注明时刻+库名 |
| CD-12 | ✔ | `dev_env.md:38`(3.12.3) vs `:63`(3.12.13)；`:39-40`(Node v24.1.0 / npm 11.4.2) | 同一文件自相矛盾，且与实测（3.12.3 / v22.13.1 / npm 11.9.0）不符 | 统一为实测值 |
| CD-13 | ✔ | `dev_env.md:206`「miniapp 与 admin 的 node_modules **均已装**」 | `admin/node_modules` **不存在** → admin 构建无法执行 | 修正为「仅 miniapp 已装」或补安装步骤 |
| CD-14 | ✔ | `docs/split/05:29`「接口列表（**30 个**）」 vs 表内 34 行 vs openapi 头部「34 接口」 vs 实际 72 路径/78 ops | 同一文档标题与实际、契约三者不一致 | 标题改 34，openapi 头部改「72 路径 / 78 ops」 |
| CD-15 | ✔ | `docs/split/04:101 §7.1`（31 表） vs 实际 36 表 | Phase 3~5 新增表（`subscription`/`leaderboard`/`track_event`/`community_comment`/`community_like`）未登记 | 更新表清单 |
| CD-16 | ✔ | `data/sql/001_schema.sql:666` vs `backend/app/models/__init__.py` | `config` 表 SQL 与库中均有，**ORM 无模型、代码零引用** | 补 ORM 模型，或文档标明「预留未启用」 |
| CD-17 | ✔ | `miniapp/src/pages.json:154-178` tabBar | 文档 `01:163-165` 要求 Tab = 首页/**吃什么**/**运动**/社区/我的；实际 = 首页/**记录**/社区/**商家**/我的 | 二选一同步（改 tabBar 或改文档） |
| CD-18 | ✔ | `docs/split/04:71`、`01:123`「超出返回 **400**」 vs `05:10`「参数错 = 422」 vs 代码 2001/422 | 文档内部打架，且与实现不符 | 统一为 422/2001 |
| CD-19 | 单(A) | `dev_env.md:103`、`AGENTS.md:129` | 种子命令指向 `rag_knowledge.sample.jsonl`（**仅 3 行**），但实际环境要求 `ai_knowledge=50`（`ai_knowledge_full.jsonl`）→ 照文档跑只能得 3 条 | 文档改指 `ai_knowledge_full.jsonl` |
| CD-20 | 单(A) | `backend/app/services/account.py:131` | `04:52`「每天 0 点生成 `daily_snapshot`」→ 实际无调度任务，只在写操作后 `recompute_day` | 补调度或改文档为「写触发 + 读兜底」 |
| CD-21 | 单(B) | `AGENTS.md:153` | 仍写「当前用 `NullPool`」；代码默认已是 `AsyncAdaptedQueuePool`（`db/session.py:22-32`） | 更新 AGENTS §7.3 |
| CD-22 | 单(B) | `docs/go-no-go.md:6`、`docs/接口冻结说明.md:13-14` | 冻结 commit 写 `c2f2bb4`、分支写 `feature/phase5`，当前为 `develop / 138d172` | 更新冻结基线 |
| CD-23 | 单(B) | `backend/app/core/idempotency.py:152` vs `app/main.py:80` | `install_idempotency()` 从未被调用，死代码 | 删除或让 main.py 调用 |
| CD-24 | 单(B) | `backend/app/core/config.py:31` + `.env:32` | 默认 `JWT_SECRET` 仅 28 字节 → PyJWT `InsecureKeyLengthWarning`（<32B） | 默认值改为 32+ 字节，或生产环境强制校验 |
| CD-25 | 单(B) | `AGENTS.md:154` | 只披露 B008，实际另有 UP045×94、E501×7、UP017×3 等 109 处非 B008 告警 | 更新存量告警说明或 `ruff --fix` 清理 |
| CD-26 | 单(A) | `docs/split/01:27` TDEE 口径 vs `04:54` TEE 口径 vs `calorie.py:173` | 两文档公式互相矛盾（NEAT 是否入 TEE）；实现为不入，与 `04 §6.3.1` 一致 | 文档统一为 §6.3.1 口径 |
| CD-27 | 单(A) | `docs/split/05:134` vs `:128` | 同一样例中 `calories_burnt=320` 但 `eat=274`，自相矛盾 | 改 320 → 274 |
| CD-28 | 单(B) | `contracts/openapi.yaml:503` | 声明 `Accept` 参数（SSE 预留），实现既不读取也不分支 | 契约移除该参数或实现 SSE |
| CD-29 | 单(A) | `contracts/mock/routes.mjs:405` | `/api/track` 硬编码 `accepted: 2`，提交 1 条也返回 2 → 前端联调误判 | 改为按 `events.length` 回显 |
| CD-30 | 单(A) | `docs/split/01:159-160` #24/#25 | `/pages/merchant/login`、`/pages/merchant/admin` 均缺失（商家后台落在独立 `admin/` H5） | 文档注明「商家后台合入 admin H5」 |

---

## 5. 结论与处置建议

**门禁结论：`FAIL`** —— 无 P0（测试、构建、契约对齐、安全抽查全过），但有 10 条 P1。

修复应按**两类**分开处理，不要混在一起改：

1. **必须改代码**（真实功能缺失）：CD-01 ~ CD-06（邀请裂变全链路：上限阈值、有效性判定、权益发放、双方发券、reward 文案、小程序页面）。这是唯一一条**文档承诺了但功能实际不可用**的业务链路，也是 K 因子与邀请解锁权益的验收项。
2. **契约/错误码对齐**（改哪边都行，但不能两边都留）：CD-07 ~ CD-10 —— 缺 `parameters` 声明、`scope` 参数漂移、库存不足 4001 vs 2001、核销越权语义映射到 5002。
3. **只改文档**（低风险、可批量）：CD-11 ~ CD-30 全部，属数字过期、版本漂移、口径矛盾、自相矛盾示例。

> 下一步建议：按 `AGENTS.md §5.4` 派**单个 fix Agent** 执行上述清单（精确到 `文件:行号 + 修法`），修复后重新派两个审查 Agent 复审，双 PASS 才 commit。是否执行、以及第 1 类改代码还是改文档（例如邀请上限到底是 5 还是 10），需要你先拍板。

---

## 附录：两份审查原始编号对照

| 本报告 | REVIEW-A | REVIEW-B |
| --- | --- | --- |
| CD-01 | RA-001 | RB-004 |
| CD-02 | RA-004 | RB-003 |
| CD-03 | RA-002 | RB-005 |
| CD-04 | RA-005 | RB-005 |
| CD-05 | RA-006 | RB-008 |
| CD-06 | RA-003 | — |
| CD-07 | — | RB-001 |
| CD-08 | — | RB-002 |
| CD-09 | — | RB-006 |
| CD-10 | — | RB-007 |
| CD-11~CD-18 | RA-012,015,018 / RA-007,010,011,009 | RB-014,019,016,017,018 / RB-012,010,013,020 |
| CD-19~CD-30 | RA-019,023,021,025,022 / RA-008,021 | RB-009,011,015,021,022,023,024,027,028,029 |

两份审查独立得出的**核心结论完全一致**（均判 FAIL、均定位邀请裂变链路、均确认无 P0、均实测 485 passed），分歧仅在覆盖广度：A 侧多覆盖前端页面与示例自相矛盾，B 侧多覆盖契约参数、错误码语义与 Phase 5 专项。
