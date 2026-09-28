#!/usr/bin/env python3
"""load_seeds.py — 种子数据导入脚本（P0-c 骨架）。

对齐 plan.md DATA 轨道交付节点：
- DATA1 食物库 1700+ 条 + food_alias：W3 前交付
- DATA3 RAG 知识库语料：W5 前交付
- DATA2 标准 SKU 目录：W7 前交付

正式数据未就绪时，默认只加载本目录 *_sample.* 示例数据并打印提示；
正式文件用 --file 显式指定（格式：表名:路径）。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent / "seeds"

# 表名 -> 默认示例文件
SAMPLE_FILES = {
    "food": "food.sample.csv",
    "sku_catalog": "standard_sku.sample.csv",
    "ai_knowledge": "rag_knowledge.sample.jsonl",
}

# DATA1/DATA2/DATA3 正式数据交付后改为 True（或始终用 --file 指定）
REAL_DATA_READY = False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="导入种子数据到 PostgreSQL")
    p.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""),
                   help="PostgreSQL DSN，默认读环境变量 DATABASE_URL")
    p.add_argument("--dry-run", action="store_true", help="只解析文件不写库")
    p.add_argument("--no-truncate", action="store_true",
                   help="导入前不清空目标表（默认 TRUNCATE 以保证重复导入幂等）")
    p.add_argument("--file", action="append", default=[],
                   help="指定导入文件，格式 表名:路径（可多次），如 food:data/seeds/food_full.csv")
    return p.parse_args()


def _num(v: str | None):
    v = (v or "").strip()
    return float(v) if v else None


def _connect(dsn: str):
    import psycopg2  # 延迟导入：dry-run / 数据未就绪时不强依赖

    return psycopg2.connect(dsn)


def load_food(conn, path: Path, dry_run: bool) -> int:
    """导入食物库。正式数据量大时建议切换 COPY FROM STDIN 提升吞吐。"""
    with open(path, newline="", encoding="utf-8-sig") as f:  # utf-8-sig 兼容带 BOM 的 Excel 导出 CSV
        rows = list(csv.DictReader(f))
    data = [
        (
            r["name"].strip(),
            (r.get("category") or "").strip() or None,
            float(r["calories_100g"]),
            _num(r.get("protein_100g")),
            _num(r.get("fat_100g")),
            _num(r.get("carb_100g")),
            _num(r.get("gi")),
            (r.get("is_standard") or "").strip().lower() in ("true", "1", "t", "yes"),
        )
        for r in rows
    ]
    if dry_run:
        print(f"[dry-run] food: 解析 {len(data)} 行，跳过写库")
        return len(data)
    sql = ("INSERT INTO food (name, category, calories_100g, protein_100g, "
           "fat_100g, carb_100g, gi, is_standard) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)")
    with conn.cursor() as cur:
        cur.executemany(sql, data)
    return len(data)


def load_sku(conn, path: Path, dry_run: bool) -> int:
    """导入标准 SKU 目录（含价格区间 min/max）。"""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    data = [
        (
            r["code"].strip(), r["name"].strip(), (r.get("category") or "").strip() or None,
            int(r["calories_low"]) if (r.get("calories_low") or "").strip() else None,
            int(r["calories_high"]) if (r.get("calories_high") or "").strip() else None,
            float(r["base_price"]), float(r["min_price"]), float(r["max_price"]),
            (r.get("unit") or "").strip() or None,
        )
        for r in rows
    ]
    if dry_run:
        print(f"[dry-run] sku_catalog: 解析 {len(data)} 行，跳过写库")
        return len(data)
    sql = ("INSERT INTO sku_catalog (code, name, category, calories_low, calories_high, "
           "base_price, min_price, max_price, unit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    with conn.cursor() as cur:
        cur.executemany(sql, data)
    return len(data)


def load_rag(conn, path: Path, dry_run: bool) -> int:
    """导入 RAG 知识库语料（JSONL，每行一个对象）。"""
    data = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            data.append((o.get("category"), o.get("title"), o["content"], o.get("source")))
    if dry_run:
        print(f"[dry-run] ai_knowledge: 解析 {len(data)} 行，跳过写库")
        return len(data)
    sql = ("INSERT INTO ai_knowledge (category, title, content, source) "
           "VALUES (%s,%s,%s,%s)")
    with conn.cursor() as cur:
        cur.executemany(sql, data)
    return len(data)


LOADERS = {"food": load_food, "sku_catalog": load_sku, "ai_knowledge": load_rag}


def main() -> int:
    args = parse_args()

    targets: dict[str, Path] = {}
    for item in args.file:
        table, _, p = item.partition(":")
        if table not in LOADERS or not p:
            print(f"错误：--file 格式应为 表名:路径，可选表名 {list(LOADERS)}，收到：{item}", file=sys.stderr)
            return 2
        targets[table] = Path(p)

    if not targets:
        if not REAL_DATA_READY:
            print("提示：正式种子数据尚未交付（DATA1 食物库 W3 / DATA3 RAG W5 / DATA2 SKU W7）。")
            print("本次仅加载示例数据 *_sample.*；正式文件就绪后用 --file 指定导入。")
        targets = {t: SEED_DIR / f for t, f in SAMPLE_FILES.items()}

    if args.dry_run:
        for table, path in targets.items():
            LOADERS[table](None, path, dry_run=True)
        return 0

    if not args.dsn:
        print("错误：未提供 --dsn，且环境变量 DATABASE_URL 为空", file=sys.stderr)
        return 2

    conn = _connect(args.dsn)
    try:
        for table, path in targets.items():
            if not args.no_truncate:
                # 表名来自 LOADERS 白名单，无注入风险；TRUNCATE 保证重复导入幂等
                with conn.cursor() as cur:
                    cur.execute(f"TRUNCATE TABLE {table}")
            n = LOADERS[table](conn, path, dry_run=False)
            print(f"已导入 {table}: {n} 行（来自 {path}）")
        conn.commit()
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        print(f"导入失败，已回滚：{e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
