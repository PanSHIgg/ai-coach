# dev_env.md — 开发 / 测试环境确认（动工前必跑）

> **用途**：任何开发、测试、联调开始前，先按本文件确认环境；不满足就先修环境，**不要带着坏环境跑测试**（否则产生大量假失败）。
>
> 同源：本文件与 `AGENTS.md §7.1 环境事实块` 保持一致，环境变更时**两处同步**。CI 参照 `.github/workflows/ci.yml`。
>
> **约定**：下文 `$PY` 代表你的 Python ≥3.12 解释器；`$REPO_ROOT` 代表仓库检出根目录（即本文件所在目录），在仓库内任意位置可用 `$(git rev-parse --show-toplevel)` 取得——**本文不写死任何绝对路径**。**不假设虚拟环境，也不假设 venv 目录名/路径**——venv / conda / pyenv / 系统解释器均可，探测见 §1.1。

---

## 0. 一键自检（复制执行）

```bash
# ---- 语言 / 工具链 ----
# Python：任选一个 >=3.12 的解释器（不假设虚拟环境/目录）
python3 --version                            # 期望 >= 3.12；不符见 §1.1
PY="${PY:-$(command -v python3.12 || command -v python3)}"   # 后续命令统一用 "$PY"
node --version && npm --version              # 期望 Node >= 20 / npm >= 10

# ---- 数据库 / 缓存 ----
psql --version                               # 期望 PostgreSQL 16.x
redis-cli --version                          # 期望 Redis 7.x
pg_isready -h 127.0.0.1 -p 5432              # 期望 "accepting connections"
redis-cli -h 127.0.0.1 ping                  # 期望 PONG

# ---- 浏览器自动化（H5 验收用）----
agent-browser --version                      # 缺失见 §6；能力/用法见 .agents/skills/agent-browser/SKILL.md
```

任一不满足 → 按 §2–§6 处理。**环境事实以本机当次实测为准，不要臆测。**

---

## 1. 必需工具与版本

| 工具 | 版本要求 | 本机实测 | 校验命令 | 说明 |
| --- | --- | --- | --- | --- |
| Python | ≥ 3.12 | 3.12.3（本沙箱 `backend/.venv`；示例路径见 §1.1） | `"$PY" --version` | **不限定虚拟环境或目录**：venv/conda/pyenv/系统均可，只要 ≥3.12；探测见 §1.1 |
| Node.js | ≥ 20 | v22.13.1 | `node --version` | 前端 uni-app 构建 |
| npm | ≥ 10 | 11.9.0 | `npm --version` | |
| PostgreSQL | 16.x | 16.15 | `psql --version` / `pg_isready` | `127.0.0.1:5432`，user/pass = `postgres/postgres`，db = `ai_coach`。**Ubuntu 24.04(noble) 官方源即提供 16.15，直接 `apt-get install postgresql-16` 即可；若发行版只有 14 再加 pgdg 源装 postgresql-16 并 `pg_createcluster 16 main`** |
| Redis | 7.x | 7.4.11 | `redis-cli ping` | `127.0.0.1:6379`（2026-09-30 复验；packages.redis.io 官方源，勿用 apt 自带的 6.0） |
| agent-browser | 最新 | 0.27.0（系统 Chrome 可用，H5 验收已实测跑通） | `agent-browser --version` | H5 浏览器自动化验收；能力/用法见 `.agents/skills/agent-browser/SKILL.md`（§6）。0.27.0 非最新但功能完整，升级非必需 |
| Docker | 需要 | **可用**（27.5.1，daemon 在线，`docker run --rm hello-world` 实测跑通） | `docker --version` | 2026-10-01 复测：`/usr/local/bin/docker` 存在且 daemon 正常、`CAP_SYS_ADMIN` 具备、镜像可拉取。**本次交付仍按原生 PG/Redis + uvicorn 搭建**（见 §9），容器仅作备选。（注：该行是 2026-10-01 那台 Ubuntu 沙箱的实测；**当前 Windows 主机的 docker 在 WSL 内、Windows 侧不可见**，全栈已在 WSL 用 compose 起好——见 §2 的"本机实测"注意） |
| 压测工具 | 任选 | **未安装**（k6/locust/hey/wrk/ab/jmeter 均无） | `command -v k6` | Phase 5 性能用 `httpx`+asyncio 自研 harness（httpx 0.28.1 已装，见 §9） |

> 代码要求 `python >= 3.12`（见 `backend/pyproject.toml`）。使用错误解释器是最常见的“依赖装不上”根因。

### 1.1 Python 解释器探测（不要假设固定路径）

