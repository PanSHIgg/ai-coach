# deploy/ 部署文件说明

| 文件 | 用途 |
| --- | --- |
| `docker-compose.yml` | 一键编排 postgres:16 + redis:7 + api + worker + nginx + prometheus + grafana + redis-exporter + postgres-exporter；镜像 tag 用 `${GIT_SHA:-latest}`，日志落盘卷 `logs` |
| `Dockerfile.backend` | 后端镜像：python:3.12-slim，装 requirements、拷 backend、uvicorn 多 worker 非 root 启动 |
| `nginx.conf` | 入口路由：`/api/`→api:8000、`/admin/`→后台静态、`/uploads/`→媒体；gzip、限流 100r/s；80（dev）+ 443（LE 证书占位，已启用） |
| `prometheus/prometheus.yml` | Prometheus 采集配置：抓取 `api:8000/metrics` + `redis-exporter:9121` + `postgres-exporter:9187` |
| `prometheus/alert.rules.yml` | 告警规则：不可用 5min / 错误率>5% / 磁盘>80% / AI 日成本超预算 + Redis/PG 六条（组 `ai-coach-infra`） |
| `grafana/dashboard.json` | Grafana 看板：QPS、P95 延迟、错误率、热量计算耗时、AI 调用与成本估算、基础设施（Redis 内存/吞吐/命中率、PG 连接/事务/缓存/体积） |
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
# 预期：全量通过（基线以当次实跑为准）
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
| `calorie_calc_seconds` | Histogram | 热量账户计算耗时（埋点在 `account.compute_result`，只圈纯计算，不含取数等待） |
| `ai_calls_total{task,degraded}` | Counter | 真实厂商 AI 调用次数 / 降级率；`task`=chat\|weekly_comment\|recommend\|vision（由 `ai_task()` 声明）。无 Key 的 Mock/模板降级不发 HTTP，故不计入 |
| `ai_tokens_total{task,type}` | Counter | token 用量速率，`type`=input\|output\|cached（cached 是 input 中命中前缀缓存的部分，取自 `usage.prompt_tokens_details.cached_tokens`） |
| `ai_cost_usd_total{task}` | Counter | AI 成本估算 = [(input−cached)×输入价 + cached×缓存价 + output×输出价] / 1e6，牌价取根 `.env` 的 `AI_PRICE_*_USD_PER_MTOKEN`（美元/百万 token，默认 0 → 成本恒为 $0，`AIBudgetExceeded` 也就永不触发，接入厂商后务必填） |

### 基础设施指标（Redis / PostgreSQL exporter）

两个 exporter 与业务同栈（compose 服务 `redis-exporter` / `postgres-exporter`，只读采集）：

```bash
docker compose -f deploy/docker-compose.yml up -d redis-exporter postgres-exporter
```

| 指标族 | 来源 | 关键序列（本机 v1.93.0 / v0.20.1 实测名） |
| --- | --- | --- |
| Redis | `oliver006/redis_exporter:v1.93.0`（:9121，job `redis`） | `redis_up`、`redis_memory_used_bytes` / `_used_peak_bytes` / `_max_bytes`、`redis_connected_clients` / `_blocked_clients`、`rate(redis_commands_processed_total)`、`redis_commands_duration_seconds_total{cmd}`、`redis_keyspace_hits_total` / `_misses_total`、`redis_evicted_keys_total` / `_expired_keys_total`、`redis_db_keys{db}` |
| PostgreSQL | `prometheuscommunity/postgres-exporter:v0.20.1`（:9187，job `postgres`） | `pg_up`、`pg_stat_activity_count{datname,state}`、`pg_settings_max_connections`、`pg_stat_database_xact_commit` / `_xact_rollback` / `_blks_hit` / `_blks_read` / `_deadlocks` / `_tup_returned`（**注意：这些计数无 `_total` 后缀**）、`pg_database_size_bytes{datname}`、`pg_locks_count{datname,mode}`、`pg_replication_lag_seconds` |

- **DSN 与 compose 的 `${POSTGRES_*}` 同源同坑**：插值不读根 `.env`（见上文 api 段说明），
  改库口令必须 shell 传入或建 `deploy/.env`，且 `postgres` / `api` / `postgres-exporter` 三处一致，
  否则 exporter 恒 `pg_up 0`（表现为 PG 面板整排 No data）。
- `pg_stat_database_*` 与 `pg_stat_activity_count` 覆盖实例内**所有库**；看板按 `datname="ai_coach"`
  过滤到部署库，而 `PostgresConnectionsHigh` 按实例总量算（`max_connections` 是实例级上限）。
