# AGENTS.md — AI 饮食管控教练 · 多代理协作工作流

> 本文件约束本工作区内所有 AI 代理的协作方式。**仓库根 = 本文件所在目录**（下文命令以 `$REPO_ROOT` 指代；仓库内任意位置可用 `$(git rev-parse --show-toplevel)` 取得，**不写死绝对路径**），下述路径均相对仓库根（monorepo：`backend/ miniapp/ admin/ deploy/ data/ contracts/ docs/ perf/`）。交付计划见 `plan.md`，**需求唯一真源见 `docs/AI饮食管控教练_全栈开发交付文档.md`**（`docs/split/` 为其按主题拆分的等价副本）。
>
> **docs/ 目录纪律（最高优先级，见 §7.2）**：`docs/` 下**只允许**存放开发交付文档（`AI饮食管控教练_全栈开发交付文档.md`）与其拆分副本 `split/`，以及 `changes/`（仅限**用户显式授权**放入的变更决策记录，见下）。禁止把过程性文档写回 `docs/` 或仓库根。**基线正文（根文档 + `split/`）一律只读，禁止修改/回写/新增**——无论实现与文档差异多大，都不许改文档适配代码。
>
> **`docs/changes/` 例外条款**：该目录仅存放用户主动提供并明确授权入库的变更决策/口径记录（如 `2026-10-01-邀请规则变更记录.md`）。此类文件记录的是**变更意图而非已生效基线**：在其对应变更真正落地（文档换版 + 代码变更）之前，需求裁定仍以基线正文为准；AI 不得据此擅自改动基线或代码，落地须由用户发起。
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
   - **端口**：临时起服务/静态服务的端口按 slot 偏移（如 uvicorn `8000 + slot`、后台静态 `4177 + slot`）。
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
- **前后端如何解耦（Mock Server 已删除，不要再按"对 Mock 开发"编排）**：解耦靠**契约 + 可独立起栈的后端**——前端开发态 `VITE_API_BASE=http://localhost`（本机 compose 的 nginx :80 反代 `/api` → api:8000，见 §7.1），后端各自用隔离库/服务（§3）。按模块滚动联调，联调即真链路（登录需根 `.env` 有微信凭证，无凭证是明确 1001，不再有假身份）。
- **契约变更纪律**：契约由主 Agent 单点修改并冻结；子 Agent 不得改契约；禁止实现单方面漂移。契约变更后由主 Agent 同步三处：`openapi.yaml` → pydantic schema → TS 类型（两份副本），**不再有第四份 Mock canned data**；一致性由 §7.2 的三方校验兜底。

---

## 5. 质量循环：两个相同审查 Agent 全量复核 → 单 fix Agent 修复 → 门禁

> **定位**：这是进入提交/合并的**唯一门禁**。每波交付完成即触发，未通过不得 commit / merge。

1. **双审查（同配置、同任务书、全量）**：主 Agent 派出**两个完全相同的审查 Agent**（同一份任务书、同样的全量检查范围），**并行、只读**。
   - 二者的职责**不做分工**，都对**本波新增/改动的全部代码与文档**执行**全量检查**：跑测试、跑冒烟、静态检查（lint/类型检查）、构建、契约一致性核对、边界与异常路径、安全（越权/注入/重放）。
   - 另须检查两件常被忽略的事：**① 测试质量**（是否存在重复/无谓用例、是否断言框架自身行为、同类边界值是否可用 `parametrize` 合并，见 §2.9）；**② 前端/UI 波次的视觉核对通道**：本项目**只交付微信小程序**，H5 不在部署面（`deploy/Dockerfile.miniapp` 与 nginx 的 SPA 三段已删），故**不存在"H5 线上产物"可核对**。可行做法：`cd miniapp && npm run build:h5` 后自起静态服务（或直接 `npm run dev:h5`）用 `agent-browser` 对本地 H5 渲染做布局/样式/交互/控制台核对——`#ifdef H5` 分支只有这条通道能看到，**但它对鉴权页只是"编译期防腐"，没有渲染核对价值**：mock code 删除后 H5 端已无登录路径（`src/pages/login.vue` 的 `fetchWxCode` 只在 `#ifdef MP-WEIXIN` 里赋值 → `canWxLogin=false`，点登录只 toast「仅微信小程序支持登录」），拿不到 token 的鉴权页停在未登录态（如 `src/pages/report/index.vue:4` 的 `CNoPermission`）。**结论口径：H5 渲染核对实际只覆盖免登录页**，任何"H5 鉴权页已核对/已验证"的表述都不成立。小程序侧仍以**微信开发者工具**（加载 `dist/build/mp-weixin`，外部重建须 `cli quit`+`cli open` 才生效）为准。注意 `scripts/h5-compat-check.sh` 现只覆盖**管理后台**浏览器渲染，**不再构建/渲染小程序 H5**（见 `dev_env.md §6`）。
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
- **提交前**：主 Agent 必须确认工作区干净、关键自验（pytest / **compose 冒烟**——照 `.github/workflows/ci.yml` 的 `compose-deploy` job 语义跑：nginx 探活 + 无凭证登录断言 1001 + 后台登录拿 token 打管理接口 + 鉴权反向对照 + 种子行数 / type-check + `build:mp-weixin` / JSON·YAML 校验）已过。**"mock 冒烟"已随 mock server 一并废止**，不要再用它当代步自验。

