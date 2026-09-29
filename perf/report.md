# F5 性能测试报告

> 数据来源：`perf/seed_bulk.py` 灌入 + `perf/harness.py` 真跑实测。**全部为真实执行所得，
> 未编造**。测量时刻：2026-09-29（Asia/Shanghai）。

## 一、实测参数与环境

| 项 | 值 |
| --- | --- |
| 数据库 | `postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach_perf` |
| 数据规模 | `meal_record` 1,000,000 行（全部归属压测用户）；`"order"` 200 行；`food` 1750 行 |
| meal_record 体积 | 143 MB（`pg_total_relation_size`） |
| 被测服务 | `uvicorn app.main:app --port 8003`，**单进程单 worker** |
| 限流 | `RATE_LIMIT_ENABLED=false`（否则全局 100/min/IP 会先触发 429，无法压测） |
| JWT | `JWT_SECRET=perf-secret-hs256-key-0123456789`（harness 直接签发 C 端 token） |
| 压测客户端 | httpx 0.28.1（AsyncClient + asyncio，串行任务，低并发） |
| 机器 | cgroup 内存 4 GiB、无 swap、3 vCPU |
| PostgreSQL | 16.15，shared_buffers=128 MB，max_connections=100 |
| 连接池 | **采集时点**应用用 `NullPool`（`app/db/session.py`，每请求新建 PG 连接）；**Phase 5 已默认启用真实异步连接池**（`DB_POOL_DISABLED=true` 才回退 NullPool） |
| 并发/时长 | 见下表（**未做满 100 并发 5 分钟**，原因见第四节） |

## 二、各接口实测（QPS / P50 / P95 / P99 / 错误率）

单位：ms；`err%` = 非 200 或业务码≠0 的比例。

| 场景 | 并发 | 时长s | 请求数 | QPS | P50 | P95 | P99 | err% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GET /api/account/today | 5 | 15.14 | 306 | 20.2 | 246.7 | **290.0** | 312.7 | 0 |
| GET /api/account/today | 20 | 15.53 | 341 | 22.0 | 905.6 | **1014.8** | 1130.1 | 0 |
| GET /api/account/today | 100 | 12.21 | 264 | 21.6 | 3787.1 | **8233.3** | 10192.0 | 0 |
| POST /api/food/search | 5 | 15.08 | 519 | 34.4 | 144.4 | **184.7** | 205.6 | 0 |
| POST /api/food/search | 20 | 15.19 | 568 | 37.4 | 530.3 | **620.3** | 657.3 | 0 |
| GET /api/order/list | 5 | 15.06 | 558 | 37.0 | 132.2 | **171.2** | 187.9 | 0 |
| GET /api/order/list | 20 | 15.19 | 594 | 39.1 | 506.1 | **617.6** | 689.2 | 0 |
| POST /api/order（下单/写） | 20 | 15.54 | 302 | 19.4 | 1000.3 | **1229.0** | 1414.8 | 0 |
| POST /api/meal（写+重算） | 10 | 15.09 | 498 | 33.0 | 300.6 | **368.5** | 416.1 | 0 |
| GET /api/meal/list page=1 size=20 | 1 | 10.10 | 76 | 7.5 | 127.6 | **155.1** | 157.6 | 0 |
| GET /api/meal/list page=1 size=20 | 20 | 16.33 | 125 | 7.7 | 2526.3 | **3364.9** | 3389.3 | 0 |
| GET /api/meal/list page=5000 size=100 | 1 | 10.55 | 15 | 1.4 | 710.8 | **739.2** | 741.0 | 0 |
| GET /api/meal/list page=5000 size=100 | 10 | 16.70 | 37 | 2.2 | 3872.8 | **6051.8** | 6226.8 | 0 |

## 三、百万行分页双证据（EXPLAIN ANALYZE + 实测）

对 `meal_record`（1,000,000 行，压测用户占 100%）执行与 `record_service.list_meals`
等价的查询：

| 查询 | EXPLAIN ANALYZE 执行时间 | 实测 P95（并发 1） | 备注 |
| --- | --- | --- | --- |
| `COUNT(*) WHERE user_id=?` | 86.6 ms | — | Parallel Seq Scan |
| `... ORDER BY created_at DESC,id DESC LIMIT 20`（page 1） | 110.98 ms | 155.1 ms | Parallel Seq Scan + top-N heapsort |
| `... OFFSET 499900 LIMIT 100`（page 5000） | **921.92 ms** | **739.2 ms** | Parallel Seq Scan + **external merge sort**（temp read=11050 blk，落盘） |

深分页执行计划关键片段：

