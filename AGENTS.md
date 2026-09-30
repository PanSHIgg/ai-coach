# AGENTS.md — AI 饮食管控教练 · 多代理协作工作流

> 本文件约束本工作区内所有 AI 代理的协作方式。**仓库根 = 本文件所在目录**（本工作区为 `/workspace/ai-coach`），下述路径均相对仓库根（monorepo：`backend/ miniapp/ admin/ deploy/ data/ contracts/ docs_process/ perf/`）。交付计划见 `plan.md`，**需求唯一真源见 `docs/AI饮食管控教练_全栈开发交付文档.md`**（`docs/split/` 为其按主题拆分的等价副本，二者同源同步）。
>
> **docs/ 目录纪律**：`docs/` 下**只允许**存放开发交付文档（`AI饮食管控教练_全栈开发交付文档.md`）与其拆分副本 `split/`。过程性文档——验收报告（go-no-go）、冒烟清单（smoke_50）、测试报告、联调手册、打靶纪要、埋点口径、接口冻结说明、AI spike 等——一律放 `docs_process/`（2026-09-30 起，原 `docs/` 下 10 个过程文档已迁出，全仓引用已同步）。禁止把新的过程文档写回 `docs/`。
>
> 优先级：本文件 > 单次任务书 > 子 Agent 自行判断。冲突时以本文件为准，并在汇报中标注。

---

## 1. 角色定义

**主 Agent（指挥官，team lead）**——唯一的控制点：
- 拆解任务、建任务清单，向用户同步进度
- 编排子 Agent：按依赖关系决定并行/串行，同一消息内并行发出多个独立 Agent 调用
- **独占产出并冻结"地基"**（见 §4），分配**文件级互斥**的可写清单
- **统一执行所有 git 操作**（commit / branch / merge），子 Agent 一律禁止
- 验收子 Agent 交付物（抽查文件、在干净环境复跑关键命令），汇总后向用户汇报
- **守自己的上下文**：主 Agent 的上下文是全局稀缺资源，只用于拆解、决策、定级、验收与提交。**脏活一律派子 Agent**——环境与依赖准备（装 PG/Redis/CLI、建库、导种子、起服务）、批量探索、跑测试收集输出、截图核对、格式化批改等都不许自己干
- **不重复付环境成本**：环境准备只做一次，结论沉淀进 `dev_env.md` 与「环境事实块」，后续子 Agent 直接引用实测值，禁止重新探测或重新安装

**子 Agent**——单一明确任务的执行者：实现、审查、修复、数据、基建等。每个子 Agent 拿到自包含任务书独立工作，完成即汇报。

---

## 2. 子 Agent 任务书硬性规则

1. **自包含**：子 Agent 看不到主 Agent 的对话。任务书必须含：背景、仓库绝对路径、必读文档、交付物清单（精确到路径）、**可写文件白名单 + 禁碰文件清单**、自验步骤、汇报格式。
2. **文件级互斥（不是目录级）**：并行子 Agent 的**可写文件**不得相交。同一目录下的不同文件可并行，但**共享聚合文件**（见 §4.2）必须由主 Agent 预占位并冻结。
3. **共享文件只读**：共享真源（`contracts/`、`app/models/`、`app/services/calorie.py`、`app/services/account.py`、`app/api/v1/router.py`、`app/schemas/__init__.py`、`app/db/session.py`、`app/core/*`、`tests/conftest.py`、`miniapp/src/pages.json`、`miniapp/src/types/api.d.ts`、`miniapp/src/api/request.ts`、`uni.scss`、`styles/`）声明为**只读**。
   **灰色地带规则**：子 Agent 若判断必须修改任一共享文件，**先停止并在汇报中提出申请**，由主 Agent 决策（或由主 Agent 亲自改），禁止自行改动共享文件。
