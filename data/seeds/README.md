# 种子数据说明（P0-c）

本目录存放种子/示例数据。**当前全部为 `*.sample.*` 示例数据**，仅用于联调冒烟，不是正式数据。

## 文件

| 文件 | 目标表 | 说明 |
| --- | --- | --- |
| `food.sample.csv` | `food` | 食物库示例（表头 + 5 行；gi 留空 = NULL） |
| `standard_sku.sample.csv` | `sku_catalog` | 标准 SKU 目录示例（含价格区间 min/max，商家定价越界后端 400） |
| `rag_knowledge.sample.jsonl` | `ai_knowledge` | RAG 知识库示例（每行一个 JSON 对象） |

## 正式数据交付节点（对齐 plan.md DATA 轨道）

| 编号 | 数据 | 交付节点 | 说明 |
| --- | --- | --- | --- |
| DATA1 | 食物库 1700+ 条 + food_alias | **W3 前** | BE3 food/search、BE4a 识别匹配依赖 |
| DATA3 | RAG 知识库语料 + 预置 FAQ | **W5 前** | BE4b AI 对话依赖 |
| DATA2 | 标准 SKU 目录（含价格区间） | **W7 前** | BE5 商家/目录依赖 |
| DATA4 | 热量测试用例 50 行 / 识别测试图 30 张 | W4 | QA 对拍用 |

正式文件就绪后由 DATA 轨道放入本目录（建议命名 `food_full.csv` / `standard_sku_full.csv` / `rag_knowledge_full.jsonl`），并用 `--file` 指定导入。

## 导入方式

```bash
# 先跑建表 SQL（或 alembic upgrade head）
psql "$DATABASE_URL" -f code/data/sql/001_schema.sql

# 示例数据 dry-run（不写库）
python3 code/data/load_seeds.py --dry-run

# 导入示例数据（DSN 默认读环境变量 DATABASE_URL）
python3 code/data/load_seeds.py --dsn "postgresql://user:pass@localhost:5432/ai_coach"

# 正式数据就绪后
python3 code/data/load_seeds.py --file food:code/data/seeds/food_full.csv
```
