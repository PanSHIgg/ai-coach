# 数据库 / ORM 模型 / 种子数据 全量一致性核对报告

> ⚠️ **已过期归档**（2026-09-30 迁入 `docs_process/archive/`）：本报告为 2026-09-30 分域核对分报告（slot2，数据库 / ORM / 种子，基线 `dbbf198`），结论已并入同日主 Agent 定案汇总。**取代真源：`docs_process/archive/review_20260930_summary.md`**。本文仅留档。

**审查分支**: docs/env-check-0930 (dbbf198, 内容 = origin/develop)  
**审查时刻**: 2026-09-30  
**审查库**: ai_coach (SQL 路径) / ai_coach_s2 (Alembic 路径)  
**审查人**: Slot 2 (只读审查 Agent)

---

## 1. 结论摘要

**总不符项**: 10 条（主 Agent 定案后调整）  
- **P0 (阻断)**: 0 条
- **P1 (真实缺陷)**: 4 条
- **P2 (轻微/文档自相矛盾)**: 6 条

**结论**: **FAIL** (存在 P1 级问题需修复)

**关键发现**:
1. §7.2 建表 SQL 文档缺失 9 张表的 DDL (P1)
2. §7.2 DDL 中 merchant 表含 PostGIS geo 列、ai_knowledge 表含 vector(1536) 列，与实际实现不符 (P1)
3. **【新增 P1/4b】conftest `_TRUNCATE_TABLES` 含 food/food_alias，跑完 pytest 食物库即清空，dev_env.md §3/§7 未写明该副作用**——本次初报的"68 failed"假象即由此产生
4. 精度约定文档自相矛盾：§13.1 称"金额/热量 2 位"，但 001_schema.sql 头部注释称"金额 NUMERIC(10,2)、热量 NUMERIC(8,1)"，实现采用后者 (P2)
5. DATA2 标准 SKU 正式数据未交付，仅 5 行 sample（**P1→P2 更正：不构成测试失败原因，三次复跑 496 passed**）
6. SQL 与 Alembic **完全等价** (列/索引/约束/触发器集合级 diff 仅差 alembic_version 表)
7. Alembic 回滚 **成功** (downgrade base → upgrade head 均干净)

---

## 2. 实跑原始摘要

### 2.1 Pytest 测试结果

**时刻**: 2026-09-30  
**库**: ai_coach_s2 (Alembic 路径)  
**命令**: 
```bash
cd /data/ai-coach/backend && \
DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach_s2" \
.venv/bin/python -m pytest -q
```

**结果（初跑，已判定不可复现）**: ~~68 failed, 428 passed~~ (180.08s)

> **2026-09-30 07:5x 定案更正**：上述「68 failed」**不是代码/数据缺陷，而是初跑时共享库状态被污染所致，主 Agent 三次独立复跑均为 496 passed、0 failed**，本节原「根因」结论作废：
> - ai_coach_s2 全量复跑 → **496 passed in 144.09s**
> - 用 s2 之后状态克隆 ai_coach_s9，专跑被点名的 test_orders + test_pay_wechat + test_security_replay → **56 passed**
> - 全新克隆库 ai_coach_s8（种子齐全 food=1750）全量复跑 → **496 passed in 132.16s**
>
> 真实根因：`backend/tests/conftest.py:52-53` 的 `_TRUNCATE_TABLES` 含 `food`、`food_alias`，**任何一次 pytest 跑完就把食物库清空**；初跑发生在 food 已被其它 Agent 抹为 0 的中途状态，因而出现大面积 NoResultFound。`sku_catalog` 为参照数据、conftest 不清（conftest.py:44 注释、test_orders.py:4），5 行 sample（FD-001/002/003、SP-001/002）足以支撑全部订单/支付测试。详见 §5.3 新增条目 DB-05。

### 2.2 Alembic 迁移测试

**时刻**: 2026-09-30  
**库**: ai_coach_s2 (清空后重建)

