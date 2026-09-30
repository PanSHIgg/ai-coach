# F8 · Go-No-Go 放行决议（Phase 5 · M5）

> ⚠️ **已过期归档**（2026-09-30 迁入 `docs_process/archive/`）：F8 放行决议（2026-09-29，M5 时点结论 No-Go）属时点性纪要，文中门禁基线（494 passed + 2 skipped）已被刷新。**取代真源：`docs_process/archive/review_20260930_summary.md`**（2026-09-30 全量核对定案，496 passed / 0 failed）；现行基线真源见仓库根 `AGENTS.md` §7.1。本文仅留档。

> 判据真源：`docs/split/07-测试方案.md` §9.7「上线通过标准」、`docs/split/09-排期与验收交付.md`
> §11.3 M5 / §12.1–12.2 验收清单、`plan.md` §11「退出标准（M5）」。
> 本决议**只记录本沙箱真实执行所得**；无法验证项**逐项标注「未验证 + 原因 + 补验方式」**，不臆断通过。
> 生成时刻：2026-09-29 15:52 UTC（Asia/Shanghai 23:52）。冻结基线：**develop 分支；基线 `138d172`（Phase 5 合入），随后续修复波次前进**。
> **修订（Phase 5 收尾修复）**：2026-09-29 16:03 UTC —— ①契约 4 处悬空 `$ref` 已修为 `NotFound404`；
> ②深分页已加索引 `idx_meal_user_created` 修复（921.9ms → 76~109ms）；③后台 375 窄屏响应式已修复并复验。
> 三项复验结论见本文 §一、§二、§四 及 `docs_process/兼容性测试报告.md`。

## 一、§9.7 退出标准逐项结论

| # | 退出标准（07 §9.7） | 当前真实结论 | 依据 |
| --- | --- | --- | --- |
| 1 | P0/P1 全部关闭，无遗留 | **全部关闭（P0/P1 无遗留）** | 安全域 P1（接口重放）**已闭环**（见 §二.1）；契约完整性 P1（`contracts/openapi.yaml` 4 处 `$ref:'#/components/responses/NotFound'` 悬空）**已修复**为 `NotFound404`（见 §二.2），F2 契约门禁已去除 xfail、转为真门禁 |
| 2 | 接口测试 100% 通过 | **通过（本沙箱）** | 全量 `pytest -q` → **494 passed, 2 skipped, 0 xfailed**（最近一次全量实测 2026-09-30 UTC，库 `ai_coach_a1`；2 skipped 为 Redis 不可达的环境性跳过）。契约一致性门禁**无 xfail**（该文件 77 passed） |
| 3 | 单测覆盖 ≥ 70% | **未验证** | 本轮未执行覆盖率统计（无 `pytest-cov` 运行记录） |
| 4 | 性能达标 | **部分达标（未全达标）** | `perf/report.md` §四/§八：低并发（c=5）查询 P95 达 <300ms ✓；百万行**深分页已修复**：加索引 `idx_meal_user_created` 后深页 921.9ms → **76.6~84.2ms**（首跑 109.3ms）✓、首页 0.08ms ✓；**仍超阈**：中并发（c=20）P95 1014.8ms、写类 order_create 1229ms；「100 并发 5 分钟」**未跑满**（环境 4GiB/3 核/NullPool+单 worker），以 c=100/12.2s 探测错误率 0% |
| 5 | 安全测试无高危 | **通过（无高危遗留）** | `docs_process/安全测试报告.md`：越权 / SQLi（72 用例）/ XSS / 支付篡改 / 限流 全通过；重放 P1 已闭环（§二.1）。**无未闭环高危** |
| 6 | 冒烟用例 50 条全部通过 | **通过** | `docs_process/smoke_50.md`：实跑 **61 passed**（≥50；2026-09-29 16:41 UTC，库 `ai_coach`） |

## 二、关键项细节

### 2.1 安全 P1（接口重放）——已闭环 ✅
- 缺口原状：`tests/test_security_replay.py` 曾以 `xfail` 暴露「1s 内重放 10 次全部落库」。
- 现状：主 Agent 新增 `backend/app/core/idempotency.py`（`IdempotencyMiddleware`）并装配进
  `app/main.py:98`；携带 `Idempotency-Key` 的写请求在 TTL 窗口内**仅首次放行，重复返回 HTTP 409 + 业务码 4002**。
- 本轮全量复跑：`test_security_replay.py` **无 xfail**（全部转正），即该 P1 已由测试证实闭环。

### 2.2 契约完整性 P1——已闭环 ✅
- 原现象：`contracts/openapi.yaml` 4 处（`/api/admin/merchants/{id}/audit`、`/api/admin/merchant-skus`、
  `/api/admin/merchant-skus/{id}/status`、`/api/admin/coupon-pools/{id}/grant`）的 `404` 响应
  `$ref: '#/components/responses/NotFound'`，而 `components.responses` 仅定义 `NotFound404`。
- 现状：主 Agent 已将上述 4 处改为 `$ref: '#/components/responses/NotFound404'`（全库现有 29 处
  `NotFound404` 引用均可解析，`components.responses` 定义存在、无悬空）。
- 复验：`backend/tests/test_contract_consistency.py::test_all_component_refs_resolve` **已移除
  `xfail` 标记、转为真门禁**；本轮实跑该文件 **77 passed、无 xfail**，全量 `pytest -q` **0 xfailed**。