- 序列量级：`pg_stat_user_tables_*` / `pg_statio_*` 是**每表一条**，本机因并存多个 slot 库
  实测 `job="postgres"` 共 5142 条；生产单库同量级会降到约 1/18。

### 一键起监控栈

```bash
# 与业务一起起（prometheus + grafana + 两个 exporter 见 docker-compose.yml）
GIT_SHA=$(git rev-parse --short HEAD) \
  docker compose -f deploy/docker-compose.yml up -d --build
```

- Prometheus：`http://localhost:9090`，抓取 `api:8000/metrics` + `redis-exporter:9121` +
  `postgres-exporter:9187`（见 `prometheus/prometheus.yml`）。改了 `prometheus/` 下的文件后
  热加载：`docker kill --signal=SIGHUP ai-coach-prometheus`（无需重启，历史数据不丢）。
- Grafana：`http://localhost:3000`（默认 admin/admin，生产改 `GRAFANA_ADMIN_PASSWORD`）。
  数据源与看板由 `grafana/provisioning/` 自动装配（`dashboard.json` 是 bind-mount，
  `updateIntervalSeconds: 10` → 改完 10 秒内自动生效），**不要再手动导入**，否则会出现两份同名看板。

### 告警（`prometheus/alert.rules.yml`）

| 告警 | 触发 | 依赖 |
| --- | --- | --- |
| `ServiceDown` | `up{job="ai-coach-api"}==0` 持续 5m | 内置 |
| `HighErrorRate` | 5xx 占比 >5% 持续 5m | 内置 |
| `DiskUsageHigh` | 磁盘使用率 >80% 持续 10m | **需外部 `node_exporter`**（未接入时不触发） |
| `AIBudgetExceeded` | 近 24h `ai_cost_usd_total` 超预算 | 内置；牌价未填时恒 0 不触发；阈值为占位 |
| `RedisDown` | `redis_up==0` 持续 2m | `redis-exporter` |
| `RedisMemoryNearMax` | used/maxmemory >80% 持续 5m | `redis-exporter`；**未设 `maxmemory` 时不产生数据** |
| `RedisEvictingKeys` | `rate(redis_evicted_keys_total[5m])>0` 持续 5m | `redis-exporter` |
| `PostgresDown` | `pg_up==0` 持续 2m | `postgres-exporter` |
| `PostgresConnectionsHigh` | 实例连接总数 >80% `max_connections` 持续 5m | `postgres-exporter` |
| `PostgresCacheHitRatioLow` | 缓存命中率 <95% 持续 10m | `postgres-exporter` |

> 告警通知（企业微信/邮件）需另配 Alertmanager（本仓未内置），规则表达式已就绪。

### 多 worker 与指标聚合

`Dockerfile.backend` 以 `--workers 2` 启动。**镜像已默认打开跨 worker 聚合**：`ENV
PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus-multiproc`，CMD 启动前 `rm -rf` 该目录再 `exec uvicorn`；
`app/observability/metrics.py::_registry()` 检测到该变量即改用 `MultiProcessCollector` 汇总，
于是任一 worker 的 `/metrics` 都返回全进程的和。

为什么必须这么做（本机 2026-10-04 22:4x 实测，未聚合前）：
- 连抓 6 次容器内 `localhost:8000/metrics`：5 次返回 `ai_calls_total{task="vision"}` +
  `calorie_calc_seconds_count 4.0`，1 次返回 `{task="recommend"}` + `2.0` —— 两个 worker 各自记账，
  端点随机应答。
- Prometheus 侧 `count_over_time(ai_calls_total[15m])` 只有 16 / 5 个采样（应有 ~60），
  序列反复被标 stale。
- 后果：`increase(ai_calls_total[15m])` 与面板的 `rate(...)` 全算成 **0**（出现的那些采样里
  计数器恒为 1.0，没有上升沿），面板显示 0 或 No data。QPS / 延迟 / 错误率同样被污染。
- 若不用聚合，退路是 `--workers 1`；两者都不做时，本看板所有数字只能当趋势看，不能当判据。

⚠️ 聚合目录**必须在启动前清空**：`docker restart` 保留容器可写层，残留 `*.db` 会被继续累加，
计数器从此永久偏高（`AIBudgetExceeded` 会误报）。故清空放在 CMD 里，而不是应用代码里——
两个 worker 各自 wipe 会互相抹掉对方的 mmap 文件。

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
