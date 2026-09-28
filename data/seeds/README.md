# 种子数据说明（P0-c / Phase1 DATA）

本目录存放种子/示例数据。
- **DATA1 食物库已交付**：`food_full.csv`（1700+ 条）+ `food_alias_full.csv`（口语别名）。
- **DATA4 热量对拍用例已交付**：`../testcases/calorie_test_cases.xlsx`（50 行）。
- 其余仍为 `*.sample.*` 示例数据，仅用于联调冒烟，不是正式数据。

## 文件

| 文件 | 目标表 | 说明 |
| --- | --- | --- |
| `food_full.csv` | `food` | **【DATA1 正式】** 食物库 1750 行（表头与 `food.sample.csv` 一致；gi 留空 = NULL；`is_standard=true` 标注标准减脂餐） |
| `food_alias_full.csv` | `food_alias` | **【DATA1 正式】** 食物别名 342 行（表头 `food_name,alias`；覆盖全部 `is_standard` 食物 + 常见口语别名，如 鸡胸肉→鸡胸/鸡脯肉） |
| `food.sample.csv` | `food` | 食物库示例（表头 + 5 行） |
| `standard_sku.sample.csv` | `sku_catalog` | 标准 SKU 目录示例（含价格区间 min/max，商家定价越界后端 400） |
| `rag_knowledge.sample.jsonl` | `ai_knowledge` | RAG 知识库示例（每行一个 JSON 对象） |
| `../testcases/calorie_test_cases.xlsx` | — | **【DATA4 正式】** 热量对拍用例 50 行（期望值由 `app.services.calorie.compute_account` 计算，误差 0） |

### DATA1 生成/复跑（确定性、无随机）

```bash
python3 data/gen_food_seed.py        # 重新生成 food_full.csv / food_alias_full.csv
```

> 生成逻辑：内置 291 条真实常见中式/健身食物基础表 → 按「烹饪方式 / 份量规格」固定规则扩展至 1750 行；
> 变体营养按固定规则调整（加油类增加脂肪/热量，蒸煮类不变，烤类轻微脱水，榨汁类稀释）。名称全局唯一、可读。

## 正式数据交付节点（对齐 plan.md DATA 轨道）

| 编号 | 数据 | 交付节点 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| DATA1 | 食物库 1700+ 条 + food_alias | **W3 前** | ✅ 已交付 | BE3 food/search、BE4a 识别匹配依赖 |
| DATA3 | RAG 知识库语料 + 预置 FAQ | **W5 前** | ⏳ 待交付 | BE4b AI 对话依赖 |
| DATA2 | 标准 SKU 目录（含价格区间） | **W7 前** | ⏳ 待交付 | BE5 商家/目录依赖 |
| DATA4 | 热量测试用例 50 行 / 识别测试图 30 张 | W4 | ✅ 用例已交付（识别图待交付） | QA 对拍用 |

正式文件就绪后由 DATA 轨道放入本目录（建议命名 `food_full.csv` / `standard_sku_full.csv` / `rag_knowledge_full.jsonl`），并用 `--file` 指定导入。

## 数据来源与【假设】

- **【假设】食物营养值为「开发用合理估值」**：基于公开常见食物成分常识的近似值（每 100g 的 kcal/g/g/g），
  **非权威数据源**，仅供联调、检索与识别匹配验证；正式上线前须以权威食物成分表（如《中国食物成分表》）校订。
- 烹饪变体营养由固定规则推算（如「清炒」每 100g 加 4g 油、热量 += 36kcal），属近似估值。
- 别名（`food_alias.alias`）全局唯一，用于 `food.search_vec`（tsvector）之外的别名匹配检索。

## 导入方式

```bash
# 先跑建表 SQL（或 alembic upgrade head）；勿重复建表
psql "$DATABASE_URL" -f data/sql/001_schema.sql

# dry-run（不写库，打印解析行数）
python3 data/load_seeds.py --dry-run \
  --file food:data/seeds/food_full.csv \
  --file food_alias:data/seeds/food_alias_full.csv

# 导入 DATA1 正式数据（DSN 亦可用环境变量 DATABASE_URL）
# 注意：food 必须先于 food_alias（food_alias.food_id 依赖 food.id）
python3 data/load_seeds.py --dsn "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach" \
  --file food:data/seeds/food_full.csv \
  --file food_alias:data/seeds/food_alias_full.csv

# 兼容旧用法：不带 --file 时加载 *_sample.* 示例数据
python3 data/load_seeds.py --dsn "postgresql://user:pass@localhost:5432/ai_coach"

# DATA4 用例复跑
python3 data/testcases/gen_calorie_cases.py

# 落库后抽查（tsvector 检索）
#   SELECT count(*) FROM food;                       -- >= 1700
#   SELECT id,name FROM food WHERE search_vec @@ plainto_tsquery('simple','鸡胸肉');
#   SELECT f.name FROM food f JOIN food_alias a ON a.food_id=f.id WHERE a.alias='鸡胸';
```

> 导入默认 `TRUNCATE` 目标表以保证幂等；`food` 使用 `TRUNCATE ... CASCADE`（会一并清空 `food_alias`），
> 清空顺序为「子表→父表」。加 `--no-truncate` 可追加导入不清空。