---

## 7. 已固化的项目事实（新会话先读）

> 子 Agent 任务书请**原样引用**下方「环境事实块」，勿自行臆测。**环境确认清单**见 `dev_env.md`（动工/测试前先跑其 §0 自检）；本块与 `dev_env.md §1/§4` 须保持一致，环境变更时两处同步。

### 7.1 环境事实块（模板，随环境更新）

```
仓库根：本文件（AGENTS.md）所在目录，下文以 <repo-root> 指代；仓库内任意位置可用
       $(git rev-parse --show-toplevel) 取得，不写死绝对路径
Python：要求 >=3.12（不限定 venv/目录；venv/conda/pyenv/系统均可）；解释器路径不写死，
       经 PY 变量指定或按 dev_env.md §1.1 探测（如 command -v python3.12 || command -v python3）
后端测试：cd <repo-root>/backend && DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach" \
          "${PY:-python3.12}" -m pytest -q   # PY=你的 >=3.12 解释器；基线：以当次实跑为准，
          # 最近一次全量实测 666 passed + 0 failed（2026-10-02 UTC，develop 240d27f，库 ai_coach 与
          #    ai_coach_r2 两个隔离槽各跑一次结果一致）
          # ⚠️ 注意 DB-5：tests/conftest.py 的 TRUNCATE 含 food/food_alias，跑完全量后种子被清空，
          #    任何依赖食物库匹配的验证（RAG/AI 识别/ILIKE 回落）必须先重跑 data/load_seeds.py，否则会误判为代码缺陷。
PostgreSQL：127.0.0.1:5432  user=postgres password=postgres  db=ai_coach
            建表：psql -f data/sql/001_schema.sql（36 表；Alembic 0001 与之同源，二者择一）
Redis：127.0.0.1:6379
种子导入："${PY:-python3.12}" data/load_seeds.py \
          --dsn "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach" \
          --file food:data/seeds/food_full.csv --file food_alias:data/seeds/food_alias_full.csv \
          --file sku_catalog:data/seeds/standard_sku.sample.csv \
          --file ai_knowledge:data/seeds/ai_knowledge_full.jsonl
          （sku_catalog/ai_knowledge 必导，否则订单与 AI 用例失败；ai_knowledge_full.jsonl 共 50 条）
          ⚠️ compose 的 migrate 服务用的是 rag_knowledge.sample.jsonl（本机实测仅 3 行），与本行不同源：
             跑 RAG/AI 相关验证前按上面这条全量命令重导，别把"容器里只有 3 条"当成代码缺陷。
          dry-run：... --dry-run（CSV 用 utf-8-sig 兼容 BOM）
无 Mock（2026-10-02 起）：`contracts/mock/`（server.mjs + routes.mjs，791 行）已删除，
      后端也无 mock 登录分支——`WECHAT_APPID`/`WECHAT_SECRET` 任一为空即**明确 1001 失败**
      （`app/services/auth_service.py`），不再伪造 openid；测试的零依赖可跑性改由
      `backend/tests/conftest.py` 的 autouse `_stub_code2session` 承担
      （openid = "test-" + sha256(code)[:16]，**同 code 必得同 openid**，重放/注入用例依赖此确定性）。
契约一致性门禁：openapi.yaml ↔ 后端 FastAPI 路由 ↔ 两份 TS 类型 三方一致校验
      （`backend/tests/test_contract_consistency.py`），取代原"mock 覆盖契约全部操作"门禁。
本机全栈（WSL docker）：compose 工程名 `ai-coach`（`deploy/docker-compose.yml` 顶层 `name:`），
      nginx :80 反代 `/api` → api:8000；postgres 127.0.0.1:5432、redis 127.0.0.1:6379。
      Git Bash 调 docker 必须经 WSL：`timeout 60 wsl.exe -e bash -lc 'docker ...'`（裸 /workspace 路径会被 MSYS 改写）。
      后端测试解释器（本机实测）：`backend/.venv/Scripts/python.exe`（系统 python3.12 无后端依赖）。
      ⚠️ `env_file` 标了 `required: false`：根 `.env` 缺失时 compose **静默**跳过该文件（不报错），
         这是"改了 .env、重启 compose 却没生效"的根因——先核实文件存在与键名，再怀疑代码。
      ⚠️ 换 `JWT_SECRET` 会让已签发 token 集体失效（前端表现：index↔login 互弹）。
      后台种子账号：`data/sql/003_phase3_admin_seed.sql`（`admin_user` 表由 001_schema.sql 建，
         initdb.d 与 `load_seeds.py` 都**不含**后台账号）；口令见该文件头注释，`POST /api/admin/login` 实测 code=0。
      真微信登录本机已实测通：解 JWT payload 看 `openid` 前缀（真 = `oCPjzxZ-…`，非 `mock-`）；
         假 code → `1001 + "invalid code, rid:…"`（`rid` 来自微信侧，可作"真链路已生效"判据）。
微信开发者工具：导入目录是 `miniapp/dist/build/mp-weixin`（不是 src）；**外部重建产物不会自动生效**，
      必须 `cli quit` + `cli open` 才真正加载新 bundle（WeappLog 里 `DevtoolsFileWatcher … false`）。
前端：cd miniapp && npm install → npm run type-check → npm run build:mp-weixin（= 唯一交付物）
      `build:h5`/`dev:h5` 与 `#ifdef H5` 分支**刻意保留但不进部署面**，只作 agent-browser 视觉回归通道。
      前端交付门禁：type-check 0 错误 + `build:mp-weixin` 通过；H5 通道另跑 `build:h5` 防其腐化
      （`#ifdef H5` 只有 H5 构建才会编译，CI frontend job 仍保留该步骤，见 ci.yml 注释）。
      ⚠️ **CI/CD 只管后端部署**（`cd.yml` 仅 build `Dockerfile.backend`）；小程序包由**微信开发者工具上传
      → 公众平台审核发布，不经过流水线**。所以 CI 里的 `build:mp-weixin` / `build:h5` **只是编译检查**，
      不要在 CI 里断言"小程序发布 baseURL/域名"——发布域名是**上传前由人填**的事，且当前项目
      **尚无域名，测试一律走 `http://localhost`**（本机 compose nginx :80）。
      空 baseURL 的兜底在运行期：`src/api/request.ts` 的 `#ifdef MP-WEIXIN` 断言启动即抛。