本仓库只要求 `python >= 3.12`，**既不要求虚拟环境，也不假设 venv 目录名/路径**。任选一个满足要求的解释器即可：

```bash
# ① 已有 venv / conda 环境：直接激活（路径按你的实际填）
#    source <your-venv>/bin/activate        # 或：conda activate <env>
# ② 否则探测系统 / 工具链中的 3.12+
command -v python3.12 || command -v python3 || command -v python
"$PY" -c 'import sys; assert sys.version_info[:2] >= (3, 12), sys.version'   # 校验版本
# ③ 都没有再新建（示例）
python3 -m venv .venv && . .venv/bin/activate && pip install -r backend/requirements.txt
```

> **示例**（**勿照抄**）：解释器以 `PY=/path/to/your/python3.12` 形式指定即可，不要假设任何固定路径。本沙箱当前实测解释器为 `backend/.venv/bin/python`（Python 3.12.3）。下文所有 `$PY` 均指你选定的解释器。

---

## 2. 起本地依赖（PostgreSQL / Redis）

**方式 A：Docker（推荐）**

```bash
cd "$(git rev-parse --show-toplevel)"                  # 仓库根（$REPO_ROOT）
cp .env.example .env                                   # ⚠️ 见下方"密钥"注意
docker compose -f deploy/docker-compose.yml up -d postgres redis
```

> **本机实测（2026-10-02）**：docker 跑在 **WSL** 里，Windows/Git Bash 侧没有 daemon——`docker ps` 返回空是正常的。
> 一切 docker/compose 命令走 `timeout 60 wsl.exe -e bash -lc 'docker …'`。全栈已在 WSL 起好（工程名 `ai-coach`：
> nginx :80 反代 `/api` → api:8000、postgres 宿主 127.0.0.1:5432、redis 127.0.0.1:6379），
> `curl http://localhost/api/...` 即走真链路。**compose 的 `env_file: ../.env` 标了 `required: false`：
> `.env` 缺失时静默跳过、不报错**（"改了 .env 没生效"的根因，见 §7）。
>
> **密钥注意**：`.env` 留空不再"零依赖可跑"——mock 登录已删，`WECHAT_APPID`/`WECHAT_SECRET` 为空时
> `POST /api/auth/login` 直接 1001（见 §4）。要本地真登录须在根 `.env` 填微信凭证；
> 另：换 `JWT_SECRET` 会让已签发 token 集体失效。

**方式 B：本机已装 PG/Redis**
只需确认 `pg_isready -h 127.0.0.1 -p 5432` 与 `redis-cli ping` 正常。

> 无 Docker 的环境（如本沙箱 Ubuntu 24.04）可直接 `apt-get install -y postgresql redis-server`，
> 再 `service postgresql start` / `service redis-server start` 起服务；随后 `ALTER USER postgres PASSWORD 'postgres';` 建库口令。

---

## 3. 初始化数据库（首次 / 重建）

```bash
cd "$(git rev-parse --show-toplevel)"                  # 仓库根（$REPO_ROOT）
export PGPASSWORD=postgres

# 建库（已存在会报错，可忽略）
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE ai_coach;"

# 建表（36 表；与 Alembic 0001 同源，二者择一）
psql -h 127.0.0.1 -U postgres -d ai_coach -v ON_ERROR_STOP=1 -f data/sql/001_schema.sql

# 种子（CSV 用 utf-8-sig 兼容 BOM；$PY = 你的 ≥3.12 解释器）
# 注意：sku_catalog / ai_knowledge 必须一并导入，否则订单与 AI 相关测试会因缺参照数据失败
"$PY" data/load_seeds.py \
  --dsn "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach" \
  --file food:data/seeds/food_full.csv --file food_alias:data/seeds/food_alias_full.csv \
  --file sku_catalog:data/seeds/standard_sku.sample.csv \
  --file ai_knowledge:data/seeds/ai_knowledge_full.jsonl
```

---

## 4. 后端：测试 / 起服务（无 Mock Server）

```bash
# 回归测试（真实 PostgreSQL；conftest 函数级清库保证隔离）
cd "$(git rev-parse --show-toplevel)/backend"
DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach" \
  "$PY" -m pytest -q

# 起后端（本地调试）
DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach" \
  "$PY" -m uvicorn app.main:app --reload --port 8000
```

