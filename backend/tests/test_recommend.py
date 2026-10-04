"""饭点决策推荐（BE4c）：组合产出与绿/红等级语义、默认额度、LLM 降级、入参校验。

（401 鉴权与其它本波端点合并为 `test_ai_chat.py::test_ai_endpoints_require_auth`，见 §2.9）

为何单开文件：本文件覆盖 `/api/ai/recommend` 一组行为（额度 → 组合 → 分级 → 降级），
现有测试文件（test_ai_chat.py 只管对话/配额/RAG）均不涉及推荐域，无重复可合并之处。

【假设】LLM 一律 mock（patch `ai_service.llm_client_for`，测试不联网）；conftest 函数级
TRUNCATE `food` 表，故候选食物由本文件自插。
"""

from datetime import datetime

import pytest

from app.models import BodyProfile, Food, MealRecord
from app.services import recommend_service
from app.services.account import TZ

_URL = "/api/ai/recommend"


async def _seed_foods(db_session) -> set[int]:
    """插入主食/蛋白/蔬菜各一条（conftest 已清空 food 表，故候选可控）。"""
    rows = [
        Food(
            name="糙米饭",
            category="主食",
            calories_100g=112.0,
            protein_100g=2.6,
            is_standard=True,
            status=1,
        ),
        Food(
            name="鸡胸肉",
            category="肉类",
            calories_100g=133.0,
            protein_100g=24.0,
            is_standard=True,
            status=1,
        ),
        Food(
            name="西兰花",
            category="蔬菜",
            calories_100g=36.0,
            protein_100g=4.1,
            is_standard=True,
            status=1,
        ),
        Food(
            name="北豆腐",
            category="豆制品",
            calories_100g=116.0,
            protein_100g=12.2,
            is_standard=True,
            status=1,
        ),
        Food(
            name="香菇",
            category="菌藻",
            calories_100g=26.0,
            protein_100g=2.2,
            is_standard=True,
            status=1,
        ),
    ]
    db_session.add_all(rows)
    await db_session.flush()
    await db_session.commit()
    return {int(r.id) for r in rows}


async def _create_profile(db_session, user_id: int, *, weight: float = 70.0) -> None:
    db_session.add(
        BodyProfile(
            user_id=user_id,
            gender=1,
            height_cm=175.0,
            birth_year=1995,
            current_weight=weight,
            activity_level=3,
        )
    )
    await db_session.commit()


async def _add_intake(db_session, user_id: int, calories: float) -> None:
    db_session.add(
        MealRecord(
            user_id=user_id,
            record_date=datetime.now(TZ).date(),
            meal_type=1,
            food_id=None,
            food_name_snapshot="历史餐",
            amount_g=100.0,
            calories=calories,
        )
    )
    await db_session.commit()


async def test_recommend_returns_combos_within_allowance(db_client, db_session, authed):
    """额度充足：返回 2~3 个组合，主打食物取自库中，热量为正、理由非空且为绿（推荐）。"""
    food_ids = await _seed_foods(db_session)
    await _create_profile(db_session, authed["user_id"])

    resp = await db_client.post(
        _URL, headers=authed["headers"], json={"meal_type": 2, "budget": 30}
    )
    body = resp.json()
    assert (resp.status_code, body["code"]) == (200, 0)

    options = body["data"]["options"]
    assert 2 <= len(options) <= 3
    for option in options:
        assert option["calories"] > 0
        assert option["reason"].strip()
        assert option["food_id"] in food_ids
        assert option["merchant_id"] is None
        assert option["reason"].startswith("[推荐]")


async def test_recommend_flags_over_budget_as_red_or_yellow(db_client, db_session, authed):
    """剩余额度被吃穿：不再出现绿（推荐），至少一条落到黄（可接受）/红（建议少吃）。"""
    await _seed_foods(db_session)
    await _create_profile(db_session, authed["user_id"], weight=45.0)
    await _add_intake(db_session, authed["user_id"], 2000.0)

    resp = await db_client.post(_URL, headers=authed["headers"], json={"meal_type": 2})
    options = resp.json()["data"]["options"]
    assert options
    assert all(not o["reason"].startswith("[推荐]") for o in options)
    assert any("[建议少吃]" in o["reason"] or "[可接受]" in o["reason"] for o in options)


