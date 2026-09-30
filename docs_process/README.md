# docs_process/ 目录索引

> 本目录存放**过程性文档**：验收报告（go-no-go）、冒烟清单、测试报告、联调手册、打靶纪要、埋点口径、接口冻结说明、AI spike、一致性核对报告与问题扫描清单等。纪律真源见仓库根 `AGENTS.md`（文件头「docs/ 目录纪律」与 §7）。

## 一、目录纪律（提炼自 AGENTS.md docs/ 目录纪律）

1. **`docs/` 下只允许**存放开发交付文档（`AI饮食管控教练_全栈开发交付文档.md`）与其拆分副本 `docs/split/`。**禁止把新的过程文档写回 `docs/` 或仓库根**——过程性文档一律放 `docs_process/`。
2. **过期不删，留档可追溯**：被后续核对/波次取代的过程文档，迁入 `docs_process/archive/`，并在文件头加「⚠️ 已过期归档」注记，格式：
   `> ⚠️ **已过期归档**（<日期> 迁入 docs_process/archive/）：<被谁取代 / 为何过期，指明取代真源>。本文仅留档。`
   原文件已有过期注记的，合并为一条，不重复堆叠。
3. **活文档**（仍然有效的口径/手册/规范）留在 `docs_process/` 平铺，下表即全集；新增活文档须同步登记本索引。
4. **`archive/` 内文件不再更新**：只读留档，供追溯历史结论、基线与环境数值；不随代码演进修订。现行有效口径以各注记中指向的真源为准。

## 二、活文档索引（docs_process/ 平铺）

| 文件名 | 主题 | 一句话说明 |
| --- | --- | --- |
| `埋点与指标口径.md` | 埋点与指标口径（Phase 5 / F3） | `POST /api/track` 上报规范、10 类事件名/属性清单、六项核心指标（留存/K 因子/扫码转化/识别成功率/AI 满意度/CAC）的分子分母口径与报表脚本 |
| `前端埋点接入说明.md` | 前端埋点接入手册（Phase 5 / F3） | miniapp `track.ts` 封装（批量/匿名/静默降级）、已接入事件清单、`Idempotency-Key` 客户端接入建议 |
| `微信支付联调手册.md` | 微信支付联调手册（Phase 5 / F1） | JSAPI 支付真实商户环境接入：配置项清单、`PAY_MOCK_MODE` 开关语义、真机联调步骤、退款/验签/幂等排查速查 |
| `接口冻结说明.md` | 接口冻结与契约纪律（Phase 5 / F2） | 72 路径 / 78 ops 冻结基线、Phase 5 契约新增（track / refund / 4002 / Idempotency-Key）、契约变更四处同步纪律与 F2 自动化门禁 |

## 三、archive/ 归档索引（docs_process/archive/）

| 文件名 | 时点 | 被谁取代 / 归档理由 |
| --- | --- | --- |
| `codediffwithdoc.md` | 2026-09-29（基线 `138d172`） | 文档 vs 代码全量核对（P1×10/P2×20）已由 `e49737e` 闭环；被 `review_20260930_summary.md`（基线 `dbbf198`）取代 |
| `issues_scan_0929.md` | 2026-09-29（基线 `a2708b3`） | Phase 0-3 扫描清单 IS-001~012 已由 `a11a2d3` 修复闭环；被 `review_20260930_summary.md` 取代 |
| `go-no-go.md` | 2026-09-29（M5 时点决议：No-Go） | F8 放行决议属时点纪要，门禁基线（494 passed+2 skipped）已被刷新；现行基线真源 = `AGENTS.md` §7.1，最新核对 = `review_20260930_summary.md` |
| `smoke_50.md` | 2026-09-29（61 passed） | F8 冒烟清单及实测为交付时点记录；自动化真源 = `backend/tests/smoke/test_smoke_50.py`，口径真源 = `docs/split/07` §9.7 |
| `兼容性测试报告.md` | 2026-09-29（Phase 5 / F7） | H5 + 管理后台三档渲染核对，缺陷复验（F7-P1/F7-P2a）已闭环；前端/部署域被 `review_20260930_summary.md` 覆盖 |
| `安全测试报告.md` | 2026-09-29（Phase 5 / F6） | 越权/SQLi/XSS/重放/支付篡改测试纪要，重放 P1 已闭环；安全域被 `review_20260930_summary.md` 覆盖 |
| `后台打磨纪要.md` | Phase 5 / F4（2026-09-29 收尾） | 管理后台改版纪要，改动已落入 `admin/` 代码（以代码为准） |
| `ai-provider-spike.md` | Phase 2（P0-h spike） | 选型结论（DeepSeek/腾讯云）与现行代码不符（AI-7）；现行 provider 真源 = 仓库根 `ai_api.md` + `backend/app/ai/README.md` |
| `review_20260930_summary.md` | 2026-09-30（基线 `dbbf198`） | 全量核对主 Agent 定案汇总，为时点快照；有效口径/基线已沉淀至 `AGENTS.md` §7.1、`dev_env.md`、`contracts/openapi.yaml` |
| `review_20260930_be_api.md` | 2026-09-30（slot5） | 后端 API / 鉴权 / 限流 / 幂等分域核对分报告，结论并入 `review_20260930_summary.md` |
| `review_20260930_db_data.md` | 2026-09-30（slot2） | 数据库 / ORM / 种子分域核对分报告，结论并入 `review_20260930_summary.md` |
| `review_20260930_fe_deploy.md` | 2026-09-30（slot3） | 前端 / 部署 / CI 分域核对分报告，结论并入 `review_20260930_summary.md` |
| `review_20260930_ai_biz.md` | 2026-09-30（slot4） | AI 服务 / 业务算法分域核对分报告，结论并入 `review_20260930_summary.md` |

## 四、引用约定

- 仓库内代码/文档引用活文档时使用 `docs_process/<文件名>`（如 `docs_process/埋点与指标口径.md`）。
- 引用归档文件时路径为 `docs_process/archive/<文件名>`；已有外部文件（代码注释等）若仍指向 `docs_process/<被归档文件>`，属历史引用，由主 Agent 按需处理。
