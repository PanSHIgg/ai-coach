# deploy/ 部署文件说明

| 文件 | 用途 |
| --- | --- |
| `docker-compose.yml` | 一键编排 postgres:16 + redis:7 + api + worker + nginx + prometheus + grafana；镜像 tag 用 `${GIT_SHA:-latest}`，日志落盘卷 `logs` |
| `Dockerfile.backend` | 后端镜像：python:3.12-slim，装 requirements、拷 backend、uvicorn 多 worker 非 root 启动 |
| `nginx.conf` | 入口路由：`/api/`→api:8000、`/admin/`→后台静态、`/uploads/`→媒体；gzip、限流 100r/s；80（dev）+ 443（LE 证书占位，已启用） |
| `prometheus/prometheus.yml` | Prometheus 采集配置：抓取 `api:8000/metrics` |
| `prometheus/alert.rules.yml` | 告警规则：不可用 5min / 错误率>5% / 磁盘>80% / AI 日成本超预算 |
| `grafana/dashboard.json` | Grafana 看板：QPS、P95 延迟、错误率、热量计算耗时、AI 调用与成本估算 |
| `灰度发布方案.md` | 发布流程、灰度比例与放量、回滚触发/步骤、7 天稳定观测项与判据 |
| `.github/workflows/cd.yml` | CD：按 git sha 构建镜像 → 推送占位 → staging/prod 部署 + 回滚 |

## 启动

```bash
# 在 code/ 根目录执行
cp .env.example .env
docker compose -f deploy/docker-compose.yml up -d
```

| 服务 | 地址 |
| --- | --- |
| Nginx 入口 | http://localhost |
| API 文档 | http://localhost/api/docs |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |

只起依赖、后端本地调试：

```bash
docker compose -f deploy/docker-compose.yml up -d postgres redis
```

---

## Phase 1（M1）staging 上线步骤（本地 / 服务器通用）

> staging = 可联调、可回归的测试环境。以下命令均在 **仓库根目录** 执行。
> 已在「本地 venv + 127.0.0.1:5432 PG」验证：schema 36 表、种子 1750 食物 + 342 别名；最近一次全量实测 **485 pytest passed**（2026-09-29 UTC，库 ai_coach_a1/a2 双验）。

### 1. 准备环境变量

```bash
cp .env.example .env
# 服务器/生产：务必改 POSTGRES_PASSWORD、JWT_SECRET（openssl rand -hex 32）
```

### 2. 一键起 pg + redis + api + nginx

```bash
docker compose -f deploy/docker-compose.yml up -d --build
# 等 postgres/redis healthy、api healthy（compose 已内置 healthcheck）
docker compose -f deploy/docker-compose.yml ps
```

### 3. 导入初始 schema（36 表）

```bash
# 用容器内 psql 导入（宿主无需装 psql 客户端；schema 从 stdin 传入）
docker compose -f deploy/docker-compose.yml exec -T postgres \
  psql -U postgres -d ai_coach -v ON_ERROR_STOP=1 < data/sql/001_schema.sql

# 校验：应输出 36
docker compose -f deploy/docker-compose.yml exec -T postgres \
  psql -U postgres -d ai_coach -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
```

### 4. 迁移（增量演进）：alembic upgrade head

```bash
# alembic 走同步 psycopg2 DSN（ALEMBIC_DATABASE_URL），在 api 容器内执行
docker compose -f deploy/docker-compose.yml exec -T \
  -e ALEMBIC_DATABASE_URL="postgresql+psycopg2://postgres:postgres@postgres:5432/ai_coach" \
  api alembic upgrade head
```

> 说明：初始迁移 `0001_initial_schema` 与 `data/sql/001_schema.sql` 同源。**全新库二选一**——
> 已按第 3 步导入 schema 则不必再跑 alembic（对象已存在会报错）；alembic 供后续「只加列」的增量迁移使用。

### 5. 导入种子数据（食物库 + 别名）

```bash
# load_seeds.py 用 psycopg2，DSN 不加 +asyncpg；compose 已把 PG 5432 映射到宿主
DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/ai_coach" \
python data/load_seeds.py \
  --dsn "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach" \
  --file food:data/seeds/food_full.csv \
  --file food_alias:data/seeds/food_alias_full.csv
# 预期：已导入 food: 1750 行；已导入 food_alias: 342 行
```

> 宿主无 psycopg2 时，可改用 api 镜像执行（绑定挂载仓库根）：
> `docker compose -f deploy/docker-compose.yml run --rm -v "$PWD:/src" api python /src/data/load_seeds.py --dsn "postgresql://postgres:postgres@postgres:5432/ai_coach" --file /src/data/seeds/food_full.csv --file /src/data/seeds/food_alias_full.csv`

### 6. 健康检查

```bash
curl -fsS http://localhost/healthz      # nginx 层探活 → ok
curl -fsS http://localhost/api/docs     # API 文档可打开（/api 反代到 api:8000）

# API 容器内直连探活（compose 未把 api:8000 暴露到宿主）
docker compose -f deploy/docker-compose.yml exec -T api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/healthz').read().decode())"
```

