# current.md · 功能完成情况清单

> **对象**：`develop` 分支
> **依据**：`docs/AI饮食管控教练_全栈开发交付文档.md`（唯一真源，基线 `015d736` 冻结只读、全程一字未动）
> **结构**：本文件**只有两部分**——**一、已完成** / **二、待完成 · 优化**。
> **处置纪律（AGENTS §7.2）**：① 文档对、代码错 → 改代码补测试；② 代码做到、文档口径过时/文档自相矛盾 → 在第二部分登记，等产品拍板；③ 文档要求的 P0 未实现 → 登记排期。**禁止改文档**。
> **当前门禁（2026-10-01 定案）**：全量 pytest **564 passed / 0 failed / 0 skipped**；契约一致性 **80 passed**（**75 路径 / 82 操作**，与实现、mock 双向 diff 0）；`miniapp` type-check **0 错误** + `build:mp-weixin` / `build:h5` ✓；`admin` build ✓；alembic **head 0008**；H5 E2E 点击流 **21/21 PASS**；CI 三 job 本地复现全绿。
> **更新时间**：2026-10-01（重构为两段式；并入文档↔实现差异复核结果）

---

## 一、已完成

### 1.1 后端服务（FastAPI）

- 微信登录（code2session → JWT access 2h + refresh 7d）、用户与权益初始化
- 身体档案建档（性别/身高/体重/年龄/目标/活动水平）GET/POST
- 热量引擎：BMR（Mifflin-St Jeor）、PAL、TEE、TEF 10%、NEAT、缺口、`today_left`（手算对拍误差 0）
- 热量账户首页/详情/趋势：`account/today`、`account/trend`、`daily_snapshot` 0 点生成 + 幂等
- 步数同步与校准：`steps/sync`，逐时步频 → MET，状态法与步数法加权
- 饮食记录 CRUD（`meal` POST/PUT/DELETE/list，写后重算当日摄入）
- 运动记录：`sport` POST/list
- 食物搜索：`food/search`（tsvector + alias）
- 体重记录 CRUD + 趋势
- 提醒订阅：订阅消息（餐前 11:00/17:00、深夜防崩塌）+ Redis Streams 调度
- 拍照识别：`meal/recognize`（图片 → COS → 视觉 API → 匹配 food 表 → 置信度 <0.7 需确认）
- AI 对话：`ai/chat` + RAG 检索 `ai_knowledge` + `ai/times`，扣减配额、不足返 4001、限流 20/min
- 饭点决策：`ai/recommend`（菜单推荐 + 绿/黄/红健康等级）
- 商家：`merchant/list`（LBS/评分/券排序）、`merchant/{id}`、标准 SKU 目录 + 权重分 40/40/20 + haversine
- 券池：`coupon/list`（领券/用券）
- 订单交易：创建（服务端重算 pay_amount）、JSAPI 预下单、notify 验签/幂等/防篡改、核销码一次性、15 分钟超时取消释放券
- 社区五种社交：监督、兴趣社群、约战、挑战赛、动态（发帖/点赞/评论）
- 内容安全：微信 msgSecCheck + imgSecCheck，违规入审核队列
- 管理后台 API：`admin/dashboard`、目录/商家入驻审核/价格区间/券池/订单/内容管理
- 埋点上报：`track` 接口（event 1~64 字符）+ `/metrics`
- 统一错误码 16 个（`0/1001/1002/2001/3001/4001/4002/4102/5001~5004/6001/7001/429/500`），HTTP 映射正确
- 安全项：越权 404+3001、SQL 注入、幂等重放 409+4002、限流 429 全部实跑通过
- **邀请 → AI 次数扩容**：档位达标同步提升 `ai_times_left`，每日重置按 tier
- **生产环境默认密钥守卫**：`ENV=prod` 且 JWT_SECRET/ADMIN_INIT_PASSWORD 为默认值则拒绝启动
- **Redis 客户端跨事件循环修复**：客户端与事件循环绑定，loop 变更即重建
- **邀请规则变更落地**：注册即有效 / `INVITE_TIERS=[1,3,10]` / 实时生效 / 无期限 / 同设备防刷 4102 / 废除双方发券；删批量调度与有效期字段；0007 迁移
- **merchant 位置字段 GEOMETRY 化**：PostGIS + 0008 迁移 + GIST 索引 + `ST_DistanceSphere`，契约入出参 lat/lng 不变
- **AI Provider 收敛为 LLM/VLM 统一 OpenAI 兼容协议**：`LLM_*`/`VLM_*` env 配置，删 8 个厂商适配器

