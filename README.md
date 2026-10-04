# AI 饮食管控教练 · 操作手册

微信小程序用户端 + FastAPI 后端 + Vue3 管理后台的一体化 monorepo。

本文档只讲两件事：**用 compose 启动后端**、**编译小程序**。

---

## 一、启动后端

```bash
cp .env.example .env                            # 按 §三 填写配置（可先留空跑起来）
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```

一条命令就够了，以下都会自动完成，**不需要手动做**：

- 启动 PostgreSQL 16（PostGIS 镜像）与 Redis 7
- **建表**：首次启动自动执行 `data/sql/001_schema.sql`，建好 36 张表
- **导入种子**：食物库 1750 条、别名 342 条、标准 SKU、RAG 语料
- **对齐数据库版本**（alembic）
- **创建后台超管账号**（账号密码取自 `.env`）
- 构建后端镜像并启动 api / worker / nginx
- 构建管理后台静态产物

执行完即可访问：

| 服务 | 地址 |
| --- | --- |
| Nginx 入口 | http://localhost |
| API 文档 | http://localhost/api/docs |
| 管理后台 | http://localhost/admin/ |
| PostgreSQL | localhost:5432（`postgres` / `postgres`） |
| Redis | localhost:6379 |
| Prometheus / Grafana | localhost:9090 / localhost:3000 |

小程序连的是 **http://localhost**（nginx 把 `/api` 反代到后端），不是 8000 端口。

### 验证

```bash
curl http://localhost/healthz                                # 期望 200
curl -X POST http://localhost/api/auth/login \
  -H 'Content-Type: application/json' -d '{"code":"fake"}'  # 未填微信凭证时期望 401 + code 1001
```

### 常用运维命令

```bash
# 看状态 / 日志
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f api

# 改了后端代码后重建（镜像部署，无源码挂载，必须重新构建）
docker compose -f deploy/docker-compose.yml build api && \
docker compose -f deploy/docker-compose.yml up -d api

# 停止（保留数据卷）
docker compose -f deploy/docker-compose.yml down

# ⚠️ 停止并删除数据卷 —— 会丢数据，慎用
docker compose -f deploy/docker-compose.yml down -v
```

---

## 二、`.env` 配置

**`.env` 必须放在仓库根目录**（不是 `deploy/` 下）。

### 必填

| 变量 | 说明 | 不填的后果 |
| --- | --- | --- |
| `JWT_SECRET` | JWT 签名密钥，**≥ 32 字节** | 生产（`ENV=prod`）用默认值会**拒绝启动**；开发态可用默认值但 token 不安全 |
| `ADMIN_INIT_USERNAME` | 后台超管账号名 | 超管不会被创建，登录后台报账号不存在 |
| `ADMIN_INIT_PASSWORD` | 后台超管密码，**≥ 12 位且非弱口令** | 超管不会被创建，登录不了后台 |
| `DATABASE_URL` | 数据库连接串 | 保持默认即可（compose 会覆盖成容器服务名） |
| `REDIS_URL` | Redis 连接串 | 保持默认即可 |

生成合规密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> 超管创建走 `--optional` 模式：凭据缺失时打日志跳过、返回 0，**栈照样能起来**，但你登不进后台。所以这两项实际必填。

### 微信小程序（不填则无法真机登录 / 拍照识别 / 支付）

| 变量 | 说明 | 不填的后果 |
| --- | --- | --- |
| `WECHAT_APPID` | 小程序 AppID | **登录直接失败**（返回 `1001`）。本项目已删除 mock 登录，无假身份兜底 |
| `WECHAT_SECRET` | 小程序 AppSecret | 同上 |
| `WECHAT_MCH_ID` | 微信支付商户号 | 支付不可用 |
| `WECHAT_PAY_KEY` | 商户 API 密钥 | 支付不可用 |
| `PAY_MOCK_MODE` | 沙箱支付开关 | `true` = 支付即模拟成功。**生产必须 false** |
| `WECHAT_SUBSCRIBE_ENABLED` | 订阅消息总开关 | 默认 `false` = 推送只记日志，不真发 |

获取途径：微信公众平台 → 开发管理 → 开发设置 → AppID / AppSecret；支付在微信支付商户平台。

### 对象存储（拍照识别上传图片用）

| 变量 | 说明 |
| --- | --- |
| `COS_SECRET_ID` / `COS_SECRET_KEY` | 腾讯云 API 密钥 |
| `COS_BUCKET` | 桶名（需配成**公有读私有写**） |
| `COS_REGION` | 地域，默认 `ap-guangzhou` |
| `COS_BASE_URL` | 自定义域名 / CDN，留空回落桶默认域名 |

三项凭证任一为空 → 上传降级（拍照记录仍可保存，只是不带图）。

### AI（对话 + 拍照识别，不填自动降级为模板数据）

`LLM_*` 用于对话与推荐，`VLM_*` 用于拍照识别，都走 OpenAI 兼容协议，换厂商只改 env：