### 7. Phase 1 验收冒烟（staging 回归）

```bash
cd backend
DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach" \
  python -m pytest -q
# 预期：Phase 1 时点为 95 passed（含 tests/test_boundaries.py 建档边界、tests/test_smoke_phase1.py M1 端到端闭环）；
#       当前全量基线以 AGENTS.md §7.1 为准（最近实测 494 passed + 2 skipped，2026-09-30 UTC）
```

### 8. 服务器差异

- 云服务器：改 `.env` 的 `POSTGRES_PASSWORD`/`JWT_SECRET`；启用 Nginx 443 + Let's Encrypt（见 `nginx.conf` 文末占位）。
- 生产可将 PG/Redis 换云托管：改 `DATABASE_URL`/`REDIS_URL` 指向云实例即可，schema 与种子导入步骤同上。
- 迁移纪律（§10）：先测后 prod、执行前备份、镜像打 git short sha、只加字段保证可回滚。

---

## 监控与告警（F9 / §10.7）

后端已内置 Prometheus 指标，暴露于**运维端点 `/metrics`**（非 `/api` 契约前缀、不进 OpenAPI）：

| 指标 | 类型 | 口径 |
| --- | --- | --- |
| `http_requests_total{method,path,status}` | Counter | QPS / 错误率（`path` 取路由模板，避免高基数） |
| `http_request_duration_seconds{method,path}` | Histogram | 接口延迟，buckets 可算 P50/P95/P99 |
| `calorie_calc_seconds` | Histogram | 热量账户计算耗时 |
| `ai_calls_total{task,degraded}` | Counter | AI 调用次数/降级率 |
| `ai_cost_usd_total{task}` | Counter | AI 成本估算（次数 × 单价） |

### 一键起监控栈

```bash
# 与业务一起起（prometheus + grafana 见 docker-compose.yml）
GIT_SHA=$(git rev-parse --short HEAD) \
  docker compose -f deploy/docker-compose.yml up -d --build
```

- Prometheus：`http://localhost:9090`，抓取目标 `api:8000/metrics`（见 `prometheus/prometheus.yml`）。
- Grafana：`http://localhost:3000`（默认 admin/admin，生产改 `GRAFANA_ADMIN_PASSWORD`）。
  首次登录：添加 Prometheus 数据源（URL `http://prometheus:9090`），导入 `grafana/dashboard.json`
  （看板含数据源变量 `DS_PROMETHEUS`，导入时选择即可）。

### 告警（`prometheus/alert.rules.yml`，4 类）

| 告警 | 触发 | 依赖 |
| --- | --- | --- |
| `ServiceDown` | `up{job="ai-coach-api"}==0` 持续 5m | 内置 |
| `HighErrorRate` | 5xx 占比 >5% 持续 5m | 内置 |
| `DiskUsageHigh` | 磁盘使用率 >80% 持续 10m | **需外部 `node_exporter`**（未接入时不触发） |
| `AIBudgetExceeded` | 近 24h `ai_cost_usd_total` 超预算 | 内置；阈值为占位，按实际预算调整 |

> 告警通知（企业微信/邮件）需另配 Alertmanager（本仓未内置），规则表达式已就绪。

### 多 worker 说明

`Dockerfile.backend` 以 `--workers 2` 启动，各 worker 进程指标独立，Prometheus 抓取仅命中其一。
需全量聚合时，设置环境变量 `PROMETHEUS_MULTIPROC_DIR` 指向可写目录（启动前清空），
`app/observability/metrics.py` 会自动改用 `MultiProcessCollector` 聚合。

---

## worker 后台任务（§10.3）

compose 新增 `worker` 服务，复用后端镜像，跑每日热量快照（`app/tasks/snapshot.py`）。
`Dockerfile.backend` 无 worker 入口，故 compose 用合理 CMD：

```yaml
command: ["sh", "-c", "while true; do python -m app.tasks.snapshot --once || true; sleep 86400; done"]
```

- `--once` 幂等（PG `ON CONFLICT`），重复执行不新增；失败已由任务内部消化，不抛给调度器。
- 生产推荐改用 APScheduler / 系统 cron（对齐 00:00）或 Redis Streams 常驻消费者（见 `snapshot.py` 文档串）。

---

## 发布与回滚（§10.6 / F9）

- 镜像 tag 由 `GIT_SHA` 决定：`GIT_SHA=$(git rev-parse --short HEAD) docker compose ... up -d --build`；
  回滚即 `GIT_SHA=<上一 sha> ... up -d`。
- CD 流程见 `.github/workflows/cd.yml`（按 git sha 构建 → 推送占位 → staging/prod 部署 + 回滚）。
- 灰度比例、放量节奏、回滚触发条件、**7 天稳定运行观测项与判据**见 `灰度发布方案.md`。

## 沙箱限制（如实标注）

本仓部署产物已在无 Docker 的沙箱内**静态校验**（YAML/JSON 解析、Python 导入、ruff），
未真实执行：`docker compose config/up`、Prometheus/Grafana 启动、nginx 启动、`promtool` 规则校验。