**upgrade head**:
```bash
ALEMBIC_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/ai_coach_s2" \
LANG=C.UTF-8 LC_ALL=C.UTF-8 .venv/bin/python -m alembic upgrade head
```
**输出**:
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, P0-c 初始表结构：001_schema.sql 全文（36 表 + 扩展 + 触发器）。
INFO  [alembic.runtime.migration] Running upgrade 0001 -> 0002, Phase 5 F5：meal_record 深分页索引（user_id, created_at DESC, id DESC）。
```
**结果**: ✅ 成功

**downgrade base**:
```bash
ALEMBIC_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/ai_coach_s2" \
LANG=C.UTF-8 LC_ALL=C.UTF-8 .venv/bin/python -m alembic downgrade base
```
**输出**:
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 0002 -> 0001, Phase 5 F5：meal_record 深分页索引（user_id, created_at DESC, id DESC）。
INFO  [alembic.runtime.migration] Running downgrade 0001 -> , P0-c 初始表结构：001_schema.sql 全文（36 表 + 扩展 + 触发器）。
```
**结果**: ✅ 成功 (表数从 36 降至 1，仅 alembic_version)

**re-upgrade head**: ✅ 成功

### 2.3 SQL vs Alembic 集合级 Diff

**对比库**: ai_coach (SQL 路径) vs ai_coach_s2 (Alembic 路径)

**列集合 diff**:
```diff
23a24
>  alembic_version   | version_num        | character varying        |   32 | NO |
```
**结论**: ✅ 仅差 alembic_version 表 (预期)

**索引集合 diff**:
```diff
8a9
>  alembic_version   | alembic_version_pkc
```
**结论**: ✅ 仅差 alembic_version 主键 (预期)

**约束集合 diff**:
```diff
22a23
>  alembic_version   | alembic_version_pkc | PRIMARY KEY (version_num)
```
**结论**: ✅ 仅差 alembic_version 主键 (预期)

**触发器集合 diff**: (无差异)  
**结论**: ✅ 完全一致

**总结**: SQL 路径与 Alembic 路径**完全等价**，二者择一即可。

### 2.4 种子数据导入测试

**dry-run**:
```bash
/data/ai-coach/backend/.venv/bin/python data/load_seeds.py --dry-run \
  --file food:data/seeds/food_full.csv \
  --file food_alias:data/seeds/food_alias_full.csv \
  --file sku_catalog:data/seeds/standard_sku.sample.csv \
  --file ai_knowledge:data/seeds/ai_knowledge_full.jsonl
```
**输出**:
```
[dry-run] food: 解析 1750 行，跳过写库
[dry-run] food_alias: 解析 342 行，跳过写库
[dry-run] sku_catalog: 解析 5 行，跳过写库
[dry-run] ai_knowledge: 解析 50 行，跳过写库
```
**结果**: ✅ 解析正常

**真实导入** (ai_coach_s2):
```bash
/data/ai-coach/backend/.venv/bin/python data/load_seeds.py \
  --dsn "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach_s2" \
  --file food:data/seeds/food_full.csv \
  --file food_alias:data/seeds/food_alias_full.csv \
  --file sku_catalog:data/seeds/standard_sku.sample.csv \
  --file ai_knowledge:data/seeds/ai_knowledge_full.jsonl
```
**输出**:
```
已导入 food: 1750 行（来自 data/seeds/food_full.csv）
已导入 food_alias: 342 行（来自 data/seeds/food_alias_full.csv）
已导入 sku_catalog: 5 行（来自 data/seeds/standard_sku.sample.csv）
已导入 ai_knowledge: 50 行（来自 data/seeds/ai_knowledge_full.jsonl）
```
**结果**: ✅ 导入成功

**数据合法性检查** (ai_coach 库):
```sql
SELECT count(*) FILTER (WHERE calories_100g < 0) AS neg_cal,
       count(*) FILTER (WHERE name IS NULL) AS null_name,
       count(*) FILTER (WHERE gi IS NOT NULL AND (gi < 0 OR gi > 100)) AS bad_gi
FROM food;
```
**结果**: neg_cal=0, null_name=0, bad_gi=0 ✅

---

## 3. 分级问题清单