| 变量 | 示例 |
| --- | --- |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1`（**须含 `/v1`**） |
| `LLM_API_KEY` | 厂商 API Key |
| `LLM_MODEL` | `deepseek-chat` / `qwen-plus` |
| `VLM_BASE_URL` / `VLM_API_KEY` / `VLM_MODEL` | 同上，换成支持视觉的模型 |

留空不报错，走内置降级。

### 可选：调参与限额

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `ENV` | `dev` | 设 `prod` 启用生产守卫（禁默认密钥、禁沙箱支付） |
| `LOG_LEVEL` | `INFO` | 排查问题设 `DEBUG` |
| `CORS_ALLOW_ORIGINS` | `*` | 生产请收紧为具体域名 |
| `AI_DAILY_TIMES` | `10` | 每日 AI 对话次数配额 |
| `RATE_LIMIT_GLOBAL_PER_MIN` | `100` | 全局限流（次/分钟/IP） |
| `WECHAT_STEPS_SESSION_KEY` | 空 | **正常部署留空**，仅本地调试兜底 |

### 三个容易踩的坑

1. **改 `.env` 不生效**：先确认文件真在**仓库根**且键名拼写正确。compose 的 `env_file` 标了 `required: false`，文件缺失会**静默跳过、不报错**。另外 `${VAR}` 插值只读 shell 环境变量和 `deploy/.env`（后者不存在），**根 `.env` 不参与插值** —— 所以 `POSTGRES_PASSWORD` 这类要改得走 shell：`POSTGRES_PASSWORD=xxx docker compose up -d`。
2. **换 `JWT_SECRET` 会让已登录用户集体掉线**（旧 token 全部失效，前端在首页与登录页之间互跳）。清小程序缓存重新登录即可。
3. **改数据库口令无效**：已初始化的 pgdata 卷不会随口令变更（`initdb` 只在空卷执行），改了就连不上。要改得 `down -v` 重建（**会丢数据**）。

---

## 三、编译小程序

交付物是**微信小程序**（H5 不进部署面）。

```bash
cd miniapp
npm install
npm run build:mp-weixin
```

产物在 **`miniapp/dist/build/mp-weixin`**。

### 加载到微信开发者工具

用**微信开发者工具**导入 `miniapp/dist/build/mp-weixin`（不是 `miniapp/src`）。

**改了源码重新构建后，工具里不会自动生效** —— 必须先 `cli quit` 再 `cli open` 重新加载（开发者工具的 `DevtoolsFileWatcher` 不会监听外部构建产物）。

真机预览时记得在**开发者工具 → 详情 → 本地设置**里关闭域名校验（项目当前走 `http://localhost`，未配 https 合法域名）。

---

## 四、常见问题

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| 容器起不来，日志报连不上库 | 数据库没起 / `.env` 连接串指错 | 确认 `docker compose ps` 里 postgres 是 healthy |
| 登录返回 `1001` | `WECHAT_APPID` / `WECHAT_SECRET` 未填或填错 | 填入小程序凭证（mock 登录已删，无兜底） |
| 登录后台提示账号不存在 | `ADMIN_INIT_USERNAME/PASSWORD` 未填 | 补齐后 `docker compose -f deploy/docker-compose.yml run --rm migrate` |
| 拍照识别 / AI 对话命中 0 条 | 容器内种子的 RAG 语料是精简样本（3 行） | 手动灌全量：`data/load_seeds.py --file ai_knowledge:data/seeds/ai_knowledge_full.jsonl` |
| 改了 `.env` 没生效 | 文件不在仓库根 / 键名拼错 / 被 compose `environment` 覆盖 | 先确认文件存在与键名 |
| 首页与登录页来回跳 | 换了 `JWT_SECRET`，旧 token 全失效 | 清小程序缓存重新登录 |
| 微信开发者工具里看不到改动 | 工具不自动重载外部构建产物 | 重新构建后 `cli quit` + `cli open` |
| 小程序请求 `http://localhost` 失败 | 工具里勾选了域名校验 | 详情 → 本地设置 → 关闭域名校验 |

---

## 附录：项目结构

```
backend/    FastAPI 后端（app/: api, services, models, schemas, core, tasks）+ pytest
miniapp/    uni-app 小程序（Vue3 + TS + Pinia，交付目标 mp-weixin）
admin/      Vue3 管理后台（Element Plus，H5 SPA，部署于 /admin）
contracts/  契约真源 openapi.yaml + 两份 TS 类型副本（三方一致性由后端测试守护）
data/       建表 SQL（36 表）、种子数据、导入脚本
deploy/     docker-compose.yml、nginx.conf、prometheus/grafana、部署说明
docs/       需求交付文档（**只读基线，勿改**）
perf/       压测工具
scripts/    辅助脚本
```

核心能力：微信登录、身体档案、热量账户（BMR/TDEE/步数校准）、拍照识别记录饮食、AI 对话（RAG + 次数限制）、饭点决策、商家 / SKU / 券 / 订单核销、体重趋势、社区与五种社交。

更详细的部署细节（分阶段上线、监控栈、灰度与回滚）见 [`deploy/README.md`](deploy/README.md)。