### 2.3 性能（引用 `perf/report.md` 真实数字）
| 目标（plan §11 F5） | 实测（`perf/report.md`） | 判定 |
| --- | --- | --- |
| 查询 P95<300ms | c=5：food_search 184.7 / order_list 171.2 / account_today 290.0 | 低并发达标 |
| 同上 c=20（中并发） | account_today 1014.8 / food_search 620.3 / order_list 617.6 | **不达标** |
| 写+重算<800ms | meal_write 368.5 ✓；order_create 1229.0 ✗ | 部分达标 |
| 100 并发 5 分钟错误率<1%、无泄漏 | 环境无法跑满；c=100/12.2s 错误率 **0%**，但 P95 8233ms | 错误率暂达标；延迟不达标；**未验证 5 分钟** |
| 百万行分页<500ms | 首页 0.08ms ✓；深页（offset≈50w）**76.6~84.2ms**（修复前 739.2 / EXPLAIN 921.9） | **深/浅页均达标**（加索引 `idx_meal_user_created`，见 §八） |

主因（`perf/report.md` §五/§八）：深分页已通过新增索引 `idx_meal_user_created(user_id, created_at DESC, id DESC)`
消除全量排序落盘（`data/sql/001_schema.sql` + Alembic `0002_phase5_indexes.py`）；c≥20 吞吐饱和的主因是
**采集时点**应用为 `NullPool`（每请求新建连接）——**Phase 5 已将 `app/db/session.py` 默认改为真实异步连接池**
（`DB_POOL_DISABLED=true` 才回退 NullPool），连接池生效后的中并发/写类复测待补；keyset 分页 / 多 worker 等建议
见 `perf/report.md` §六（多 worker 尚未实施）。

## 三、本沙箱无法验证的项（逐项标注）

| 项 | 状态 | 原因 | 补验方式 |
| --- | --- | --- | --- |
| 生产环境稳定运行 7 天无 P0 | **未验证** | 无生产环境与 7 天观测窗 | 部署 `deploy/` 至 staging/生产，接入监控后连续观测 7 天（盯 P0 告警与错误率） |
| 真实微信支付（真实商户号联调） | **未验证** | 沙箱无真实 `WECHAT_MCH_ID`/`WECHAT_PAY_KEY`；`PAY_MOCK_MODE=false` 下支付推进走 mock 回调 | 按 `docs_process/微信支付联调手册.md` 配真实商户号，真机走通 `pay → 微信回调 → 核销` |
| 微信开发者工具真机/机型兼容 | **未验证** | 沙箱无微信开发者工具与真机 | 按 `docs/split/09` §9.3 在多机型 + 微信 8.x/最新版做真机验证 |
| Prometheus / Grafana 真实部署告警 | **未验证** | 沙箱未部署监控栈 | 按 `deploy/` 起 Prometheus+Grafana，导入 `dashboard.json`，触发 `alert.rules.yml` 验证告警到达 |
| 单测行覆盖率 ≥70% | **未验证** | 未跑覆盖率统计 | `pytest --cov=app --cov-report=term-missing` 实测，补测至 ≥70% |
| 性能「100 并发 5 分钟」原规格 | **未验证** | 本机 4GiB/3 核/无 swap + 采集时点 NullPool 单 worker，跑满将拖垮并行协作 | 生产规格机 + 多 worker（连接池已就绪）复跑 5 分钟，观测错误率与内存趋势 |

## 四、放行决议

**建议：No-Go（暂缓放行）**。

理由：
1. 性能**未全达标**：百万行深分页**已修复达标**（76~109ms，见 §二.3）；但**中并发（c≥20）查询 P95
   （1014.8ms）与写类 `order_create`（1229ms）仍超阈**，且「100 并发 5 分钟」未按规格跑；
2. 单测覆盖率、生产 7 天稳定、真实微信支付、微信真机、监控告警**均未验证**——M5「生产 7 天无 P0」是放行的硬门槛
   （逐项原因与补验方式见 §三）。

**已达成（可放行的正面结论）**：接口测试 100% 通过（**494 passed + 2 skipped / 0 xfailed**，最近全量实测 2026-09-30 UTC）、
契约一致性门禁**已无 xfail（真门禁）**、契约悬空 `$ref` 与百万行深分页两项缺陷**已修复并复验**、
冒烟 61 条全过、安全无高危遗留（重放 P1 已闭环）、后台 **375 / 1440 / 1920 三档真实复验通过**
（见 `docs_process/兼容性测试报告.md`）。

### 剩余风险清单
| 编号 | 级别 | 风险 | 建议动作 | 责任 |
| --- | --- | --- | --- | --- |
| R1 | ~~P1~~ **已关闭** | `contracts/openapi.yaml` 4 处 `responses/NotFound` 悬空 | 已修为 `NotFound404`，F2 门禁去 xfail 转真门禁（复验 77 passed / 0 xfailed） | 主 Agent（已完成） |
| R2 | P1 | 中并发（c≥20）查询 / 写类 P95 超阈（深分页已达标） | 连接池已由 Phase 5 默认启用（`app/db/session.py`）；+ 多 worker 复跑中并发/写类 | BE/INFRA |
| R3 | P1 | 单测覆盖率未测 | 跑覆盖率并补测至 ≥70% | QA |
| R4 | P1 | 生产 7 天稳定性未验证 | 上线灰度 + 监控观测 7 天无 P0 | INFRA |
| R5 | P1 | 真实微信支付 / 真机兼容 / 监控告警未验证 | 按 §三 补验方式逐项闭环 | BE/INFRA |
| R6 | P2 | 性能「100 并发 5 分钟」原规格未跑 | 生产规格机复跑 | QA/INFRA |

> 结论口径：在 R2–R6 闭环前，**不建议宣布 Go**；当前状态为「功能、安全、契约与后台三档响应式就绪，
> 性能（中并发/写类）与上线验证待补」。（R1 契约缺陷已闭环，已从阻塞项移除。）