4. **环境事实块必须原样引用**：任务书须附 §7 的「环境事实块」，子 Agent 不得自行臆测路径/命令/依赖。
5. **禁止 git 写操作**：commit/branch/merge 全部由主 Agent 在子 Agent 交付并审查通过后统一执行，避免并发锁冲突。
6. **真实汇报**：汇报中的测试结果、命令输出必须真实执行所得，禁止编造或预测；测试数须标注**运行时刻 + 环境标识**（见 §3）。无法执行的项如实标注「未执行 + 原因」。
7. **零提问决策**：不确定处按最简可行方案继续，在汇报中以【假设】列出（对齐 `docs/split/10-零提问默认决策规则.md`）。
8. **环境不可靠时**：若工具输出出现漂移/自相矛盾，该子 Agent 只采信可交叉验证 ≥2 次的事实，其余标注「未验证」；**由主 Agent 在干净环境复跑定案**，禁止硬凑 PASS/FAIL 结论。
9. **测试节制（反测试膨胀）**：**一个行为一个测试**。禁止为同一行为/分支/边界在不同文件重复写用例；禁止断言框架/库自身行为（只测本项目行为）；同类边界值用 `parametrize` 合并；某行为的用例若已被更全面的用例覆盖，则删除较弱者。**严禁为"看起来覆盖高"堆砌重复测试**；删除测试前必须确认该独立行为在别处仍有覆盖；新增测试文件须说明其不可被现有文件容纳的理由。

---

## 3. 环境隔离契约（并行的前置条件）

> 教训来源：多个子 Agent 并行共享同一 PostgreSQL，`tests/conftest.py` 的函数级 `TRUNCATE ... CASCADE` 互相清库，导致大量**假失败**与 Agent 反复重试。因此**隔离是并行的前提，不是可选项**。

1. **并行前必须隔离资源**。主 Agent 为每个并行子 Agent 分配唯一 `AGENT_SLOT`（如 `1..N`），并派生隔离资源：
   - **数据库**：独立 schema（`search_path=agent_<slot>`）或独立库；`DATABASE_URL` 由 slot 派生（DB 名/schema 不同）。
   - **Redis**：独立 `db` index（如 `redis://127.0.0.1:6379/<slot>`）。
   - **端口**：mock/服务端口按 slot 偏移（如 `9000 + slot`）。
2. **不满足隔离就串行**。当无法隔离（例如只允许一个集成库）时，主 Agent 必须改为**串行**派发，或规定"子 Agent 只跑纯单元测试、集成测试由主 Agent 串行复跑"。
3. **测试数不可跨 agent 比较**。并行期各 agent 的 pytest 通过数来自不同库/时刻，**不作为验收依据**；验收统一由主 Agent 在**串行干净环境**复跑（见 §5.5）。
4. **种子/建表由主 Agent 统一初始化**：schema 与种子数据在派发前一次性备好；子 Agent 不得 `TRUNCATE`/重建全局 schema（只允许清自己的隔离 schema）。

---

## 4. 编排模式

### 4.1 地基先行 + 冻结

**契约/地基先行**：并行前先由主 Agent **独占产出并冻结**共享地基：
- 共享契约：`contracts/openapi.yaml` + 两份 TS 类型副本
- ORM 模型、核心算法/服务（如热量引擎、账户服务）
- 测试基建（`tests/conftest.py`）、依赖注入装配（`router.py`）、前端 `pages.json` 与设计令牌

冻结后，这些文件对子 Agent **一律只读**。子 Agent 只写各自的"独占文件"。

### 4.2 为解耦预拆分共享聚合文件

`router.py` / `schemas/__init__.py` / `pages.json` / 契约文件等**天然被多方引用**，必须由主 Agent **预先占位并 wire 好**（例如：把 `steps/sync` 从 `records.py` 拆出成 `steps.py`，预建 `weight.py`/`notification.py` 并挂入路由），子 Agent 只填实现——否则并行 Agent 必然争抢同一文件。

### 4.3 波次门禁

- **契约先行** → 地基冻结 → 按互斥文件分组**并行**（同一消息内并行发出）。
- **前后端对 Mock 解耦**：契约 + Mock 就绪后，前后端各自对 Mock 开发，按模块滚动联调。
- **契约变更纪律**：契约由主 Agent 单点修改并冻结；子 Agent 不得改契约；禁止实现单方面漂移。契约变更后由主 Agent 同步三处：`openapi.yaml` → pydantic schema → TS 类型（两份副本）+ Mock。

---

## 5. 质量循环：两个相同审查 Agent 全量复核 → 单 fix Agent 修复 → 门禁

> **定位**：这是进入提交/合并的**唯一门禁**。每波交付完成即触发，未通过不得 commit / merge。