- **`contracts/mock/`（mock server + canned routes）已删除**，不要再用 `node contracts/mock/server.mjs`，也没有 `VITE_USE_MOCK`/`mock-code` 这条路。后端同样删了"无微信凭证 → `openid = "mock-"+md5(code)`"分支：`WECHAT_APPID`/`WECHAT_SECRET` 任一为空时 `POST /api/auth/login` **明确 1001**。
- 登录用例的离线可跑性由 `backend/tests/conftest.py` 的 autouse `_stub_code2session` 承担（`openid = "test-" + sha256(code)[:16]`，同 code 同 openid），用例永不访问 `api.weixin.qq.com`。
- 真链路自验（本机实测，2026-10-02）：解 JWT payload 看 `openid` 前缀即知真假；假 code 返回 `1001 + "invalid code, rid:…"`（`rid` 由微信侧给出）。
- 后台账号来自 `data/sql/003_phase3_admin_seed.sql`（`admin_user` 表由 `001_schema.sql` 建，initdb.d 与 `load_seeds.py` 都不含后台账号）；口令见该文件头注释。`POST /api/admin/login` → token → 打 `/api/admin/*` 是 CI 冒烟的鉴权通道。
- **测试基线**：以当次实跑为准（每次迭代会变化，不要引用过期数字）。当前阶段基线见 `AGENTS.md §7.1`。
- ⚠️ **跑完 pytest 必须重新导入种子（DB-5）**：`backend/tests/conftest.py` 的 `_TRUNCATE_TABLES` 含 `food` / `food_alias`，全量回归后这两张种子表被清空。此时若继续做依赖食物库匹配的验证（RAG 检索、拍照识别候选、ILIKE 回落、`/api/meal` 相关），会命中 0 行并被误判成代码缺陷。回到 §3 的 `load_seeds.py` 命令重导即可。
- AI 无 Key 时自动落 mock（`backend/app/ai/`）；连通性自检：`"$PY" backend/scripts/ai_hello.py --task chat|vision`。

---

## 5. 前端：uni-app（交付物=微信小程序；H5 只是视觉回归通道）

```bash
cd "$(git rev-parse --show-toplevel)/miniapp"
npm install
npm run type-check          # vue-tsc --noEmit，必须 0 错误
npm run build:mp-weixin     # 【交付物】微信小程序产物 → dist/build/mp-weixin
npm run build:h5            # 【非交付物】H5 产物 → dist/build/h5，只为 agent-browser 视觉核对
npm run dev:h5              # 【非交付物】H5 开发服务（Vite，默认 http://localhost:5173）
```

- **本项目只交付微信小程序**：H5 不进部署面（`deploy/Dockerfile.miniapp` 已删；`deploy/nginx.conf` 的 server 级 `root`、静态缓存正则、`location /` SPA 回退三段已删，未命中 `/api/ /admin/ /uploads/ /healthz` 即 404）。
- 但 `build:h5`/`dev:h5` 与源码里所有 `#ifdef H5` 分支**刻意保留**——`#ifdef H5` 只有 H5 构建才会编译，删掉构建就等于没人守这条通道。CI 的 frontend job 因此仍跑 `build:h5`（见 `.github/workflows/ci.yml` 该步注释）。
- **前端交付门禁**：`type-check` 0 错误 + `build:mp-weixin` 通过；UI/前端波次另跑 `build:h5` 做视觉回归核对（做法见 §6）。
- 开发态基址：`.env.development` 的 `VITE_API_BASE=http://localhost`（本机 compose 的 nginx :80 反代 `/api` → api:8000），**不再指向 9000 的 mock server**；`request.ts` 无内置默认值（`?? ''`），小程序端为空串会启动即抛（`MODE==='test'` 豁免）。

---

## 6. 浏览器自动化验收（agent-browser）

**用途**：对**本地渲染的 H5 页面**（`build:h5` 产物 / `dev:h5` 服务 / 管理后台）做真实渲染与交互验收——布局、样式、路由跳转、点击、表单、响应式断点。可作为前端/UI 波次双审查的一环（见 `AGENTS.md §5`）。
**注意口径**：H5 在本项目**不是部署物**（见 §5），所以这里是"本地视觉回归通道"，不是"线上一致性验收"；小程序独有分支（`#ifdef MP-WEIXIN`）在此看不见，`#ifdef H5` 分支也只有这条通道能看见。

> **本仓库已内置该能力的 skill**：`.agents/skills/agent-browser/SKILL.md`（**使用前先读它**）。该文件是发现入口，明确要求：动手前先执行 `agent-browser skills get core` 载入与**已安装版本一致**的 workflow / 命令参考，**勿凭记忆敲命令**；页面之外的场景（Electron、exploratory QA 等）用 `agent-browser skills list` 查专用 skill。