浏览器自动化：能力见仓库内 skill .agents/skills/agent-browser/SKILL.md（用前先读，并按其指引
      先执行 `agent-browser skills get core`）；未装则 npm i -g agent-browser && agent-browser install
      用于本地 H5 / 浏览器页面验收（布局/交互/控制台），小程序用微信开发者工具；详见 dev_env.md §6
环境自检：动工/测试前先按 dev_env.md §0 确认（Python/Node/PG/Redis/agent-browser）
```

### 7.2 契约与真源

- **需求唯一真源**：`docs/AI饮食管控教练_全栈开发交付文档.md`（`docs/split/` 为其按主题拆分的等价副本：01 架构需求 / 02 UI 规范 / 03 页面交互 / 04 后端与数据库 / 05 API 接口 / 06 AI 服务 / 07 测试方案 / 08 部署运维 / 09 排期验收 / 10 零提问决策规则）。**代码与实现冲突时以该文档为准**。
- **`docs/` 只读纪律（不可绕过）**：
  - `docs/` 下所有文件（主文档 + `split/00~10`）是**原始需求基线**，**禁止修改、回写、新增任何文件**——包括"口径统一""文档对齐代码""留痕决策"等任何理由。
  - **历史教训**：`e34c776` 曾以"口径统一回写"为名改写主文档与 split 共 8 个文件（表清单 31→36、接口数 30→34、错误码 400→422、新增 §8.6 等 21 处），导致验收基准漂移（文档描述的=已实现的，失去独立审计价值），后已全部恢复至基线锚点 **git commit `015d736`**（主文档 MD5 `b031abf7…`）。任何让 docs/ 偏离该锚点的改动都视为破坏基线。
  - **实现与文档不一致时的唯一正确处置**：① 文档对代码错 → 改代码补测试；② 代码对文档口径过时 → 在 `current.md` 差异清单登记（`文档位置 | 文档说法 | 实际实现 | 建议`），**等产品拍板后由用户决定是否修订基线**；③ 文档要求的 P0 功能未实现 → 视为需求缺口登记排期，**禁止改文档或改 current.md 宣告完成**。
- **契约真源**：`contracts/openapi.yaml`（路径含 `/api` 前缀；统一 envelope + 错误码 + Bearer JWT）。当前冻结基线 **110 路径 / 119 ops**（GET 54 / POST 56 / PUT 4 / DELETE 5）——该数由 `backend/tests/test_contract_consistency.py` 的 `FROZEN_PATH_COUNT/FROZEN_OP_COUNT` **双向钉死**（契约侧与后端实际注册路由侧都要等于它，漂移即红），并同步写在 `contracts/README.md`。**旧口径全部作废**：`miniapp/README.md`/`contracts/README.md` 曾写 34、本节曾写 78 ops、被删的 `contracts/mock/routes.mjs:1` 曾写 116——引用计数一律以 110/119 为准；接口换版时由主 Agent 同时改 openapi.yaml + 该测试常量 + `contracts/README.md`。
- **TS 类型有两份手写副本**（`contracts/ts/api.d.ts` 与 `miniapp/src/types/api.d.ts`）：**由主 Agent 单点同步**，禁止子 Agent 双写；变更后两份必须一致。
- **契约一致性校验**（取代原 Mock）：`openapi.yaml` ↔ 后端 FastAPI 实际路由 ↔ 两份 TS 类型 三方比对，落在 `backend/tests/test_contract_consistency.py`；新增/改接口必须同时过这条门禁，**不再需要同步 canned data**。
- **错误码**：`0` 成功 / `1001` 未登录 / `1002` 无权限 / `2001` 参数校验 / `3001` 资源不存在 / `4001` 次数不足 / `4002` 重复请求（幂等拦截，Phase 5 新增） / `5001` 商家停业 / `5002` 券不可用 / `5003` 订单超时 / `5004` 核销码已用 / `6001` AI 不可用 / `7001` 邀请上限；HTTP 映射 422/401/403/404/409/429/500。
- **幂等约定（Phase 5 / F6）**：写接口可带 `Idempotency-Key` 头；同身份同 key 在 300s 内重放 → `409 + 4002`（见 `app/core/idempotency.py`）。**不带该头则行为不变**（协作式幂等，非强制）。

### 7.3 其它已固化事实

- **只读共享层（地基）**：见 §2.3 清单；如需变更须走"申请 → 主 Agent 决策"。
- **AI 无 Key 环境自动落 mock**（`backend/app/ai/`），hello-world：`python backend/scripts/ai_hello.py --task chat|vision`。**这是四件独立的事，别混**：① AI 无 Key 降级（**仍然有效**）② 微信支付 `PAY_MOCK_MODE`（**仍然有效**）③ mock 登录 / mock server（**2026-10-02 已彻底删除**，见 §7.1）④ **小程序页面级示例数据回落 `isMock`**（**仍然有效，且不在本轮删除范围**）：`pages/coupon.vue:17`、`pages/order/list.vue:17`、`pages/merchant/merchant.vue:17`、`pages/merchant/detail.vue:18`、`pages/order/confirm.vue:22` 在**请求失败**时展示内置示例数据，并带可见横幅「示例数据 · 后端暂未连接」。定位是**离线容错**，不参与登录/token、不是 ③ 的残留，别把它当成"前端仍有 mock 没删干净"报 P0/P1。
- **DB 引擎**：`backend/app/db/session.py` 默认 `AsyncAdaptedQueuePool`，`DB_POOL_DISABLED=True` 时回退 `NullPool`（pytest 跨事件循环兼容）。
- **已知存量**：后端 `ruff` 存量 **432 处**（2026-10-02 实测）：B008×245（FastAPI `Depends/Query` 作默认值，属仓库既有风格，提示不阻断）+ UP045×121、E501×30、W292×20、UP017×6、I001×5、UP046×2、F401×2、B904×1；子 Agent 不要大规模重构存量风格。

---

## 8. 一句话原则

**能跑 > 完美；并行前先隔离，冻结后方并行；未过双审查门禁，不得提交。**

**主 Agent 只做决策不做体力活：脏活派子 Agent，环境成本只付一次。**

**没有 Mock 之后：真凭证 + 真种子 + 真栈是唯一联调通道**（本地 compose 走 WSL docker，鉴权断言照 ci 的 `compose-deploy` 语义跑）；**H5 只是视觉回归通道，不是交付物**——任何"H5 已部署/H5 验收通过"的表述都是错的。
