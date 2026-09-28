# dev_env.md — 开发 / 测试环境确认（动工前必跑）

> **用途**：任何开发、测试、联调开始前，先按本文件确认环境；不满足就先修环境，**不要带着坏环境跑测试**（否则产生大量假失败）。
>
> 同源：本文件与 `AGENTS.md §7.1 环境事实块` 保持一致，环境变更时**两处同步**。CI 参照 `.github/workflows/ci.yml`。

---

## 0. 一键自检（复制执行）

```bash
# ---- 语言 / 工具链 ----
/workspace/.venv312/bin/python --version     # 期望 Python 3.12.x（勿用系统 python 3.14）
node --version && npm --version              # 期望 Node >= 20 / npm >= 10

# ---- 数据库 / 缓存 ----
psql --version                               # 期望 PostgreSQL 16.x
redis-cli --version                          # 期望 Redis 7.x
pg_isready -h 127.0.0.1 -p 5432              # 期望 "accepting connections"
redis-cli -h 127.0.0.1 ping                  # 期望 PONG

# ---- 浏览器自动化（H5 验收用）----
agent-browser --version                      # 缺失见 §5
```

任一不满足 → 按 §2–§5 处理。**环境事实以本机当次实测为准，不要臆测。**

---

## 1. 必需工具与版本

| 工具 | 版本要求 | 本机实测 | 校验命令 | 说明 |
| --- | --- | --- | --- | --- |
| Python | 3.12.x | 3.12.13 | `/workspace/.venv312/bin/python --version` | venv = `/workspace/.venv312`；系统 `python3` 为 3.14，装不上依赖，**勿用** |
| Node.js | ≥ 20 | v24.1.0 | `node --version` | 前端 uni-app 构建 |
| npm | ≥ 10 | 11.4.2 | `npm --version` | |
| PostgreSQL | 16.x | 16.15 | `psql --version` / `pg_isready` | `127.0.0.1:5432`，user/pass = `postgres/postgres`，db = `ai_coach` |
| Redis | 7.x | 7.0.15 | `redis-cli ping` | `127.0.0.1:6379` |
| agent-browser | 最新 | 需安装 | `agent-browser --version` | H5 页面浏览器自动化验收，见 §5 |

> 代码要求 `python >= 3.12`（见 `backend/pyproject.toml`）。使用错误解释器是最常见的“依赖装不上”根因。

---

## 2. 起本地依赖（PostgreSQL / Redis）

**方式 A：Docker（推荐）**

```bash
cd /workspace/ai-coach
cp .env.example .env                                   # 开发可先留空密钥
docker compose -f deploy/docker-compose.yml up -d postgres redis
```

**方式 B：本机已装 PG/Redis**
只需确认 `pg_isready -h 127.0.0.1 -p 5432` 与 `redis-cli ping` 正常。

---

## 3. 初始化数据库（首次 / 重建）

```bash
cd /workspace/ai-coach
export PGPASSWORD=postgres

# 建库（已存在会报错，可忽略）
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE ai_coach;"

# 建表（36 表；与 Alembic 0001 同源，二者择一）
psql -h 127.0.0.1 -U postgres -d ai_coach -v ON_ERROR_STOP=1 -f data/sql/001_schema.sql

# 种子：食物库 + 别名（CSV 用 utf-8-sig 兼容 BOM）
/workspace/.venv312/bin/python data/load_seeds.py \
  --dsn "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach" \
  --file food:data/seeds/food_full.csv --file food_alias:data/seeds/food_alias_full.csv
```

---

## 4. 后端：测试 / 起服务 / Mock

```bash
# 回归测试（真实 PostgreSQL；conftest 函数级清库保证隔离）
cd /workspace/ai-coach/backend
DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach" \
  /workspace/.venv312/bin/python -m pytest -q

# 起后端（本地调试）
DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach" \
  /workspace/.venv312/bin/python -m uvicorn app.main:app --reload --port 8000

# Mock server（前后端对 Mock 解耦联调；PORT 默认 9000）
node contracts/mock/server.mjs
```

- **测试基线**：以当次实跑为准（每次迭代会变化，不要引用过期数字）。当前阶段基线见 `AGENTS.md §7.1`。
- AI 无 Key 时自动落 mock（`backend/app/ai/`）；连通性自检：`/workspace/.venv312/bin/python backend/scripts/ai_hello.py --task chat|vision`。

---

## 5. 前端：uni-app（微信小程序 + H5）

```bash
cd /workspace/ai-coach/miniapp
npm install
npm run type-check          # vue-tsc --noEmit，必须 0 错误
npm run build:mp-weixin     # 微信小程序产物 → dist/build/mp-weixin
npm run build:h5            # H5 产物 → dist/build/h5
npm run dev:h5              # H5 开发服务（Vite，默认 http://localhost:5173）
```

**前端交付门禁**：`type-check` 0 错误 + 双端（mp-weixin / h5）`build` 通过。

---

## 6. 浏览器自动化验收（agent-browser）

**用途**：对 **H5 页面**（uni-app H5 产物 / 管理后台）做真实渲染与交互验收——布局、样式、路由跳转、点击、表单、响应式断点。可作为前端/UI 波次双审查的一环（见 `AGENTS.md §5`）。

> **能力边界**：微信小程序（`mp-weixin`）运行时是微信客户端，**agent-browser 无法驱动**。小程序侧请用**微信开发者工具**导入 `miniapp/dist/build/mp-weixin` 预览；自动化可用 `@dcloudio/uni-automator`（依赖微信开发者工具）。agent-browser 只用于 H5 / 浏览器页面。

**安装**

```bash
npm i -g agent-browser && agent-browser install
agent-browser skills get core        # 用法指南（随已安装版本更新，必看）
```

**H5 验收流程**

```bash
# 1) 另开终端起 H5 dev server
cd /workspace/ai-coach/miniapp && npm run dev:h5      # http://localhost:5173

# 2) 打开并核对
agent-browser open http://localhost:5173
agent-browser snapshot                                # 无障碍树：核对关键元素是否渲染
agent-browser screenshot --path /tmp/h5-index.png     # 截图留证
```

**验收要点（示例）**：5 个 Tab 与 FAB 可见；登录 → 首页跳转正常；首页评分环 / 热量环形图渲染且数字与接口一致；空态 / 错误 / 无权限组件按预期出现；浏览器控制台无报错。

---

## 7. 常见问题

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| `pip install` 装不上依赖 | 用了系统 `python3`（3.14） | 改用 `/workspace/.venv312/bin/python` |
| pytest 大量假失败 / 数据互相污染 | 多个 Agent 并行共享同一 PG，`conftest` 的 `TRUNCATE` 互清 | 按 `AGENTS.md §3` 隔离（独立 schema / Redis db / 端口）；无法隔离则串行 |
| pytest 报连接失败 | PG 未起 / 未建表 | 见 §2、§3 |
| 限流用例结果异常 | `conftest` 故意把 Redis 指向不可达端口（6390）以走进程内兜底 | 属预期，无需修 |
| H5 端口被占用 | 5173 被占 | `npm run dev:h5 -- --port 5174`，agent-browser 打开对应端口 |
| `agent-browser` 命令不存在 | 未安装 | `npm i -g agent-browser && agent-browser install` |

---

## 8. 与 AGENTS.md 的关系

- 本文件 = 环境**确认清单**；`AGENTS.md §7.1` = 给子 Agent 任务书**原样引用的环境事实块**。二者内容须一致。
- 变更环境（升级版本 / 改端口 / 换 DSN）时：**先改本文件，再同步 `AGENTS.md §7.1`**。