# 前端 miniapp + 管理后台 + UI 规范 + 页面交互 + 部署运维 全量核对报告

> ⚠️ **已过期归档**（2026-09-30 迁入 `docs_process/archive/`）：本报告为 2026-09-30 分域核对分报告（slot3，前端 / 部署 / CI，基线 `dbbf198`），结论已并入同日主 Agent 定案汇总。**取代真源：`docs_process/archive/review_20260930_summary.md`**。本文仅留档。

**审查 slot**: 3（只读审查 Agent）  
**审查日期**: 2026-09-30  
**审查分支**: docs/env-check-0930（内容 = origin/develop @ dbbf198）  
**审查范围**: A-H 全量（前端 miniapp/admin + UI 规范 + 页面交互 + API 契约 + H5 渲染 + 部署运维 + CI）

---

## 一、结论摘要

- **不符项总数**: 16 条
  - **P0 阻断**: 2 条
  - **P1 真实缺陷**: 4 条
  - **P2 轻微**: 9 条
  - **P3 建议**: 1 条
- **整体结论**: **FAIL**（存在 P0 阻断项）
- **构建门禁**: 
  - ✅ miniapp type-check 通过（0 错误）
  - ✅ miniapp build:h5 通过
  - ✅ miniapp build:mp-weixin 通过
  - ✅ admin type-check 通过
  - ✅ admin build 通过
- **H5 真实渲染验收**: ✅ 已完成（agent-browser 0.27.0 实跑，登录页渲染正常，截图存 /tmp/h5-login.png）

---

## 二、实跑原始摘要

### 2.1 构建门禁（2026-09-30 实跑）

| 命令 | 结果 | 关键输出 |
|------|------|----------|
| `cd miniapp && npm run type-check` | ✅ 通过 | `vue-tsc --noEmit` 无错误 |
| `cd miniapp && npm run build:h5` | ✅ 通过 | `DONE Build complete.` 产物路径 `dist/build/h5` |
| `cd miniapp && npm run build:mp-weixin` | ✅ 通过 | `DONE Build complete.` 产物路径 `dist/build/mp-weixin` |
| `cd admin && npm run type-check` | ✅ 通过 | `vue-tsc --noEmit` 无错误 |
| `cd admin && npm run build` | ✅ 通过 | `built in 5.56s` 产物路径 `admin/dist/` |

### 2.2 H5 真实渲染验收（agent-browser 实跑）

**执行命令**:
```bash
cd /data/ai-coach/miniapp && npm run dev:h5 -- --port 5174
# 服务启动于 http://localhost:5174

agent-browser open http://localhost:5174
agent-browser screenshot /tmp/h5-login.png
agent-browser snapshot
```

**验收结果**:
- ✅ 登录页渲染正常（logo、标题、登录按钮、协议文案均可见）
- ✅ 截图已存 `/tmp/h5-login.png`
- ⚠️ 登录→首页跳转未验证（需 Mock 服务支持，本次未启动 Mock）
- ⚠️ 首页评分环/热量环形图未验证（需登录后访问）
- ⚠️ 空态/错误/无权限组件未验证（需特定场景触发）

**结论**: H5 验收**部分完成**，登录页渲染无问题，深层页面需 Mock 服务配合验证。

---

## 三、分级问题清单

### P0 阻断（2 条）

| # | 级别 | 文档出处 | 代码位置 | 问题 | 证据 | 建议修法 |
|---|------|----------|----------|------|------|----------|
| 1 | P0 | docs/split/08 §10.3 "Dockerfile.backend：python:3.12-slim + **多阶段构建**" | deploy/Dockerfile.backend（整文件） | Dockerfile 实际为**单阶段**（仅一个 `FROM python:3.12-slim`），与文档"多阶段构建"明确不符 | `grep -c "^FROM" deploy/Dockerfile.backend` → 1 | 要么实现多阶段（builder→runtime），要么修改文档去掉"多阶段"措辞 |
| 2 | P0 | docs/split/08 §10.3 "Dockerfile.miniapp：node:20 编译 → nginx 托管静态 H5" | deploy/ | **`Dockerfile.miniapp` 文件不存在**；`ls deploy/Dockerfile*` 仅 `Dockerfile.backend` | `ls deploy/Dockerfile*` 仅返回 Dockerfile.backend | 补齐 Dockerfile.miniapp，或在文档标注"待交付" |