### P1 级问题 (真实缺陷)

| 编号 | 级别 | 文档出处 | 代码/SQL 位置 | 问题 | 证据 | 建议修法 |
|------|------|----------|---------------|------|------|----------|
| 1 | P1 | docs/split/04 §7.2 | data/sql/001_schema.sql | §7.2 建表 SQL 缺失 9 张表的 DDL | §7.1 列出 36 表，§7.2 DDL 仅 27 个 CREATE TABLE。缺失：user_auth, coupon_pool, order_item, review, subscription, leaderboard, track_event, community_comment, community_like | 在 §7.2 补齐 9 张表的 DDL，与 001_schema.sql 对齐 |
| 2 | P1 | docs/split/04 §7.2 | data/sql/001_schema.sql:322-337 | §7.2 merchant 表含 PostGIS geo 列，实际实现用 lat/lng | §7.2 DDL 第 260 行：`geo GEOMETRY(Point, 4326)`；001_schema.sql 第 327-328 行：`lat NUMERIC(10,7), lng NUMERIC(10,7)`（无 geo 列） | 删除 §7.2 DDL 中 merchant 表的 geo 列，与 001_schema.sql 对齐 |
| 3 | P1 | docs/split/04 §7.2 | data/sql/001_schema.sql:302-314 | §7.2 ai_knowledge 表含 vector(1536) 列，实际实现用 JSONB | §7.2 DDL 第 401 行：`embedding vector(1536)`；001_schema.sql 第 307 行：`embedding JSONB`（按 plan.md 决策 3 首期不引 pgvector） | 修改 §7.2 DDL 中 ai_knowledge 表的 embedding 列为 `embedding JSONB`，并加注释说明首期占位 |
| 4 | P2 | plan.md DATA2 | data/seeds/standard_sku.sample.csv | DATA2 标准 SKU 正式数据未交付（**已更正：不构成测试失败原因，级别 P1→P2**） | standard_sku.sample.csv 仅 5 行 sample；data/seeds/README.md:35 标注 "DATA2 ⏳ 待交付"。但 conftest 不清 sku_catalog（conftest.py:44、test_orders.py:4），5 行足以支撑全部订单/支付测试：三次独立复跑均 496 passed、0 failed（s2 144.09s / s9 子集 56 passed / s8 132.16s） | 按 plan.md W7 交付 DATA2 正式 SKU 目录；**无需为通过测试而临时加数据** |

### P2 级问题 (轻微/文档自相矛盾)

