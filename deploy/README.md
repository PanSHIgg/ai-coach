# deploy/ 部署文件说明

| 文件 | 用途 |
| --- | --- |
| `docker-compose.yml` | 一键编排 postgres:16 + redis:7 + api(backend 构建) + nginx |
| `Dockerfile.backend` | 后端镜像：python:3.12-slim，装 requirements、拷 backend、uvicorn 多 worker 非 root 启动 |
| `nginx.conf` | 入口路由：`/api/`→api:8000、`/admin/`→后台静态、`/uploads/`→媒体；gzip、限流 100r/s；443 占位 |

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

只起依赖、后端本地调试：

```bash
docker compose -f deploy/docker-compose.yml up -d postgres redis
```

---

## Phase 1（M1）staging 上线步骤（本地 / 服务器通用）

> staging = 可联调、可回归的测试环境。以下命令均在 **仓库根目录** 执行。
> 已在「本地 venv + 127.0.0.1:5432 PG」验证：schema 36 表、种子 1750 食物 + 342 别名、95 pytest 全绿。

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
# 预期：95 passed（含 tests/test_boundaries.py 建档边界、tests/test_smoke_phase1.py M1 端到端闭环）
```

### 8. 服务器差异

- 云服务器：改 `.env` 的 `POSTGRES_PASSWORD`/`JWT_SECRET`；启用 Nginx 443 + Let's Encrypt（见 `nginx.conf` 文末占位）。
- 生产可将 PG/Redis 换云托管：改 `DATABASE_URL`/`REDIS_URL` 指向云实例即可，schema 与种子导入步骤同上。
- 迁移纪律（§10）：先测后 prod、执行前备份、镜像打 git short sha、只加字段保证可回滚。