### 1.2 前端小程序（uni-app + Vue3 + TS）

- 登录页、建档页、首页（热量环形图 + 摄入/运动明细 + AI 卡 + 快捷服务 + 券提醒）
- 热量账户详情页
- 拍照记录页（拍照 → 识别 → 确认/修正分量 → 写入）、饮食记录列表
- 运动页 + 添加运动页、记录中枢页
- 吃什么（AI 决策）页
- AI 对话页（剩余次数、次数尽「邀请好友解锁」）
- 商家列表/详情、订单确认、订单列表、券包
- 社区页 + 监督/兴趣社群/约战/挑战赛/动态 5 个子页
- 我的、邀请裂变、体重记录与趋势
- 通用状态组件（加载骨架/空/错误/无权限/未开通权益）
- 页面路由：代码 **26 页**、TabBar **5 个**（首页/吃什么/运动/社区/我的），与文档 §3.2 一致
- **登录后回跳原页**：统一 `nav.ts`，跳登录携 `?redirect=`，防开放重定向/循环
- **AI 满意度评分埋点**：AI 回答 1~5 星 → `track('ai_rating')`

### 1.3 管理后台（Vue3 H5）

- 管理员登录、仪表盘
- 商家管理、SKU 管理（区间定价校验）
- 券池管理、订单管理、内容审核
- 构建通过（内嵌 vue-tsc type-check + vite build ✓）

### 1.4 契约 / 数据 / 部署

- 契约冻结：`contracts/openapi.yaml` **75 路径 / 82 操作**，与实现、mock 双向 diff 0
- pydantic schema 与契约响应字段差异 0；TS 双副本逐字一致
- Mock Server 覆盖契约全部操作
- 数据库 **36 表**三方（schema.sql ↔ ORM ↔ 实际库）列级差异 0
- 种子数据：food 1750 / food_alias 342 / sku_catalog 5 / ai_knowledge 50
- Alembic 迁移（0001~0008：0007 邀请规则 / 0008 merchant PostGIS）与 schema.sql 同源
- 部署产物：`deploy/`（nginx、prometheus 告警、grafana 看板、灰度方案；PG 镜像 postgis/postgis:16-3.4）
- Dockerfile.backend 多阶段构建 + 非 root 用户
- CI 补 black 非阻断检查
- 冒烟用例 **55 条**（文档要求 50，超出非缺失）
- 测试门禁：全量 pytest **564 passed / 0 failed / 0 skipped**；type-check 0 错误；双端 build + admin build 全部通过

### 1.5 E2E 与 CI 验证（2026-10-01 实测，编排 agent 复验）

- **H5 E2E 点击流：21/21 断言 PASS**（playwright + 系统 Chromium）：5 Tab 切换、邀请页新口径文案断言（「注册成功即算有效邀请」「1/3/10」「同设备只计 1 次」）+ 分享按钮交互、AI 对话页、商家列表（`/api/merchant/list` 请求发出）、记录中枢；登录走 mock code2session（`WECHAT_SECRET` 空）+ 后端签发 JWT 注入 localStorage；aiohttp 反代 :8080 同源接入 `/api`。控制台**严重报错 0**；轻微 2 类均为预期降级（监督空数据 3001 的 404 envelope、COS 占位域名 DNS 失败）。辅助脚本/截图留 /tmp 不入仓库
- **CI 复现（按 `.github/workflows/ci.yml` 三 job 逐条）**：backend **564 passed / 0 failed / 0 skipped**（起真实 redis:7 后原 2 例锁定用例转执行全过；ruff/black 非阻断存量告警与 CI 口径一致）；frontend type-check + `build:mp-weixin`/`build:h5` ✓；admin `npm ci` + build ✓。偏差仅环境性（postgis:16-3.4 镜像替代 postgres:16、Python 3.11 vs 3.12）→ **推送 GitHub Actions / Gitea Actions（同构 runner）将全绿**
- **docker compose 全栈部署实测**（2026-10-01）：7 服务全部健康（postgres/redis/api/worker/nginx/prometheus/grafana）；补齐部署缺口——postgres 自动初始化 schema（initdb 挂载）、Grafana provisioning 开箱即用（datasource uid=prometheus + 看板自动加载）、Dockerfile PyPI 国内源、nginx 443 块拆分至 `nginx-ssl.conf.example`（无证书环境可启动）、worker 禁用继承的 HTTP 探活；种子导入 + 8 用户全链路流量（登录/建档/记餐/商家 PostGIS 查询/账户）后 Prometheus targets `ai-coach-api up`、`http_requests_total` 等业务指标入采集