### P1 真实缺陷（4 条）

| # | 级别 | 文档出处 | 代码位置 | 问题 | 证据 | 建议修法 |
|---|------|----------|----------|------|------|----------|
| 3 | P1 | docs/split/03 §5.1-5.5 原型底部 tabBar：`🏠首页 🍽️吃什么 🏃运动 💬社区 👤我的` | miniapp/src/pages.json:165-186 | 实际 tabBar 为 `首页/记录/社区/商家/我的`，与文档原型"首页/吃什么/运动/社区/我的"**完全不一致**（"吃什么""运动"被"记录""商家"替换） | pages.json:165-186 list 顺序 text 字段 | 产品/设计定案：要么改 pages.json 对齐文档，要么更新 03 文档原型；tabBar 文案历史有"记录/商家 vs 吃什么/运动"之争，需主 Agent 拍板 |
| 4 | P1 | docs/split/03 §5.2/5.3（"吃什么""运动"作为独立 Tab 页） | miniapp/src/pages/eat/eat.vue、pages/record/sport.vue | 文档中"吃什么""运动"是 Tab 级入口，代码中 `pages/eat/eat` 仅作为非 tabBar 子页注册；"运动"被拆到 `record/sport` 下，无独立 Tab | pages.json 中 eat/sport 不在 tabBar.list | 与 #3 一并定案 |
| 5 | P1 | docs/split/02 §4.1 设计令牌（`--brand`/`--danger`/`--warn`/`--text-3` 等） | miniapp/src/pages/index/index.vue:226-310、profile.vue:95、record/camera.vue:276、ai/chat.vue:348/407/503、invite/invite.vue:263/273、order/confirm.vue:432、community/post.vue:13/19 | 多处**硬编码 hex 色值**绕过令牌（如 `#ef4444`/`#f59e0b`/`#22c55e`/`#3b82f6`/`#9ca3af`/`#f3f4f6`/`#ffffff`），未使用 tokens.scss 变量或 CSS 变量 | grep `#[0-9a-fA-F]{6}` 命中 20+ 处（详见证据列） | 统一替换为 `var(--brand)`/`var(--danger)` 等，或 SCSS `$brand` 等；尤其 index.vue 的状态色函数应返回令牌引用 |
| 6 | P1 | contracts/openapi.yaml（72 路径 / 78 ops） | miniapp/src/api/*.ts | 前端 API 层未完全覆盖契约：约 **17 个路径前端未调用**（含 `/api/subscription*` 2 个、Phase 5 新增 `/api/track` 与 `/api/order/{id}/refund`、社区子资源 `/api/community/{group,battle,challenge,post,supervise}/{id}/*` 约 10 个、`/api/meal/{id}` 与 `/api/meal/recognize`、`/api/ai/weekly-comment`、`/api/order/notify`） | openapi 72 路径 vs miniapp api/*.ts grep 49 路径；差集见上 | 按排期（09 文档）补齐：订阅链路、退款、track、meal 详情/识别、社区子资源交互 |

### P2 轻微（9 条）

| # | 级别 | 文档出处 | 代码位置 | 问题 | 证据 | 建议修法 |
|---|------|----------|----------|------|------|----------|
| 7 | P2 | .env.example（仓库根） | backend/app/core/config.py | config.py 54 字段、.env.example 56 键；API_PREFIX/API_PORT/LOG_LEVEL/AI_*/MS_*/ADMIN_INIT_* 等均已覆盖。真正缺失的仅 **6 个有默认值的运维调优项**：`DB_POOL_SIZE`(=10)、`DB_POOL_MAX_OVERFLOW`(=20)、`DB_POOL_RECYCLE`(=1800)、`DB_POOL_DISABLED`(=False)、`IDEMPOTENCY_ENABLED`(=True)、`IDEMPOTENCY_TTL_SECONDS`(=300)。env 侧多出 POSTGRES_*/REDIS_HOST/PORT/NGINX_PORT 为 compose 用，合理 | `comm -23` config 字段 vs env 键，差集仅上述 6 个 | 补齐 6 个字段到 .env.example（带注释说明默认值），或标注"高级调优，一般无需配置" |
| 8 | P2 | dev_env.md §9 第 204 行 | backend/requirements.txt:16、backend/app/main.py:133 | dev_env.md §9 表格仍写"prometheus_client **未安装**"，但实际 requirements.txt:16 已含 `prometheus-client==0.26.0`，main.py:133 调用 `install_metrics(app)`，`/metrics` 端点已实现且可达。**纯文档陈旧问题**，代码无缺陷 | `grep prometheus backend/requirements.txt` → `prometheus-client==0.26.0`；`grep install_metrics backend/app/main.py` → 第 133 行 | 更新 dev_env.md §9 表格，把 prometheus_client 改为"已安装 0.26.0" |
| 9 | P2 | AGENTS.md §7.2 "两份 TS 副本由主 Agent 单点同步" | contracts/ts/api.d.ts vs miniapp/src/types/api.d.ts | `diff` 结果为空，**两份副本当前一致** ✅；但缺乏自动化同步校验，下次契约变更有漂移风险 | `diff contracts/ts/api.d.ts miniapp/src/types/api.d.ts` 无输出 | 建议在 CI 加一步 `diff` 检查，防止两份副本静默漂移 |
| 10 | P2 | docs/split/02 §4.14 动效 / Sass 现代语法 | miniapp/src/styles/mixins.scss:75 + CButton.vue:17-18、merchant/detail.vue:230-232 等 | build 输出大量 Sass `mixed-decls` deprecation 警告（声明跟在嵌套规则后），未来 Sass major 版本会破坏构建 | build:h5 输出 deprecation warning 块 | 把 `font-size`/`color` 等声明移到 `&:active` 嵌套之前 |
| 11 | P2 | docs/split/08 §10.4 "80 强制跳 443" | deploy/nginx.conf | 80 server 块中 `return 301 https://...` 被注释掉，仅以注释说明"生产启用"；文档措辞为"80 强制跳 443"（无"生产才跳"限定） | nginx.conf 第 26 行 `# return 301 https://$host$request_uri;` | 文档补"生产环境"限定词，或 nginx.conf 默认启用跳转 |
| 12 | P2 | admin build 产物大小 | admin/dist/assets/index-CpRq3zjo.js | 单 chunk 1208 kB（gzip 388 kB），Vite 警告 >500 kB；element-plus 全量打入 | build 输出 | 配 `build.rollupOptions.output.manualChunks` 拆 element-plus |
| 13 | P2 | .github/workflows/ci.yml | ci.yml `frontend` job | CI 用 `node-version: 20`，dev_env.md §1 期望 Node≥20（满足）；但本机实测 Node 22.23.2，CI 与本机环境有版本差（不阻断，仅记录） | ci.yml setup-node 20 | 可保持；CI 与本机版本差在合理范围 |
| 14 | P2 | contracts/openapi.yaml 12 个 /api/admin/* 路径 | admin/src/api/admin.ts | admin 覆盖 11/12，仅缺 `/api/admin/merchant-skus/{id}/status` | grep admin api 11 路径 | 补齐或从契约删除 |
| 15 | P2 | docs/split/08 §10.7 日志落盘 `/var/log/app/` | deploy/docker-compose.yml:65、105 | 文档要求日志落盘 `/var/log/app/`，docker-compose.yml 已配置 volume 挂载 `logs:/var/log/app`，但 backend 代码中**未见实际写入逻辑**（grep `"/var/log"` backend/ 无匹配） | `grep -rn "/var/log" backend/app/ --include="*.py"` 无匹配 | 在 backend/app/core/logging.py 或 main.py 中配置文件日志 handler，输出到 `/var/log/app/app.log` |

### P3 建议（1 条）

| # | 级别 | 文档出处 | 代码位置 | 问题 | 证据 | 建议修法 |
|---|------|----------|----------|------|------|----------|
| 16 | P3 | dev_env.md §1 "agent-browser 最新 = 0.38.1" | 沙箱实测 | agent-browser 实际 0.27.0，偏旧 11 个小版本；但实测可正常完成 open/snapshot/screenshot，功能无缺失 | `agent-browser --version` → 0.27.0；H5 验收实跑成功 | 有空时升级到 0.38.x 即可，不影响功能 |

---

## 四、已验证一致的部分

- ✅ miniapp 注册 25 页（pages.json），对应 25 个 .vue 文件全部存在，路径与命名一致
- ✅ miniapp type-check / build:h5 / build:mp-weixin 全部通过（exit 0）
- ✅ admin type-check + build 全部通过
- ✅ tokens.scss 完整落地 §4.1-§4.4 所有令牌（色/字号/间距/圆角/阴影），且以 SCSS 变量 + CSS 变量双形式输出
- ✅ 通用状态组件（CEmpty/CError/CNoPermission/CNoBenefit/CSkeleton）齐备且在页面中实际接入（非仅文件存在）
- ✅ request.ts 实现：BASE_URL 默认 `http://localhost:9000`（指向 Mock）/ Bearer token 注入 / 401 静默刷新 `/api/auth/refresh` / 业务 code=1001 触发刷新 / 成功解包 envelope.data / 防刷新死循环的 `_retried` 标记 — 与 AGENTS.md §7.2 与 05 文档一致
- ✅ .env.development 指向 `http://localhost:9000`（Mock 端口），可用
- ✅ contracts/openapi.yaml 实测 72 路径 / 78 ops，与 AGENTS.md §7.2 声明完全一致
- ✅ 两份 TS 副本（contracts/ts/api.d.ts vs miniapp/src/types/api.d.ts）当前 diff 为空，一致
- ✅ miniapp src/api/*.ts 引用 49 个 API 路径，覆盖 openapi 72 路径中约 45 个（去重后）；admin src/api/admin.ts 引用 11 个 /api/admin/* 路径，覆盖 12 个 admin 路径中的 11 个
- ✅ prometheus-client==0.26.0 已写入 backend/requirements.txt（但 dev_env.md §9 表格未同步更新，见 #8）
- ✅ deploy/docker-compose.yml 包含 postgres/redis/api/worker/nginx 服务，卷持久化 pgdata/redisdata/uploads/logs，与 §10.3 大体一致
- ✅ deploy/nginx.conf 含 /api/ 反代、/admin/ 静态、/uploads/ 媒体、限流 100r/s、静态缓存 7 天、HTML 不缓存 — 与 §10.4 一致
- ✅ deploy/prometheus/ 与 deploy/grafana/ 与 backend/app/observability/ 目录存在，对应 §10.7 监控落地图
- ✅ backend/app/observability/metrics.py 已实现 `/metrics` 端点，main.py:133 调用 `install_metrics(app)`
- ✅ CI (.github/workflows/ci.yml) 含 backend（lint+test+真实 PG/Redis+种子导入）+ frontend（type-check+双端 build）+ admin（build）三个 job，覆盖文档承诺
- ✅ CI 中 seed 步骤已改用 `rag_knowledge.sample.jsonl`（非 `ai_knowledge_full.jsonl`），与仓库 data/seeds/ 实际文件名一致
- ✅ miniapp tabBar 颜色值（`color: #6b7280`、`selectedColor: #22c55e`）与 tokens 中 `--text-2`/`--brand` 一致
- ✅ H5 真实渲染验收（agent-browser）登录页渲染正常，截图存 /tmp/h5-login.png

---

## 五、未执行 / 待确认项

| 项 | 原因 | 验证方法 |
|---|------|----------|
| **H5 深层页面验收** | 登录→首页跳转、首页评分环/热量环形图、空态/错误/无权限组件需 Mock 服务配合 | 启动 Mock 服务 `node contracts/mock/server.mjs`，登录后访问首页验证 |
| **contracts/mock/routes.mjs 覆盖度** | mock server.mjs 56 行 + routes.mjs 432 行，未逐条核对 78 ops 中 Mock 实现多少 | 主 Agent 派专项核对 |

---

## 六、备注

- 本报告基于 develop 事实（dbbf198），已纠正前一轮误用 main 的错判。
- Sass mixed-decls 警告虽不阻断，但累积 20+ 处，建议下一波统一整改，避免未来 Sass major 版本升级时集中爆雷。
- tabBar 文案之争（#3/#4）属产品决策，需主 Agent 与用户定案，本报告不定案。
- H5 验收已实跑（agent-browser 0.27.0），登录页渲染无问题；深层页面需 Mock 服务配合验证。