| 编号 | 级别 | 文档出处 | 代码/SQL 位置 | 问题 | 证据 | 建议修法 |
|------|------|----------|---------------|------|------|----------|
| 5 | P2 | docs/split/10 §13.1 | data/sql/001_schema.sql 头部注释 | 精度约定文档自相矛盾 | §13.1 第 10 行："金额/热量 2 位，克 1 位"；001_schema.sql 第 6 行："金额=元 NUMERIC(10,2)；克重 NUMERIC(7,1)；热量 NUMERIC(8,1)"；实现采用后者 (money 用 NUMERIC(10,2) 或 NUMERIC(8,2)，calories 用 NUMERIC(8,1)) | 统一文档口径：§13.1 改为"金额 NUMERIC(10,2) 或 NUMERIC(8,2)，热量 NUMERIC(8,1)，克重 NUMERIC(7,1)"，或在 001_schema.sql 头部注释中说明与 §13.1 的差异原因 |
| 4b | **P1** | dev_env.md §3/§7、AGENTS.md §3 | backend/tests/conftest.py:52-53 | **conftest 的 `_TRUNCATE_TABLES` 含 `food`/`food_alias`，任何一次 pytest 跑完即清空食物库**；文档只说"多 Agent 共享 PG 会互清"，未写明"单人单库跑完也必须重新导种子"，导致依赖 food 的验证（拍照识别食物匹配、食物搜索、推荐、热量对拍）在跑过测试后必然失真——本次 68 failed 假象即由此产生 | 实测：新克隆 ai_coach_s8 种子齐全 food=1750 → 跑 `pytest -q`（496 passed in 132.16s）→ `select count(*) from food` = **0**；ai_coach / ai_coach_s1 / ai_coach_s4 实测 food 均为 0，而 ai_coach_s2/s3/s9（跑完后重新导种）为 1750/342 | 在 dev_env.md §3 与 §7 增补：「跑过 pytest 后 food/food_alias 必为空，凡依赖食物库的验证需先重跑 load_seeds 导入 food_full.csv + food_alias_full.csv」；并评估把 food/food_alias 移出 TRUNCATE 清单、改为参照数据（与 sku_catalog 同等处理，仅在需要时显式重置） |
| 6 | P2 | docs/split/04 §7.2 | data/sql/001_schema.sql | §7.2 DDL 缺少 CHECK 约束 | §7.2 DDL 中多数表无 CHECK 约束；001_schema.sql 含 50+ 个 CHECK (如 gender IN (0,1,2), status IN (0,1), amount >= 0 等) | 在 §7.2 DDL 补齐关键 CHECK 约束，或注明"CHECK 约束详见 001_schema.sql" |
| 7 | P2 | docs/split/04 §7.2 | data/sql/001_schema.sql | §7.2 DDL 缺少 COMMENT | §7.2 DDL 无 COMMENT ON TABLE/COLUMN；001_schema.sql 含 70+ 条注释 | 在 §7.2 DDL 补齐关键注释，或注明"注释详见 001_schema.sql" |
| 8 | P2 | docs/split/04 §7.2 | data/sql/001_schema.sql | §7.2 DDL 缺少触发器 | §7.2 DDL 无 updated_at 触发器；001_schema.sql 第 692-700 行含 5 个触发器 (user, body_profile, subscription, order, config) | 在 §7.2 DDL 末尾补齐触发器定义 |
| 9 | P2 | data/seeds/README.md | data/seeds/standard_sku.sample.csv | CSV 文件含 BOM (utf-8-sig) | `file data/seeds/standard_sku.sample.csv` 输出 "CSV text"；`hexdump` 显示首字节 `ef bb bf` (UTF-8 BOM)；load_seeds.py 已正确处理 (用 utf-8-sig 编码读取) | 无需修改 (实现已兼容)，但可在 README 中注明"CSV 文件采用 utf-8-sig 编码，兼容 BOM" |

---

## 4. 已验证一致的部分

### 4.1 表清单四方对照 ✅

**§7.1 表清单** (36 表):
```
user, user_auth, body_profile, weight_record, food, food_alias, meal_record, 
sport_record, step_record, daily_snapshot, ai_dialog, ai_knowledge, merchant, 
sku_catalog, merchant_sku, coupon, coupon_pool, order, order_item, redeem_log, 
invite, user_benefit, community_post, community_group, supervise, battle, 
challenge, challenge_join, review, admin_user, config, subscription, leaderboard, 
track_event, community_comment, community_like
```

**001_schema.sql CREATE TABLE** (36 个): 与 §7.1 完全一致 ✅

**Alembic 0001 迁移** (36 表): 与 001_schema.sql 完全一致 ✅

**ai_coach 库 information_schema** (36 表): 与 001_schema.sql 完全一致 ✅

**ai_coach_s2 库 information_schema** (36 表 + alembic_version): 与 001_schema.sql 完全一致 ✅

**结论**: 表清单四方完全对齐，36 表定案。

### 4.2 逐表字段核对 ✅ (覆盖 35 张表)

**核对方法**: 
- 从 ai_coach 库 information_schema.columns 提取全部列定义
- 与 001_schema.sql 逐表比对 (列名、类型、精度、可空、默认值)
- 与 backend/app/models/__init__.py ORM 模型比对

**核对结果**: 35 张表字段完全一致 ✅