### 1.6 文档↔实现 处置台账（已闭环，2026-10-01 用户拍板）

> 处置依据：`docs/changes/2026-10-01-文档矛盾代码对齐决策记录.md` + `2026-10-01-邀请规则变更记录.md`。`docs/` 基线冻结只读，一字未动；原始明细（逐条说法 A/B、行号定位）见决策记录与 git 历史。

**A. 口径矛盾（N / D / R 系列）**

| 编号 | 摘要 | 处置结果 |
| --- | --- | --- |
| N-1 / N-2 | 文档表数 31↔27、接口数 30↔34（代码 36 表 / 82 操作） | 保留代码：文档清单/DDL 滞后于文档功能章节（拍板①） |
| N-3 | 商家越界价 400↔422 | 改代码＝400（已落地） |
| N-4 / N-5 / N-6 | 邀请口径三处矛盾 | 按《邀请规则变更记录》落地代码（注册即有效 / 1-3-10 档 / 实时无期限） |
| N-7 / D-06 | geo GEOMETRY ↔ lat/lng | 改代码＝PostGIS GEOMETRY（0008 迁移，拍板②） |
| N-8 / D-05 | embedding vector ↔ jsonb | 代码 JSONB |
| N-9 | TDEE ↔ TEE 公式 | 拍板③遵守 TEE（代码一致，手算对拍误差 0） |
| N-10 / D-08 | compose 5 ↔ 7 服务 | 保留代码：Prometheus/Grafana 为文档 §10.7 监控要求的实现 |
| N-11 / N-12 | 首页模块口径 / 商家保护分级 | 已按 §5.1 补齐 / R-01 已实现 |
| D-01 | 错误码 4002 未登记 | 保留代码：幂等防重放（安全项，删除即退化） |
| D-02 | 订单库存语义 | 保留代码：支付扣减防超卖 |
| D-03 / D-04 | contribution_points 列 / source 1–5 | 保留代码：§2.3.2 功能要求 |
| D-07 | §3.1 页面表出入 | 保留代码：26 页均为 §5.x 功能页，商家后台合入 admin H5 |
| D-09 | AI Provider 选型 | 改代码＝LLM/VLM 统一 OpenAI 兼容协议（拍板④，`LLM_*`/`VLM_*` env 配置） |
| D-10 | 冒烟 50 ↔ 55 条 | 保留代码：超出非缺失 |
| R-01 | 商家权重保护/清退 | 已实现（`partner_level` 分档 + 零贡献清退，0005 迁移） |
| R-02 / R-03 | P1 其余项 / P2 二期 | 文档明示二期，不实现 |

**B. 功能级偏差补齐（F 系列，文档有的一律实现）**

