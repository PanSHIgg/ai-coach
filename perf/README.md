# F5 性能测试目录

对 `ai_coach_perf` 库 + 8003 端口真跑 uvicorn 施压。**本机 4GiB / 3 核 / 无 swap →
压测串行、低并发**，实测参数与结论见 `report.md`。

## 文件

- `seed_bulk.py`：向 `ai_coach_perf` 灌入 1,000,000 行 `meal_record` + 200 行
  `"order"` + 压测用户/商家/SKU。幂等（重复执行只补差量）；`--clean` 清理。
  执行后写 `seed_ids.json`（供 harness 读取 id）。
- `harness.py`：httpx.AsyncClient + asyncio 压测器，输出 QPS / P50 / P95 / P99 / 错误率。
- `report.md`：真实实测报告。
- `seed_ids.json`：seed_bulk 产出的 id（自动生成，可删）。

## 用法

```bash
PY=/workspace/.venv312/bin/python

# 1) 灌数据（可重复执行；--rows 调整规模；--clean 清理）
$PY perf/seed_bulk.py
$PY perf/seed_bulk.py --clean

# 2) 起被测服务（务必禁用限流，否则全局 100/min/IP 先返回 429）
cd backend && \
  DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach_perf" \
  RATE_LIMIT_ENABLED=false \
  JWT_SECRET="perf-secret-hs256-key-0123456789" \
  $PY -m uvicorn app.main:app --port 8003 --log-level warning

# 3) 施压（jwt-secret 须与 uvicorn 一致；场景见 harness.py SCENARIOS）
$PY perf/harness.py --scenario account_today --concurrency 20 --duration 15 \
    --jwt-secret "perf-secret-hs256-key-0123456789"
$PY perf/harness.py --scenario meal_page --page 5000 --page-size 100 \
    --concurrency 1 --duration 10 --jwt-secret "perf-secret-hs256-key-0123456789"
```

场景：`account_today` / `food_search` / `order_create` / `order_list` /
`meal_page` / `meal_write`。

## 百万行分页双证据

```bash
PGPASSWORD=postgres psql -h 127.0.0.1 -U postgres -d ai_coach_perf -c \
 "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM meal_record WHERE user_id=<id> \
  ORDER BY created_at DESC, id DESC OFFSET 499900 LIMIT 100;"
```