> **能力边界**：微信小程序（`mp-weixin`）运行时是微信客户端，**agent-browser 无法驱动**。小程序侧请用**微信开发者工具**导入 `miniapp/dist/build/mp-weixin` 预览；自动化可用 `@dcloudio/uni-automator`（依赖微信开发者工具）。agent-browser 只用于 H5 / 浏览器页面。

**安装（未安装时）**

```bash
npm i -g agent-browser && agent-browser install
agent-browser skills get core        # 载入用法指南（随已安装版本更新，必看，见上方 skill）
```

**H5 视觉回归流程（无 Mock 之后的可执行做法）**

```bash
# 0) 后端必须在跑：本机全栈跑在 **WSL 里的 compose**（工程名 ai-coach，nginx :80 → /api → api:8000）。
#    Git Bash 侧看不到 docker，必须经 WSL 调用；<repo> = 仓库在 WSL 下的路径（如 /mnt/e/workspace/.../ai-coach）：
timeout 60 wsl.exe -e bash -lc 'docker compose -f <repo>/deploy/docker-compose.yml ps'
#    H5 从任意端口起都能直打 http://localhost/api（后端 CORS 放行 authorization/content-type）

# 1) 另开终端起 H5 dev server（或 build:h5 后自起静态服务）
cd "$(git rev-parse --show-toplevel)/miniapp" && npm run dev:h5      # http://localhost:5173

# 2) 打开并核对
agent-browser open http://localhost:5173
agent-browser snapshot                                # 无障碍树：核对关键元素是否渲染
agent-browser screenshot --path /tmp/h5-index.png     # 截图留证
```

**验收要点（示例）**：5 个 Tab 与 FAB 可见；首页评分环 / 热量环形图渲染且数字与接口一致；空态 / 错误 / 无权限组件按预期出现；浏览器控制台无报错。
**登录链路不在此验收**：H5 侧无微信容器，`uni.login` 拿不到 code，真登录以**微信开发者工具**的小程序侧为准（判据见 §4：解 JWT 看 `openid` 前缀）。

> `scripts/h5-compat-check.sh` 名字里有 h5，但现在**只跑管理后台**（`admin/dist` 多档 viewport 浏览器渲染）；miniapp H5 的构建与三档渲染段已删除。要核对小程序 H5 请按上面这条流程手动跑。

---

## 7. 常见问题

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| `pip install` 装不上依赖 | 解释器 < 3.12（如系统 `python3` 为 3.14） | 换成任意 ≥3.12 的解释器（见 §1.1） |
| pytest 大量假失败 / 数据互相污染 | 多个 Agent 并行共享同一 PG，`conftest` 的 `TRUNCATE` 互清 | 按 `AGENTS.md §3` 隔离（独立 schema / Redis db / 端口）；无法隔离则串行 |
| pytest 报连接失败 | PG 未起 / 未建表 | 见 §2、§3 |
| 限流用例结果异常 | `conftest` 故意把 Redis 指向不可达端口（6390）以走进程内兜底 | 属预期，无需修 |
| H5 端口被占用 | 5173 被占 | `npm run dev:h5 -- --port 5174`，agent-browser 打开对应端口 |
| `agent-browser` 命令不存在 | 未安装 | `npm i -g agent-browser && agent-browser install`；用法见 `.agents/skills/agent-browser/SKILL.md` |
| Git Bash 里 `docker ps` 空 / 命令不存在 | 本机 docker 跑在 **WSL**，Windows 侧没有 daemon | 一律 `timeout 60 wsl.exe -e bash -lc 'docker …'`；裸 `/workspace` 之类路径会被 MSYS 改写，需要时加引号或用 `/mnt/e/...` |
| 改了根 `.env`、重启 compose 却没生效 | `deploy/docker-compose.yml` 的 `env_file` 标了 `required: false`——`.env` 不存在时**静默跳过**，不报错 | 先确认 `.env` 真的在仓库根且键名正确，再怀疑代码；必要时 `docker compose config` 看渲染后的变量 |
| 换了 `JWT_SECRET` 后前端在 index↔login 之间互弹 | 已签发的 access/refresh token 集体失效，`request.ts` 刷新失败即 reLaunch 登录页 | 清 storage（工具「清除缓存」）或重新登录，属预期而非死循环 bug |
| 小程序侧改了源码/重建产物后工具里没变化 | 微信开发者工具导入的是 `dist/build/mp-weixin`，且**外部重建不会自动重载**（WeappLog 里 `DevtoolsFileWatcher … false`） | 先确认产物已重建，再 `cli quit` + `cli open`（单跑 `cli open` 不触发重编译） |
| 登录返回 1001 | 无微信凭证（`WECHAT_APPID`/`WECHAT_SECRET` 为空）或 code 无效——mock 登录分支已删，不再有假身份 | 见 §4：本地要真登录就在根 `.env` 填测试号；跑测试不需要凭证（conftest 打桩） |