```
Limit (actual time=862.466..880.166 rows=100)
  -> Gather Merge (actual time=695.572..851.103 rows=500000)
       -> Sort (Sort Key: created_at DESC, id DESC)
            Sort Method: external merge  Disk: 35792kB   <-- 全量排序落盘
            -> Parallel Seq Scan on meal_record  Filter: (user_id = 1)
Execution Time: 921.918 ms
```

## 四、是否达标（对齐 plan §11 F5）

| F5 目标 | 实测结论 | 判定 |
| --- | --- | --- |
| 单接口 P95<300ms（查询） | 低并发(c=5)：food_search 184.7、order_list 171.2 ✓；account_today 290.0 勉强 ✓ | **部分达标** |
| 同上，中并发(c=20) | account_today 1014.8、food_search 620.3、order_list 617.6 全超 | **不达标** |
| 写+重算<800ms | meal_write(c=10) P95=368.5 ✓；order_create(c=20) P95=1229.0 ✗ | **部分达标** |
| 100 并发 5 分钟错误率<1%、无内存泄漏 | 本机无法跑满 5min；改以 c=100/12.2s 探测：**错误率 0%**，但 P95=8233ms、吞吐饱和 | **错误率暂达标，延迟不达标** |
| 百万行分页<500ms | 首页(page=1) P95=155.1 ✓；深页(page=5000, offset≈50w) P95=739.2 / EXPLAIN 921.9 ✗ | **浅页达标，深页不达标** |

## 五、偏差与原因

1. **未做满「100 并发 5 分钟」**（如实标注）：本机 cgroup 4 GiB、无 swap、3 核，且
   应用为 **NullPool + 单 worker**，c≥20 时 P95 已达 1~6s。跑满 100 并发 5min 既无
   代表性（环境非生产规格），又可能拖垮并行协作的其它 Agent。故改以 c=100/12.2s 做
   「错误率」探测，并保留 c=5/20 的延迟曲线。
2. **`NullPool` 主导退化**（**采集时点**：2026-09-29，应用仍为 NullPool）：`app/db/session.py`
   当时用 `NullPool`（pytest 跨事件循环所需），每请求新建 PG 连接（TCP + scram 认证 + fetch 系统目录）。
   低并发下 account_today 已 ~247ms（写快照 + 提交 fsync + 建连）；并发升高后建连成本叠加，吞吐在
   **c≈5 时即饱和**（写类 ~20 QPS），继续加并发只增延迟不增吞吐（见 c=5/20/100 QPS 恒 ~20-22）。
   > 后续变更：**Phase 5 已将 `app/db/session.py` 默认改为真实异步连接池**（SQLAlchemy 默认
   > `AsyncAdaptedQueuePool`；`DB_POOL_DISABLED=true` 才回退 `NullPool`），本节数字为**改动前基线**，
   > 连接池生效后的复测待补（见 §六）。
3. **深分页为全量排序**：`meal_record` 仅有 `(user_id, record_date DESC, meal_type)`
   索引，列表按 `created_at DESC, id DESC` 排序，导致 `OFFSET` 深页需对 100 万行**全量
   排序并落盘**（external merge，35 MB），故 page=5000 从 111ms 涨到 922ms。
4. **单进程无并发**：uvicorn 单 worker，3 核未利用；GIL/FastAPI 同步段在高并发下排队。

## 六、优化建议（原「仅建议」清单；连接池已由 Phase 5 实施）