1. **双审查（同配置、同任务书、全量）**：主 Agent 派出**两个完全相同的审查 Agent**（同一份任务书、同样的全量检查范围），**并行、只读**。
   - 二者的职责**不做分工**，都对**本波新增/改动的全部代码与文档**执行**全量检查**：跑测试、跑冒烟、静态检查（lint/类型检查）、构建、契约一致性核对、边界与异常路径、安全（越权/注入/重放）。
   - 另须检查两件常被忽略的事：**① 测试质量**（是否存在重复/无谓用例、是否断言框架自身行为、同类边界值是否可用 `parametrize` 合并，见 §2.9）；**② 前端/UI 波次**须用 `agent-browser` 对 **H5 产物**做真实渲染核对（布局/样式/交互/控制台无报错，见 `dev_env.md §6`），小程序侧用微信开发者工具。
   - 审查 Agent **禁止修改任何文件、禁止 git 操作**。
   - 两份审查必须**互不相通**、独立得出结论（用于交叉印证，避免单点漏检）。
2. **审查输出**（两者格式一致）：
   - ① **实跑原始摘要**：pytest 通过数、冒烟结果、lint/类型/构建结果等（附命令与关键输出）；
   - ② **分级问题清单**：`编号 | 级别 | 文件:行号 | 问题 | 建议修法`；
   - ③ **结论 `PASS / FAIL`**（存在任何 P0/P1 即 `FAIL`）。
3. **判级**：
   - **P0 = 阻断**：测试失败 / 导入失败 / 构建失败 / 契约不一致 / 文件损坏 / 越权。
   - **P1 = 真实缺陷**：边界、异常路径、并发、安全、数据不一致。
   - **P2 = 轻微**：文案、注释、可维护性（不阻塞 PASS）。
4. **单 fix Agent 修复**：主 Agent **汇总去重**两份清单，合成**精确到 `文件:行号 + 修法`**的修复清单，派**一个** fix Agent 执行；fix Agent 必须自验（复跑相关测试、语法/类型检查、集合比对），并回报"修了哪些、如何验证"。
5. **复审循环**：修复完成后**重新派出两个相同的审查 Agent**（保持独立视角、无前轮包袱）再次全量复核；循环 **2 → 4**，直到**两个审查 Agent 都 PASS**。
6. **闭环定案（主 Agent）**：审查 Agent 因环境无法实跑的项，由主 Agent 亲自在**串行干净环境**复跑（pytest、冒烟、构建、集合 diff）后代为定案；主 Agent 复跑中发现的新缺陷同样进入修复循环。
7. **门禁**：**两个审查 Agent 都 PASS，且主 Agent 干净环境复跑通过**，才允许 commit / merge。

---

## 6. 分支与提交

- **git flow**：`main`（稳定里程碑）/ `develop`（集成分支，日常交付落这里）/ `feature/*`（按 Phase/任务拉取）。
- **提交节奏**：每波交付 + 双审查 PASS + 主 Agent 复跑通过后，由主 Agent 提交；提交信息注明任务编号与审查轮次
  （例：`Phase 0 第二波: ...(P0-e/f/h); 双轮独立审查: 修复P0x1+P1x4+P2x9`）。
- **Phase 收口默认动作**：每个 Phase 完成，主 Agent **默认提交到 `feature/phaseN` 分支**（或明确向用户说明本轮不提交及原因），避免工作区长期不落盘。里程碑后 `develop` fast-forward 合并回 `main`，**保留 develop**。
- **提交前**：主 Agent 必须确认工作区干净、关键自验（pytest / mock 冒烟 / 两端构建 / JSON/YAML 校验）已过。

---

## 7. 已固化的项目事实（新会话先读）

> 子 Agent 任务书请**原样引用**下方「环境事实块」，勿自行臆测。**环境确认清单**见 `dev_env.md`（动工/测试前先跑其 §0 自检）；本块与 `dev_env.md §1/§4` 须保持一致，环境变更时两处同步。

### 7.1 环境事实块（模板，随环境更新）

