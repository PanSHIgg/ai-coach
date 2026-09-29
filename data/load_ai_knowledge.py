#!/usr/bin/env python3
"""将 DATA3 RAG 知识语料导入 PostgreSQL。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach"
DEFAULT_FILE = "data/seeds/ai_knowledge_full.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入 AI RAG 知识语料到 PostgreSQL")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help=f"PostgreSQL DSN（默认：{DEFAULT_DSN}）")
    parser.add_argument("--file", default=DEFAULT_FILE, help=f"JSONL 文件（默认：{DEFAULT_FILE}）")
    parser.add_argument("--truncate", action="store_true", help="导入前清空 ai_knowledge")
    parser.add_argument("--dry-run", action="store_true", help="只解析和统计，不写库")
    return parser.parse_args()


def read_rows(path: Path) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    titles: set[str] = set()
    with path.open(encoding="utf-8-sig") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行不是有效 JSON：{exc.msg}") from exc

            values: dict[str, str] = {}
            for field in ("category", "title", "content", "source"):
                value = item.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"第 {line_number} 行字段 {field} 必须是非空字符串")
                values[field] = value.strip()

            if values["title"] in titles:
                raise ValueError(f"第 {line_number} 行标题重复：{values['title']}")
            titles.add(values["title"])
            rows.append((values["category"], values["title"], values["content"], values["source"]))
    return rows


def connect(dsn: str):
    import psycopg2

    return psycopg2.connect(dsn)


def main() -> int:
    args = parse_args()
    path = Path(args.file)
    try:
        rows = read_rows(path)
    except (OSError, ValueError) as exc:
        print(f"解析失败：{exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"[dry-run] ai_knowledge: 解析 {len(rows)} 行，跳过写库（来自 {path}）")
        return 0

    conn = connect(args.dsn)
    try:
        with conn.cursor() as cursor:
            if args.truncate:
                cursor.execute("TRUNCATE TABLE ai_knowledge RESTART IDENTITY")

            # 幂等策略：以 title 为业务唯一键；数据库中已存在的标题直接跳过。
            cursor.execute("SELECT title FROM ai_knowledge WHERE title IS NOT NULL")
            existing_titles = {row[0] for row in cursor.fetchall()}
            pending_rows = [row for row in rows if row[1] not in existing_titles]
            cursor.executemany(
                "INSERT INTO ai_knowledge (category, title, content, source) VALUES (%s, %s, %s, %s)",
                pending_rows,
            )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"导入失败，已回滚：{exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    skipped = len(rows) - len(pending_rows)
    print(f"已导入 ai_knowledge: {len(pending_rows)} 行（跳过已存在 {skipped} 行，来自 {path}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