| 级别 | 位置 | 最小改法 |
| --- | --- | --- |
| ~~P1~~ **已完成** | `app/db/session.py` | **Phase 5 已默认启用真实异步连接池**（`pool_pre_ping` + `pool_size`/`max_overflow`/`pool_recycle`；`DB_POOL_DISABLED=true` 才回退 `NullPool`）。连接池生效后的 c=20/写类复测待补 |
| P1 | `app/services/record_service.py:332`（list_meals） | 深分页改 keyset：`WHERE user_id=? AND (created_at,id) < (?,?) ORDER BY created_at DESC,id DESC LIMIT ?`；或新增索引 `CREATE INDEX ix_meal_user_created ON meal_record(user_id, created_at DESC, id DESC)` |
| P2 | 部署（deploy/nginx.conf / Dockerfile） | uvicorn 多 worker（本机 3 核 → `--workers 3`）；生产按核数配置 |
| P2 | `app/services/record_service.py:346` | 列表 `total` 与分页查询解耦成本；高频列表可缓存 count 或用 `count(*) OVER()` 窗口函数一次成型 |
| P2 | `app/core/rate_limit.py` | 全局 100/min/**IP** 对单 IP 突发（如小程序聚合出口）误伤，建议改按用户维度或提高阈值 |

## 七、复现命令

```bash
PY=/workspace/.venv312/bin/python
cd /workspace/ai-coach
$PY perf/seed_bulk.py            # 1,000,000 行 meal + 200 order
cd backend && DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach_perf" \
  RATE_LIMIT_ENABLED=false JWT_SECRET="perf-secret-hs256-key-0123456789" \
  $PY -m uvicorn app.main:app --port 8003 --log-level warning &
cd /workspace/ai-coach
$PY perf/harness.py --scenario account_today --concurrency 5 --duration 15 \
  --jwt-secret "perf-secret-hs256-key-0123456789"
$PY perf/harness.py --scenario meal_page --page 5000 --page-size 100 --concurrency 1 \
  --duration 10 --jwt-secret "perf-secret-hs256-key-0123456789"
```

## 八、修复后复测（Phase 5 F5 深分页 P1）

> 复测时刻：2026-09-29 15:4x（Asia/Shanghai）；库：`ai_coach_perf`（`meal_record` 1,000,000 行
> 全部归属 `user_id=3`）。**以上第三节原始数据保留，本节为修复后的同查询对比，均为真实执行所得。**

### 8.1 变更

| 项 | 内容 |
| --- | --- |
| 诊断 | 深分页慢因 = **缺索引**：`meal_record` 仅有 `(user_id, record_date DESC, meal_type)`，而列表按 `created_at DESC, id DESC` 排序 → 百万行 Parallel Seq Scan + external merge sort 落盘。 |
| 修复 | 新增索引 `idx_meal_user_created(user_id, created_at DESC, id DESC)`（覆盖过滤列 + 排序键）。 |
| 落地 | `data/sql/001_schema.sql`（新增 CREATE INDEX）+ Alembic `0002_phase5_indexes.py`（`0001→0002`）；已在 `ai_coach_p5c`、`ai_coach_perf` 分别执行生效。 |

> 注：任务书示例索引为 `(user_id, record_date DESC, id DESC)`，但 EXPLAIN 显示查询的排序键是
> `created_at DESC, id DESC`（非 `record_date`），故按诊断结论改用 `created_at` 版本。

### 8.2 EXPLAIN 前后对比（同查询：`WHERE user_id=3 ORDER BY created_at DESC,id DESC OFFSET 499900 LIMIT 100`，取全列）

| 阶段 | 执行计划关键 | Execution Time |
| --- | --- | --- |
| 修复前（真实实测，未建索引） | Gather Merge → **external merge Disk 12416kB** → Parallel Seq Scan | **678.96 ms** |
| 修复前（原始报告，harness 口径） | external merge **Disk 35792kB** | 921.92 ms |
| 修复后（第 1 次，冷） | **Index Scan using idx_meal_user_created**（无 Sort） | 109.28 ms |
| 修复后（连续 5 次热态） | Index Scan（无 Sort） | 84.22 / 78.77 / 81.10 / 77.28 / 76.58 ms |

修复后深分页热态耗时 **76.6 ~ 84.2 ms**（首跑 109.3 ms），远低于 500 ms 门槛；**排序节点消失**，
不再落盘。首页（`LIMIT 100`，offset 0）同步从 254.7 ms 降至 **0.08 ms**（Index Scan）。

修复后 EXPLAIN 关键片段：

```
Limit  (actual time=82.902..82.922 rows=100)
  ->  Index Scan using idx_meal_user_created on meal_record
        Index Cond: (user_id = 3)
Execution Time: 82.969 ms
```

### 8.3 结论

| F5 目标 | 修复前 | 修复后 | 判定 |
| --- | --- | --- | --- |
| 百万行分页 <500ms（浅页 page=1） | 254.7 ms（EXPLAIN 110.98 ms） | **0.08 ms** | 达标 |
| 百万行分页 <500ms（深页 page=5000 / offset≈50w） | 739.2 ms（EXPLAIN 678.96~921.92 ms） | **76.6~84.2 ms**（单次 <500ms） | **达标** |

### 8.4 复现命令

```bash
export PGPASSWORD=postgres
psql -U postgres -h 127.0.0.1 -d ai_coach_perf -c \
  "CREATE INDEX IF NOT EXISTS idx_meal_user_created ON meal_record(user_id, created_at DESC, id DESC);"
psql -U postgres -h 127.0.0.1 -d ai_coach_perf -c \
  "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM meal_record WHERE user_id = 3 \
   ORDER BY created_at DESC, id DESC OFFSET 499900 LIMIT 100;"
```