---

## 8. 与 AGENTS.md 的关系

- 本文件 = 环境**确认清单**；`AGENTS.md §7.1` = 给子 Agent 任务书**原样引用的环境事实块**。二者内容须一致。
- 变更环境（升级版本 / 改端口 / 换 DSN）时：**先改本文件，再同步 `AGENTS.md §7.1`**。
- **解释器路径仅为当前环境示例**：本文件不假设虚拟环境或固定目录，任何环境请按 §1.1 探测自己的 ≥3.12 解释器（`AGENTS.md §7.1` 中的具体路径同理）。

---

## 9. Phase 5 环境事实（本沙箱实测，2026-09-29 记录 / 2026-09-30 复验 / 2026-10-01 再次复验刷新）

> 结论：**测试不用容器**，一律原生 PG/Redis + `uvicorn`（容器虽已可用，见下表，但本次交付走原生路径）。以下为实测事实，子 Agent 任务书可直接引用，勿重新探测。

| 能力 | 实测结论 | 影响 |
| --- | --- | --- |
| Docker / podman / containerd | **Docker 可用**（2026-10-01 复测）：`27.5.1`，daemon 在线，`CapEff=000001ffffffffff`（含 `CAP_SYS_ADMIN`），`docker run --rm hello-world` 实测跑通、镜像可拉取；`docker compose v2.33.0` 插件齐备 | 与旧记录相反：`deploy/docker-compose.yml` **可实跑**。本次交付仍用原生 PG/Redis（`psql`/`redis-cli` 需落在指定版本），容器仅作备选路径 |
| 压测工具 | k6/locust/hey/wrk/ab/jmeter/vegeta 全部**未安装**；`promtool` 未安装 | F5 用 `httpx`(0.28.1, 已装) + asyncio 写 harness；⚠️ 容量上限见下 |
| Python | **3.12.3**（2026-10-01 复测，`backend/.venv`；系统 `python3` 为 3.11.1 **不满足**，须显式用 `/usr/bin/python3.12` 建 venv）；测试依赖 `pytest 8.4.2` / `pytest-asyncio` 在 `pyproject.toml` 的 `[dev]` extra 里，`requirements.txt` **不含** | 建 venv 需先 `apt-get install python3.12-venv`；跑测试须额外装 dev extra（`pip install "pytest>=8.2,<9.0" "pytest-asyncio>=0.23,<1.0"`），否则 `pytest` 缺失 |
| `prometheus_client` | **已安装**：`backend/requirements.txt:16` = `prometheus-client==0.26.0`，`backend/.venv` 实测可 import，`/metrics` 返回 200 | F9 `/metrics` 无需再手工补装；若新建 venv，按 §4 `pip install -r requirements.txt` 即得 |
| agent-browser | 0.27.0；系统 Chrome 可用（`/usr/bin/google-chrome`、`/usr/bin/chromium`） | F7/F3/F4 可做 H5 真实渲染；mp-weixin 仍不可（见 §6）。注：§9 与 §1 曾写 0.38.1，实为本沙箱版本漂移，已统一为实测值 |
| Node / npm | v22.13.1 / 11.9.0（2026-10-01 复验）；`miniapp/node_modules` 与 `admin/node_modules` **均已装** | 两端可直接 `type-check`/`build`；换沙箱后需各自 `npm install` |
| 内存 / CPU | 2026-10-01 复测：`/proc/meminfo` MemTotal ≈ **123.3 GiB**、`nproc` = **32**（2026-09-30 记录为 7.8 GiB / 4 核，2026-09-29 为 4 GiB / 3 核）。沙箱配额随会话漂移，**以当次探测为准** | 配额充裕，压测仍建议串行以免相互干扰；起服务前先 `awk '/MemTotal\|MemAvailable/' /proc/meminfo` 确认 |
| 微信支付商户号 / 微信开发者工具 / AI Key | 均无 | F1 真机联调、F7 小程序真机、F3 识别准确率不可真跑 → 产出产物 + 替代验证 |

**F5 压测约定**：本机起 `uvicorn`（`127.0.0.1:8000`，单 worker 可控）后串行压测；百万行分页用 `EXPLAIN ANALYZE` + 实测耗时（真实可做）；100 并发 5 分钟 soak 需按上表**当次实测内存配额**降低并发或缩短时长，并在报告中标注实际参数与偏差。