| 编号 | 主文档位置 | 文档要求 | 落地实现 |
| --- | --- | --- | --- |
| F-01 | §2.3.1 `:98`、§6.3.3 `:897` | 每日早晨「今天什么状态」五选一（NEAT 粗调） | `daily_snapshot.activity_level` + `POST /api/account/today-status` + 首页弹窗；当日状态驱动 PAL，未选回退建档值【假设】 |
| F-02 | §2.4 `:118` | 食物库查不到 → 用户自定义食物（仅本人可见、待审核） | `Food` 加 `owner_user_id`/`audit_status`（0004 迁移）+ `POST /api/food/custom` + 搜索按可见性过滤 + 前端录入 |
| F-03 | §2.4 `:123` | 网络异常：记录/订单本地缓存、恢复重试 | `utils/offline.ts` 离线队列 + 网络恢复重放 + `request.ts` 钩子（**未真机验证**） |
| F-04 | §2.4 `:125`、§12.1 `:1699` | 订单退款入口 | `order.ts#refundOrder` + 订单列表「申请退款」按钮 |
| F-05 | §2.2 `:90`、§6.3.4 `:902` | 平台运营「标准目录维护」 | `POST/PUT /api/admin/sku-catalog` + 后台「标准目录」页（契约/mock/TS 同步） |
| F-06 | §1.2 `:36`、§2.3.1 `:100` | AI 主动介入 12+ 场景、订阅消息推送 | 消费者 `tasks/reminder_consumer.py` + 发送抽象（无凭证明确降级）+ 场景模板扩到 13 个（**未真机验证**） |
| F-07 | §6.3.3 `:897`、§5.7 `:824` | NEAT 第四层「体重变化·周度反推」 | `calorie.weekly_neat_calibration`（有界修正）+ `account.get_weekly_calibration`；不改 TEE 结构【假设】 |
| F-08 | §2.4 `:124` | 未授权订阅 → 引导设置页 | `useSubscribe` + 「我的」提醒入口（`requestSubscribeMessage`→`openSetting`，不阻断） |
| F-09 | §2.5 `:136`、§13.3 `:1754` | 步数为 0/取不到 → PAL 估算 | 去除伪造 8000 步，改 `uni.getWeRunData`（无则报 0）+ 后端解密骨架（**未真机验证**） |
| F-10 | §13.3 `:1752-1753` | 未填活动水平默认 2、目标默认「减脂」 | `schemas/profile.py` 两项带默认值 + 契约/TS 同步 |
| F-11 | §2.4 `:119`、§13.3 `:1756` | AI 不可用 → 降级展示预设 FAQ | `chat.vue` 优先展示后端 FAQ，不再覆盖 |

**C. 已重新核对为一致（回滚后无变化）**

- §10.3 `:1619`「Dockerfile.backend 多阶段构建、非 root、8000」↔ 代码已对齐 ✓
- §3.2 `:172` TabBar 5 个 ↔ 代码 ✓
- §8.1 `:1346`「参数错 422」↔ 代码 ✓（与 N-3 的「400」冲突见上）
- 错误码 HTTP 映射、契约 75 路径/82 ops ↔ 实现/mock 双向 diff 0 ✓

---

## 二、待完成 · 优化

> 口径：`P0` 阻断 / `P1` 真实缺陷或交付要求未达 / `P2` 轻微或二期。带 ✅ 者为**已拍板登记、等产品决定是否修订基线**，不改文档。

### 2.1 功能缺口（文档要求、代码未实现）

| 编号 | 文档位置 | 文档要求 | 当前状态 | 级别 |
| --- | --- | --- | --- | --- |
| G1 | §2.1 P1 `:80`、§2.2 `:84-92`、§5.2-8 | 真人健身教练工单（教练端查看分配用户/回复工单）、专家问诊 | 后端无任何 coach/ticket 端点；`eat.vue` 专家问诊仅 UI 占位「即将上线」 | **P1** |
| G2 | §2.1 P1 `:80`、§1.2 `:30` | 平台自营 AI+真人教练订阅付费（进阶 29 / 高级 59 / 终身档） | 无付费升级链路；`/api/subscription` 实为**提醒订阅**（notification.py），非权益付费 | **P1** |
| G3 | §5.5 `:683-698` | 我的页 items 5–9：任务中心/每日签到、我的积分、隐私控制、报告导出、专属优惠 | `mine.vue` 仅「常用/提醒/账号」三卡，上述模块全缺 | P2 |
| G4 | §5.1-4 `:141`、§5.2-2、§5.3-4 | 语音录入/语音输入/语音描述 | `eat.vue` 语音按钮为占位「后续版本支持」，无 `RecorderManager`；其余页无语音 | P2 |
| G5 | §5.2-7 `:109-114` | 附近商家比价卡片（标准套餐） | `eat.vue` 占位「即将上线」，未调用 `/api/merchant/list` | P2 |
| G6 | §5.3-8 `:296-297` | 硬件同步（小米手环/华为手表/Apple Watch/智能秤） | `sport.vue` 注释明示「无后端支撑，本期不实现」（文档 §6.3.3 亦列二期） | P2（二期） |
| G7 | §6.3.6 `:911` | 账号注销级联清除 | 无注销/级联删除端点 | P2 |
| G8 | §7.4 `:1335` | 2 年记录按月分区归档 | 未实现（文档允许首期不实施） | P2 |
| G11 | §3.1 #24/25 `:159-160` | 独立商家后台登录页 / 商家后台页 | 无 `pages/merchant/login`、`pages/merchant/admin`；功能并入 `admin/` H5（同 D-07） | P2 |
| G12 | §2.3.1-7 `:92` | 周报（缺口/步数/体重趋势 + AI 点评） | 有 `/api/ai/weekly-comment`（仅 AI 点评聚合），无周报导出 | P2 |