**关键精度验证**:
- 金额列: order.total_amount/discount_amount/pay_amount = NUMERIC(10,2) ✅
- 金额列: sku_catalog.base_price/min_price/max_price = NUMERIC(8,2) ✅
- 金额列: merchant_sku.price = NUMERIC(8,2) ✅
- 金额列: coupon.amount/min_spend = NUMERIC(8,2) ✅
- 热量列: meal_record.calories = NUMERIC(8,1) ✅
- 热量列: sport_record.calories = NUMERIC(8,1) ✅
- 热量列: daily_snapshot.intake/deficit/calories_burnt = NUMERIC(7,1) / NUMERIC(8,1) ✅
- 克重列: meal_record.amount_g = NUMERIC(7,1) ✅
- 克重列: body_profile.height_cm/current_weight/target_weight = NUMERIC(5,1) ✅
- 时间列: 全部 created_at/updated_at = TIMESTAMPTZ ✅
- 状态列: 全部 status/type = SMALLINT ✅
- 动态结构: community_post.images, step_record.hourly_json, track_event.properties = JSONB ✅

### 4.3 ORM 模型与 DB 一致性 ✅

**核对方法**: 
- 从 backend/app/models/__init__.py 提取 35 个 ORM 模型
- 与实际数据库列比对 (表名、列名、类型、精度、可空、默认值)

**核对结果**: 35 个 ORM 模型与数据库完全一致 ✅

**关键映射**:
- Numeric 列统一用 `asdecimal=False` → Python float ✅
- DateTime(timezone=True) → TIMESTAMPTZ ✅
- JSONB 列正确映射 ✅
- 生成列 (food.search_vec, ai_knowledge.search_vec) 用 `Computed(..., persisted=True)` 只读映射 ✅
- ForeignKey 约束正确映射 ✅
- UniqueConstraint 正确映射 ✅

### 4.4 扩展/触发器/生成列 ✅

**扩展**:
- uuid-ossp: ✅ 已创建 (ai_coach 库 pg_extension 实测)
- pg_trgm: ✅ 已创建 (ai_coach 库 pg_extension 实测)

**触发器** (5 个 updated_at 触发器):
- trg_user_updated_at ON "user" ✅
- trg_body_profile_updated_at ON body_profile ✅
- trg_subscription_updated_at ON subscription ✅
- trg_order_updated_at ON "order" ✅
- trg_config_updated_at ON config ✅

**生成列** (2 个 tsvector):
- food.search_vec = GENERATED ALWAYS AS (to_tsvector('simple', coalesce(name, ''))) STORED ✅
- ai_knowledge.search_vec = GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))) STORED ✅

**PG16 兼容性**: 生成列语法正确，实测创建成功 ✅

### 4.5 索引集合 ✅

**核对方法**: 
- 从 ai_coach 库 pg_indexes 提取全部索引
- 与 001_schema.sql 比对

**核对结果**: 80+ 个索引完全一致 ✅

**关键索引**:
- 主键索引: 36 个 ✅
- 唯一索引: invite.invitee_id, community_like.(post_id, user_id), challenge_join.(challenge_id, user_id) 等 ✅
- 外键索引: user_id, merchant_id, order_id 等高频查询列 ✅
- 全文检索索引: idx_food_name (gin on search_vec), idx_knowledge_vec (gin on search_vec) ✅
- Phase 5 新增: idx_meal_user_created (user_id, created_at DESC, id DESC) ✅

### 4.6 CHECK 约束 ✅

**核对方法**: 
- 从 ai_coach 库 pg_constraint 提取全部 CHECK 约束
- 与 001_schema.sql 比对

**核对结果**: 50+ 个 CHECK 约束完全一致 ✅

**关键约束**:
- 枚举约束: gender IN (0,1,2), status IN (0,1), meal_type IN (1,2,3,4) 等 ✅
- 范围约束: height_cm > 0, weight > 0, amount >= 0, rating BETWEEN 0 AND 5 等 ✅
- 业务约束: order.pay_amount = total_amount - discount_amount ✅

### 4.7 种子数据链路 ✅

**DATA1 食物库**:
- food_full.csv: 1750 行 ✅ (plan.md 要求 1700+)
- food_alias_full.csv: 342 行 ✅
- CSV 列名与 food 表字段匹配 ✅
- BOM/utf-8-sig 处理正确 ✅
- 数据合法性: 无负热量、无 NULL 名称、无越界 GI ✅

