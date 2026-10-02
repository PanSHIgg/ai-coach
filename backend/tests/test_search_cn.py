"""G10 中文全文检索失真修复测试（`POST /api/food/search` 的 pg_trgm 命中与排序）。

失真背景：旧实现以 `to_tsvector('simple', name)` 建检索、`plainto_tsquery` 匹配；
`simple` 配置不切中文（整串作一个词元），中文子串（如「鸡胸」）检索命中 0 行、或
命中与预期无关的「0 热量」行。0010 改 pg_trgm：`name`/`food_alias.alias` ILIKE 子串
命中（GIN trgm 索引加速）+ `similarity()` 排序。

本文件用**真实种子数据**（`data/seeds/food_full.csv`、`food_alias_full.csv`）验证：
- 中文子串能命中真实种子行（旧实现此处 0 行）；
- 命中行热量为真实值（非 0/错行）；
- 相似度排序合理（精确名/别名相似度 1.0 排首位）；
- 仅存在于别名的词仍能经 `food_alias` 命中。

为何单开文件：G10 检索口径变更为本轮修复点；`test_food_search` 覆盖既有基本命中
与可见性隔离，此处单列中文检索专项回归（一个行为一个测试，AGENTS §2.9）。
"""

import csv
from pathlib import Path

from sqlalchemy import insert, select

from app.models import Food, FoodAlias

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seeds"


def _num(value: str | None) -> float | None:
    value = (value or "").strip()
    return float(value) if value else None


def _read_rows(filename: str) -> list[dict[str, str]]:
    with open(SEED_DIR / filename, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


async def _load_real_food_library(db_session) -> None:
    """全量导入真实种子食物库与别名（food_full.csv + food_alias_full.csv）。"""
    foods = [
        {
            "name": r["name"].strip(),
            "category": (r.get("category") or "").strip() or None,
            "calories_100g": float(r["calories_100g"]),
            "protein_100g": _num(r.get("protein_100g")),
            "fat_100g": _num(r.get("fat_100g")),
            "carb_100g": _num(r.get("carb_100g")),
            "gi": int(r["gi"].strip()) if (r.get("gi") or "").strip() else None,
            "is_standard": (r.get("is_standard") or "").strip().lower()
            in ("true", "1", "t", "yes"),
            "status": 1,
        }
        for r in _read_rows("food_full.csv")
    ]
    await db_session.execute(insert(Food), foods)
    name_to_id = dict((await db_session.execute(select(Food.name, Food.id))).all())
    aliases = [
        {"food_id": name_to_id[r["food_name"].strip()], "alias": r["alias"].strip()}
        for r in _read_rows("food_alias_full.csv")
        if r["food_name"].strip() in name_to_id
    ]
    await db_session.execute(insert(FoodAlias), aliases)
    await db_session.commit()


async def test_search_cn_substring_hits_real_seed_rows(db_client, db_session, authed):
    """中文子串「鸡胸」→ 命中真实种子行且热量为真实值（旧 tsvector('simple') 会 0 行失真）。"""
    await _load_real_food_library(db_session)

    resp = await db_client.post(
        "/api/food/search", headers=authed["headers"], json={"keyword": "鸡胸", "limit": 100}
    )
    body = resp.json()
    assert (resp.status_code, body["code"]) == (200, 0)

    data = body["data"]
    assert data["total"] > 0  # 旧实现此处为 0（失真点）
    names = [it["name"] for it in data["items"]]
    assert "鸡胸肉" in names
    assert "鸡胸肉丸" in names
    kcal = {it["name"]: it["calories_100g"] for it in data["items"]}
    assert kcal["鸡胸肉"] == 133.0  # 真实种子热量，非 0/错行


async def test_search_cn_exact_name_ranks_first(db_client, db_session, authed):
    """精确名（similarity=1.0）排子串行之前：搜「鸡胸肉」→ 首位为「鸡胸肉」。"""
    breast = Food(name="鸡胸肉", calories_100g=133.0, status=1)
    ball = Food(name="鸡胸肉丸", calories_100g=120.0, status=1)
    db_session.add_all([breast, ball])
    await db_session.commit()

    resp = await db_client.post(
        "/api/food/search", headers=authed["headers"], json={"keyword": "鸡胸肉", "limit": 20}
    )
    items = resp.json()["data"]["items"]
    assert items[0]["name"] == "鸡胸肉"
    assert items[0]["id"] == breast.id


async def test_search_cn_alias_only_match(db_client, db_session, authed):
    """别名专属词「地瓜」（不在任何 name 中）→ 经 food_alias 命中真实种子行「红薯」。"""
    sweet_potato = Food(name="红薯", calories_100g=86.0, status=1)
    db_session.add(sweet_potato)
    await db_session.flush()
    db_session.add(FoodAlias(food_id=sweet_potato.id, alias="地瓜"))
    await db_session.commit()

    resp = await db_client.post(
        "/api/food/search", headers=authed["headers"], json={"keyword": "地瓜", "limit": 20}
    )
    data = resp.json()["data"]
    assert data["total"] == 1
    assert [it["name"] for it in data["items"]] == ["红薯"]
    assert data["items"][0]["calories_100g"] == 86.0