```
仓库根：/workspace/ai-coach
Python：要求 >=3.12（不限定 venv/目录；venv/conda/pyenv/系统均可）；本工作区实测解释器
       /workspace/.venv312/bin/python（示例，其它环境用自带 >=3.12，探测见 dev_env.md §1.1）
后端测试：cd backend && DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach" \
          "${PY:-/workspace/.venv312/bin/python}" -m pytest -q   # PY=你的 >=3.12 解释器；基线：以当次实跑为准，
          # 最近一次全量实测 494 passed + 2 skipped（2026-09-30 UTC，库 ai_coach_a1）
PostgreSQL：127.0.0.1:5432  user=postgres password=postgres  db=ai_coach
            建表：psql -f data/sql/001_schema.sql（36 表；Alembic 0001 与之同源，二者择一）
Redis：127.0.0.1:6379
种子导入："${PY:-/workspace/.venv312/bin/python}" data/load_seeds.py \
          --dsn "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach" \
          --file food:data/seeds/food_full.csv --file food_alias:data/seeds/food_alias_full.csv \
          --file sku_catalog:data/seeds/standard_sku.sample.csv \
          --file ai_knowledge:data/seeds/ai_knowledge_full.jsonl
          （sku_catalog/ai_knowledge 必导，否则订单与 AI 用例失败；ai_knowledge_full.jsonl 共 50 条）
          dry-run：... --dry-run（CSV 用 utf-8-sig 兼容 BOM）
Mock：node contracts/mock/server.mjs（PORT 默认 9000）
前端：cd miniapp && npm install → npm run type-check → npm run build:mp-weixin / npm run build:h5
      前端交付必须过「type-check 0 错误 + 双端 build 通过」
浏览器自动化：能力见仓库内 skill .agents/skills/agent-browser/SKILL.md（用前先读，并按其指引
      先执行 `agent-browser skills get core`）；未装则 npm i -g agent-browser && agent-browser install
      仅用于 H5/浏览器页面验收（布局/交互/控制台），小程序用微信开发者工具；详见 dev_env.md §6
环境自检：动工/测试前先按 dev_env.md §0 确认（Python/Node/PG/Redis/agent-browser）
```

### 7.2 契约与真源

- **需求唯一真源**：`docs/AI饮食管控教练_全栈开发交付文档.md`（`docs/split/` 为其按主题拆分的等价副本：01 架构需求 / 02 UI 规范 / 03 页面交互 / 04 后端与数据库 / 05 API 接口 / 06 AI 服务 / 07 测试方案 / 08 部署运维 / 09 排期验收 / 10 零提问决策规则）。**代码与实现冲突时以该文档为准**；文档与实现不一致应修复实现或在文档留痕决策，禁止无记录地单方面漂移。`docs/` 只保留交付文档与 `split/`，过程性文档一律放 `docs_process/`。
- **契约真源**：`contracts/openapi.yaml`（路径含 `/api` 前缀；统一 envelope + 错误码 + Bearer JWT）。当前 **72 路径 / 78 ops**（Phase 1 `weight*`/`subscription*`/`auth/refresh`；Phase 3 `/api/admin/*` 12 个；Phase 4 社区/社交 25 个；Phase 5 新增 `/api/track`、`/api/order/{id}/refund`）。
- **TS 类型有两份手写副本**（`contracts/ts/api.d.ts` 与 `miniapp/src/types/api.d.ts`）：**由主 Agent 单点同步**，禁止子 Agent 双写；变更后两份必须一致。
- **Mock**：`contracts/mock/routes.mjs`（新增接口须同步 canned data）。
- **错误码**：`0` 成功 / `1001` 未登录 / `1002` 无权限 / `2001` 参数校验 / `3001` 资源不存在 / `4001` 次数不足 / `4002` 重复请求（幂等拦截，Phase 5 新增） / `5001` 商家停业 / `5002` 券不可用 / `5003` 订单超时 / `5004` 核销码已用 / `6001` AI 不可用 / `7001` 邀请上限；HTTP 映射 422/401/403/404/409/429/500。
- **幂等约定（Phase 5 / F6）**：写接口可带 `Idempotency-Key` 头；同身份同 key 在 300s 内重放 → `409 + 4002`（见 `app/core/idempotency.py`）。**不带该头则行为不变**（协作式幂等，非强制）。

### 7.3 其它已固化事实

- **只读共享层（地基）**：见 §2.3 清单；如需变更须走"申请 → 主 Agent 决策"。
- **AI 无 Key 环境自动落 mock**（`backend/app/ai/`），hello-world：`python backend/scripts/ai_hello.py --task chat|vision`。
- **DB 引擎**：`backend/app/db/session.py` 默认 `AsyncAdaptedQueuePool`，`DB_POOL_DISABLED=True` 时回退 `NullPool`（pytest 跨事件循环兼容）。
- **已知存量**：后端 `ruff` 存量 **274 处**：B008×166（FastAPI `Depends/Query` 作默认值，属仓库既有风格，提示不阻断）+ UP045×94、E501×6、UP017×3、UP046×2、B904×1、UP012×1、I001×1；子 Agent 不要大规模重构存量风格。

---

## 8. 一句话原则

**能跑 > 完美；并行前先隔离，冻结后方并行；未过双审查门禁，不得提交。**

**主 Agent 只做决策不做体力活：脏活派子 Agent，环境成本只付一次。**
