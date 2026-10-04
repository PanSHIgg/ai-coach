# F5 性能测试目录

本目录为本机压测工具，仓库内零外部引用。

对 `ai_coach_perf` 库 + 8003 端口真跑 uvicorn 施压。**本机单worker、无 swap →
压测串行、低并发**；实测数据由 `harness.py` 现场输出。

## 文件

- `seed_bulk.py`：向 `ai_coach_perf` 灌入 1,000,000 行 `meal_record` + 200 行
  `"order"` + 压测用户/商家/SKU。幂等（重复执行只补差量）；`--clean` 清理。
  执行后写 `seed_ids.json`（供 harness 读取 id）。
  ⚠️ **不灌 `food` 种子**，所以 `seed_ids.json` 的 `food_id` 为 `null`；直接跑
  `meal_write` 场景会全量 `422/2001`。须先按下方「food 种子」补灌。
- `harness.py`：httpx.AsyncClient + asyncio 压测器，输出 QPS / P50 / P95 / P99 / 错误率。
- `ai_chat_bench.py`：AI 对话专项压测（串行 50 次 × 2s 间隔），输出延迟分位与
  文档 §9.4 达标判定；明细落 `ai_chat_result.json`。
- `seed_ids.json`：seed_bulk 产出的 id（自动生成，可删）。
- `ai_chat_result.json`：AI 对话压测明细（自动生成，可删）。

## 用法

```bash
PY=/path/to/your/python3.12    # 任意 >=3.12 解释器；PY 已在环境时无需设置

# 0) food 种子（meal_write 场景必需；food_full 1750 行 + 别名 347 行）
$PY data/load_seeds.py --dsn "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach_perf" \
  --file food:data/seeds/food_full.csv \
  --file food_alias:data/seeds/food_alias_full.csv
# 再把真实 food_id 回填进 seed_ids.json（seed_bulk 不做这件事）
#   $PY -c "import asyncio,asyncpg,json; ..."  # 见下方「已知缺口」

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

# 4) AI 对话压测（需 .env 配好 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL）
$PY perf/ai_chat_bench.py
```

场景：`account_today` / `food_search` / `order_create` / `order_list` /
`meal_page` / `meal_write`。

## 已知缺口

- **`seed_bulk.py` 不灌 food 种子**，`seed_ids.json` 的 `food_id` 为 `null`，
  `meal_write` 场景会全量 `422/2001`。须按上方步骤 0 补灌并回填 food_id。
- **配额会拦 AI 压测**：`ai_times_left` 落在 `user_benefit` 表，改 `.env` 的
  `AI_DAILY_TIMES` **只影响新用户**，对已有用户无效。跑 50 次需先重置：
  ```sql
  UPDATE user_benefit SET ai_times_left = 100,
                         ai_times_reset_at = now() - interval '1 day'
   WHERE user_id = 1;
  ```
- `/api/ai/chat` 的 `session_id` 是**必填** uuid，漏了返回 `422/2001`。


## 实测结果（2026-10-04）

环境：Windows 11 / Python 3.12.12 venv / PostgreSQL 16 + Redis 7（compose 栈）/
模型 `deepseek-v4.1-flash`（阿里百炼 OpenAI 兼容端点，**已关闭思考链**）。
被测服务为**单 uvicorn worker**，`RATE_LIMIT_ENABLED=false`，数据规模 100 万行
`meal_record` + 200 订单 + 1750 行食物库。

### 接口压测（对照文档 §9.4）

| 场景 | 并发 | QPS | P50 | P95 | P99 | 错误率 | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `food_search` | 20 | 234.2 | 81ms | 127ms | 132ms | 0% | PASS（查询 <300ms） |
| `order_list` | 20 | 199.6 | 94ms | 145ms | 166ms | 0% | PASS |
| `account_today` | 20 | 130.9 | 143ms | 178ms | 358ms | 0% | PASS |
| `order_create` | 10 | 133.6 | 74ms | 99ms | 109ms | 0% | PASS（写 <800ms） |
| `meal_write` | 10 | 91.4 | 107ms | 126ms | 169ms | 0% | PASS |
| `meal_page` p=5000 | 1 | 142.3 | 6.9ms | 7.9ms | 8.7ms | 0% | PASS |
| `meal_page` p=9999 | 1 | 142.8 | 6.9ms | 8.0ms | 8.8ms | 0% | PASS |

**深分页无塌陷**：100 万行下翻到第 9999 页 P95 仍 8.8ms，证明迁移 0002 建的
`(user_id, created_at DESC, id DESC)` 索引生效。

**并发拐点在 20**：`account_today` c=20→130.9 QPS，c=50→116.3，c=100→110.3
（QPS 反降、P50 从 143ms 涨到 706ms）。单 worker 串行 + 该接口单请求内跑多条 SQL
（热量引擎/摄入/运动/步数）CPU 密集；PG 连接数 21 = 池上限 20+1，无泄漏。
**要提吞吐需多 worker 或加缓存。**

### AI 对话压测（50 次 × 2s 间隔，串行）

| 指标 | 值 |
| --- | --- |
| 成功 / 总数 | **50 / 50（错误率 0%）** |
| 降级（6001） | 0 |
| min | 1390ms |
| P50 | 2272ms |
| **P95** | **3617ms** |
| P99 | 7595ms |
| max | 8392ms |
| avg | 2529ms |

**关闭思考链是关键**。`deepseek-v4.1-flash` 是推理模型，非流式下思考链会吃掉
绝大部分 token（实测 `reasoning_tokens=345` vs `text_tokens=178`）：

| 配置 | P95 | reasoning |
| --- | --- | --- |
| 默认开启思考 | 11246ms | 345 tokens |
| **`enable_thinking: false`** | **3617ms** | 无 |

同 prompt 单次实测：4433ms → 1122ms（**4 倍**）。参数探测结论：
`enable_thinking: false` 最优；`reasoning_effort: none` 等价稍慢；
`thinking: false` 报 400（该端点要求 json_object）；`extra_body.enable_thinking`
**无效**（那是 LangChain 封装，直连 OpenAI 兼容接口不认）。

> §9.4 原文写「AI 对话 P95 < 3s」，本次实测 3617ms；`config.py` 注释与
> `AI_TIMEOUT` 默认值均为 5s（超时降级阈值），3617ms 在 5s 内。
> 残余超标来自两次尾部尖刺（#32 8392ms、#42 6766ms），去掉后 P95 约 2.6s。
> 彻底达标需：换非推理模型 / 上流改流式 / 压 `max_tokens`。

## 百万行分页双证据

```bash
PGPASSWORD=postgres psql -h 127.0.0.1 -U postgres -d ai_coach_perf -c \
 "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM meal_record WHERE user_id=<id> \
  ORDER BY created_at DESC, id DESC OFFSET 499900 LIMIT 100;"
```