async def test_recommend_without_profile_uses_meal_default(db_client, db_session, authed):
    """未建档：不抛 3001，按餐次默认额度出组合。"""
    food_ids = await _seed_foods(db_session)

    resp = await db_client.post(_URL, headers=authed["headers"], json={"meal_type": 4})
    body = resp.json()
    assert (resp.status_code, body["code"]) == (200, 0)
    options = body["data"]["options"]
    assert options
    assert {o["food_id"] for o in options} <= food_ids


async def test_recommend_degrades_when_llm_unavailable(db_client, db_session, authed, monkeypatch):
    """LLM 不可用：静默降级为规则文案，接口仍 200（不返回 6001）。"""
    await _seed_foods(db_session)

    def _boom(_settings):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(recommend_service, "llm_client_for", _boom)

    resp = await db_client.post(_URL, headers=authed["headers"], json={"meal_type": 3})
    body = resp.json()
    assert (resp.status_code, body["code"]) == (200, 0)
    options = body["data"]["options"]
    assert options
    assert all("组合" in o["reason"] for o in options)


@pytest.mark.parametrize("meal_type", [0, 5])
async def test_recommend_rejects_invalid_meal_type(db_client, authed, meal_type):
    """meal_type 越界（1~4 之外）→ 422。"""
    resp = await db_client.post(_URL, headers=authed["headers"], json={"meal_type": meal_type})
    assert resp.status_code == 422


# ---------- items：拍照/语音识别菜名 → 按识别菜单拼组合（§5.2 菜单拍照识别+推荐） ----------


async def test_recommend_with_recognized_items_uses_matched_foods(db_client, db_session, authed):
    """带识别菜名：命中的食物（含「清蒸鲈鱼」模糊命中库「鲈鱼」）进组合，未命中的忽略。"""
    food_ids = await _seed_foods(db_session)
    fish = Food(
        name="鲈鱼",
        category="水产",
        calories_100g=105.0,
        protein_100g=18.6,
        is_standard=True,
        status=1,
    )
    db_session.add(fish)
    await db_session.flush()
    await db_session.commit()
    food_ids.add(int(fish.id))

    resp = await db_client.post(
        _URL,
        headers=authed["headers"],
        json={"meal_type": 3, "items": ["清蒸鲈鱼", "西兰花", "不存在的菜"]},
    )
    body = resp.json()
    assert (resp.status_code, body["code"]) == (200, 0)
    options = body["data"]["options"]
    assert options
    # 组合全部来自命中食物：不拿「不存在的菜」冒充，主打食物都在库里
    assert all(o["food_id"] in food_ids for o in options)
    assert any("鲈鱼" in o["name"] for o in options)
    assert all("不存在" not in o["name"] for o in options)


async def test_recommend_items_all_unmatched_falls_back_to_templates(db_client, db_session, authed):
    """识别菜名全部未命中：回退标准库组合，接口仍 200 且返回可用方案。"""
    await _seed_foods(db_session)

    resp = await db_client.post(
        _URL, headers=authed["headers"], json={"meal_type": 2, "items": ["黑暗料理", "不存在的菜"]}
    )
    body = resp.json()
    assert (resp.status_code, body["code"]) == (200, 0)
    options = body["data"]["options"]
    assert options
    assert all("组合" in o["reason"] for o in options)


async def test_recommend_rejects_too_many_items(db_client, authed):
    """识别菜名超 20 项 → 422（防超长提示词打爆 LLM）。"""
    resp = await db_client.post(
        _URL, headers=authed["headers"], json={"meal_type": 2, "items": ["菜"] * 21}
    )
    assert resp.status_code == 422