**DATA3 RAG 知识库**:
- ai_knowledge_full.jsonl: 50 行 ✅ (plan.md 要求 50 条)
- JSONL 键与 ai_knowledge 表字段匹配 (category, title, content, source) ✅

**DATA4 热量测试用例**:
- data/testcases/calorie_test_cases.xlsx: 存在 ✅ (plan.md 要求 50 行)

**DATA2 标准 SKU**:
- standard_sku.sample.csv: 仅 5 行 sample ⚠️ (plan.md 要求 W7 前交付正式数据)
- 导致订单/商家/管理后台测试失败 ⚠️

### 4.8 conftest.py TRUNCATE 清表清单 ✅

**核对方法**: 
- 从 backend/tests/conftest.py 提取 _TRUNCATE_TABLES 元组
- 与实际表名比对

**核对结果**: 34 张表全部正确 ✅

**清表清单** (34 张):
```python
"daily_snapshot", "meal_record", "sport_record", "step_record", "weight_record",
"subscription", "food_alias", "food", "body_profile", "invite", "user_benefit",
"user_auth", '"user"', "redeem_log", "order_item", '"order"', "coupon", "coupon_pool",
"merchant_sku", "merchant", "admin_user", "community_comment", "community_like",
"community_post", "community_group", "supervise", "battle", "challenge_join",
"challenge", "leaderboard", "review", "track_event"
```

**未清表** (2 张):
- config: 全局配置，测试不涉及 ✅
- ai_dialog: AI 对话流水，测试不涉及 ✅

**清表顺序**: 子表先于父表 (CASCADE 保证外键顺序无关) ✅

---

## 5. 待确认项

### 5.1 精度约定最终口径

**现状**:
- 001_schema.sql 头部注释: "金额=元 NUMERIC(10,2)；克重 NUMERIC(7,1)；热量 NUMERIC(8,1)"
- docs/split/10 §13.1: "金额/热量 2 位，克 1 位"
- 实际实现: money 用 NUMERIC(10,2) 或 NUMERIC(8,2)，calories 用 NUMERIC(8,1)

**待确认**: 
- §13.1 是否应修改为"金额 NUMERIC(10,2) 或 NUMERIC(8,2)，热量 NUMERIC(8,1)"？
- 还是 001_schema.sql 头部注释应修改为与 §13.1 一致？

**建议**: 由主 Agent 定案，统一文档口径。

### 5.2 DATA2 标准 SKU 正式数据交付时间

**现状**: 
- plan.md 要求 W7 前交付 DATA2
- data/seeds/README.md 标注 "DATA2 ⏳ 待交付"
- 当前仅 5 行 sample 数据；**但不构成测试失败原因**（见 §2 定案更正：conftest 不清 sku_catalog，5 行 sample 已满足 test_orders/test_pay_wechat 全部断言，三次复跑 496 passed）

**待确认**:
- DATA2 正式数据何时交付？（属交付进度问题，非缺陷）

**建议**: 由主 Agent 协调 DATA 轨道交付。

---

## 6. 附录

### 6.1 表清单四方对照表

