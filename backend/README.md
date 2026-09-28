# AI 饮食管控教练 · 后端（P0-e 脚手架）

FastAPI + pydantic v2 异步后端。当前为 P0 stub：openapi.yaml 全部 **34 接口**已挂载并可跑，返回 envelope + 罐头数据（对齐 `contracts/mock/routes.mjs`），业务逻辑标注 `TODO(Phase1)` 待落库。

## 本地启动

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- 健康检查：`GET /healthz`（无前缀，`{"status":"ok"}`）
- 接口文档：`/docs`、OpenAPI：`/openapi.json`
- 无需 PG/Redis：P0 阶段接口为 stub，不连库；Redis 不可用时限流自动降级进程内窗口

## 环境变量

复制仓库根 `.env.example` 为 `.env`（或按需导出）。关键项：

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL DSN（asyncpg 驱动） |
| `REDIS_URL` | Redis DSN |
| `JWT_SECRET` / `JWT_ALGORITHM` | JWT 密钥/算法（HS256） |
| `JWT_ACCESS_EXPIRE_HOURS=2` / `JWT_REFRESH_EXPIRE_DAYS=7` | 双 token 有效期 |
| `WECHAT_APPID` / `WECHAT_SECRET` | **为空时 code2session 走 mock**（openid 由 code 确定性派生，真 JWT） |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_GLOBAL_PER_MIN` / `RATE_LIMIT_AI_PER_MIN` / `RATE_LIMIT_AUTH_PER_MIN` | 限流开关与阈值（默认 全局 100/min/IP、AI 20/min/用户、登录 10/min/IP，见 04 文档 §6.3.6） |

## 数据库迁移

```bash
ALEMBIC_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/ai_coach \
  alembic upgrade head
```

`alembic/env.py` 只读 `ALEMBIC_DATABASE_URL`（alembic.ini 留空）。

## 测试

```bash
pip install pytest pytest-asyncio httpx   # 或安装 dev 依赖
pytest tests -v          # pyproject 已配 asyncio_mode=auto、testpaths=tests
```

测试为纯接口测试（httpx ASGITransport），不依赖 PostgreSQL/Redis。

## 目录说明

```
backend/
├── alembic/            # 迁移（P0-c 既有，36 表）
├── app/
│   ├── ai/             # AI 服务（P0-f 另一代理所有，本任务未改动）
│   ├── api/
│   │   ├── deps.py     # get_current_user（JWT Bearer）、get_request_id
│   │   └── v1/
│   │       ├── router.py       # 10 个域路由聚合
│   │       └── endpoints/      # auth/users/account/records/ai/merchants/orders/coupons/community/admin
│   ├── core/
│   │   ├── config.py   # pydantic-settings，字段对齐 .env.example；get_settings() lru_cache
│   │   ├── context.py  # request_id contextvar
│   │   ├── errors.py   # AppException + 业务码→HTTP 状态映射（401/403/404/409/422/429/500）
│   │   ├── logging.py  # JSON 结构化日志（request_id/method/path/status/duration_ms）
│   │   ├── rate_limit.py # INCR+EXPIRE 窗口限流中间件；Redis 不可用降级进程内字典
│   │   └── security.py # PyJWT 签发/校验 + pbkdf2 密码哈希
│   ├── db/
│   │   ├── session.py  # 惰性 async engine + get_db 依赖
│   │   └── redis.py    # 惰性 Redis 连接，不可用不崩
│   ├── middleware/
│   │   └── request_id.py # X-Request-ID 透传/生成 + JSON 访问日志
│   ├── schemas/        # pydantic v2 契约模型（P0-d 既有，只读未改动）
│   ├── services/
│   │   └── auth_service.py # code2session（httpx）+ mock 分支 + JWT 签发
│   └── main.py         # create_app 工厂：CORS/RequestId/RateLimit/异常处理 + /healthz + /api 前缀
└── tests/              # conftest + test_health/test_auth/test_rate_limit
```

## 约定

- 响应统一 envelope：`{code, message, data, request_id, errors?}`；错误码见 `app/schemas/common.py`
- HTTP 状态映射（openapi.yaml 头部）：422→2001、401→1001、403→1002、404→3001、409→4001~7001、429/500 复用状态码
- 所有业务数据查询默认带 `user_id` 行级隔离（Phase1 落库时执行）
- P0 假设：限流/服务错业务码复用 HTTP 状态码；`/api/meal/recognize` 的 multipart 解析待引入 python-multipart（requirements 未含，暂以原始流 stub）