### 2.2 工程与测试基建缺口

- **前端测试基建缺失**（文档 §9.1 `:1542`，P1）：要求 Vitest 组件测试 + Playwright E2E，仓库**无配置与脚本**，仅后端 pytest；影响 §12.2 测试报告交付。现存 H5 E2E 脚本仅在 /tmp，未入库
- **单元测试行覆盖率无报告**（§9.1 要求 ≥70%）：仓库无可核对的覆盖率产物

### 2.3 已实现但不完整 / 优化项

- **中文全文检索失真**（G10，§6.3.2 `:889`）：按文档原文用 `to_tsvector('simple')`，实测不切中文（`热量` 命中 0 行），每次实际走 `ILIKE` 降级（`record_service.py:111`、`ai_service.py:116`）
- **设计令牌未落地消费**：`tokens.scss` 已定义，但 `miniapp/src` 内 `var(--` 使用 0 次、硬编码 hex 61 处
- **首页模块未做像素级验收**：已按文档 §5.1 补齐评分卡/需要你关注/同款减友/自查工具/最近记录，券提醒已接真实接口，但是否与设计稿完全一致未做像素级核对
- **`.env.example` 密钥占位过短**：`JWT_SECRET=change-me-to-a-random-secret` 仅 28 字节 < 32（RFC 7518）
- **存量 ruff 274 处**（B008×166 + UP045×94、E501×6、UP017×3、UP046×2、B904×1、UP012×1、I001×1）：属仓库既有风格，不阻断
- **仓库存量 40 文件非 black-clean**（本轮新增/重写文件均 clean）：按存量纪律保留

### 2.4 待外部条件 / 收尾

- **OpenAI 兼容端点联调**（原 D-13）：D-09 重构后配 `LLM_*`/`VLM_*` 六项 env 即可接入任一 OpenAI 兼容厂商（DeepSeek/通义/混元/ModelScope 等）；未配密钥前走降级路径
- **ModelScope 明文令牌轮换**：`ai_api.md`（docs/ 冻结区）中明文令牌已泄露（用户要求保留原文），强烈建议到厂商侧轮换作废
- **微信支付真实商户号联调**（F1）：现为沙箱/Mock 打通，未接正式商户号
- **CI 平台实跑**：沙箱无 runner，仅本地复现（三 job 全绿）
- **微信开发者工具小程序验收**：沙箱无该工具；H5 层交互已覆盖
- **admin H5 交互级 E2E**：现仅覆盖构建 + 后端 API 测试，浏览器点击流未做
- **性能压测 / 兼容性 / 全链路 E2E**：§9.3/§9.4 指标仅 `perf/` 自述，未在本轮实跑复现

### 2.5 本次复核补登（登记口径）

- ✅ **契约数字修正**：契约现状为 **75 路径 / 82 操作**（本文件旧版及多处曾记「72 路径 / 78 操作」，系滞后于 F-01/F-02/F-05 三次契约新增；本次已全文修正）。文档侧仍为「标题 30 / 表格 34」，属 N-2 同类滞后，等产品决定是否修订基线
- **测试文件注释滞后**（P2，待改）：`backend/tests/test_contract_consistency.py:10` 与 `:83` 的 docstring 仍写「72 路径 / 78 ops」，与同文件常量 `FROZEN_PATH_COUNT=75` / `FROZEN_OP_COUNT=82` 不一致 —— 仅注释问题，断言正确、门禁不受影响
- **P1 覆盖统计**：文档 §2.1 P1 共 6 项 —— 全实现 2（商家权重保护、智能推荐）、部分 2（报表后台、社区审核基础版）、缺失 2（G1 人工教练工单、G2 订阅付费）
- **数量维度现状**（供后续对账）：页面 26 / 接口 75 路径·82 操作 / 表 36 / 错误码 16 / 后端测试函数 342（参数化收集 564）；文档 §7.1 列 31、§7.2 DDL 27、§8.3 标题 30 / 表格 34，均与实现对不上，属 N-1 / N-2 登记项