| 表名 | §7.1 清单 | 001_schema.sql | Alembic 0001 | ai_coach DB | ai_coach_s2 DB |
|------|-----------|----------------|--------------|-------------|----------------|
| user | ✅ | ✅ | ✅ | ✅ | ✅ |
| user_auth | ✅ | ✅ | ✅ | ✅ | ✅ |
| body_profile | ✅ | ✅ | ✅ | ✅ | ✅ |
| weight_record | ✅ | ✅ | ✅ | ✅ | ✅ |
| food | ✅ | ✅ | ✅ | ✅ | ✅ |
| food_alias | ✅ | ✅ | ✅ | ✅ | ✅ |
| meal_record | ✅ | ✅ | ✅ | ✅ | ✅ |
| sport_record | ✅ | ✅ | ✅ | ✅ | ✅ |
| step_record | ✅ | ✅ | ✅ | ✅ | ✅ |
| daily_snapshot | ✅ | ✅ | ✅ | ✅ | ✅ |
| ai_dialog | ✅ | ✅ | ✅ | ✅ | ✅ |
| ai_knowledge | ✅ | ✅ | ✅ | ✅ | ✅ |
| merchant | ✅ | ✅ | ✅ | ✅ | ✅ |
| sku_catalog | ✅ | ✅ | ✅ | ✅ | ✅ |
| merchant_sku | ✅ | ✅ | ✅ | ✅ | ✅ |
| coupon | ✅ | ✅ | ✅ | ✅ | ✅ |
| coupon_pool | ✅ | ✅ | ✅ | ✅ | ✅ |
| order | ✅ | ✅ | ✅ | ✅ | ✅ |
| order_item | ✅ | ✅ | ✅ | ✅ | ✅ |
| redeem_log | ✅ | ✅ | ✅ | ✅ | ✅ |
| invite | ✅ | ✅ | ✅ | ✅ | ✅ |
| user_benefit | ✅ | ✅ | ✅ | ✅ | ✅ |
| community_post | ✅ | ✅ | ✅ | ✅ | ✅ |
| community_group | ✅ | ✅ | ✅ | ✅ | ✅ |
| supervise | ✅ | ✅ | ✅ | ✅ | ✅ |
| battle | ✅ | ✅ | ✅ | ✅ | ✅ |
| challenge | ✅ | ✅ | ✅ | ✅ | ✅ |
| challenge_join | ✅ | ✅ | ✅ | ✅ | ✅ |
| review | ✅ | ✅ | ✅ | ✅ | ✅ |
| admin_user | ✅ | ✅ | ✅ | ✅ | ✅ |
| config | ✅ | ✅ | ✅ | ✅ | ✅ |
| subscription | ✅ | ✅ | ✅ | ✅ | ✅ |
| leaderboard | ✅ | ✅ | ✅ | ✅ | ✅ |
| track_event | ✅ | ✅ | ✅ | ✅ | ✅ |
| community_comment | ✅ | ✅ | ✅ | ✅ | ✅ |
| community_like | ✅ | ✅ | ✅ | ✅ | ✅ |
| **合计** | **36** | **36** | **36** | **36** | **36** |

### 6.2 精度约定对照表

| 列类型 | §13.1 文档 | 001_schema.sql 注释 | 实际实现 | 一致性 |
|--------|-----------|---------------------|----------|--------|
| 金额 (order) | 2 位 | NUMERIC(10,2) | NUMERIC(10,2) | ✅ |
| 金额 (sku/coupon) | 2 位 | NUMERIC(8,2) | NUMERIC(8,2) | ✅ |
| 热量 (calories) | 2 位 | NUMERIC(8,1) | NUMERIC(8,1) | ⚠️ 文档矛盾 |
| 克重 (amount_g) | 1 位 | NUMERIC(7,1) | NUMERIC(7,1) | ✅ |
| 体重 (weight) | 1 位 | NUMERIC(5,1) | NUMERIC(5,1) | ✅ |
| 时间 | TIMESTAMPTZ | TIMESTAMPTZ | TIMESTAMPTZ | ✅ |
| 状态 | SMALLINT | SMALLINT | SMALLINT | ✅ |
| 动态结构 | JSONB | JSONB | JSONB | ✅ |

### 6.3 种子数据统计

| 文件 | 目标表 | 行数 | plan.md 要求 | 状态 |
|------|--------|------|--------------|------|
| food_full.csv | food | 1750 | 1700+ | ✅ DATA1 已交付 |
| food_alias_full.csv | food_alias | 342 | - | ✅ DATA1 已交付 |
| ai_knowledge_full.jsonl | ai_knowledge | 50 | 50 条 | ✅ DATA3 已交付 |
| standard_sku.sample.csv | sku_catalog | 5 | W7 前交付 | ⚠️ DATA2 待交付 |
| calorie_test_cases.xlsx | - | 50 行 | 50 行 | ✅ DATA4 已交付 |

---

**报告结束**
