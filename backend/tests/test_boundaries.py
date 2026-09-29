"""Phase 1 建档与记录边界测试（对齐 07-测试方案 §9.2 功能测试）。

均走真实 DB（db_client + authed）：
- 身高 (0,200]：0/250 拒绝（422/2001），200 通过；
- 体重 (0,500]：0/501 拒绝，500 通过；
- birth_year 未来年份（3000）→ 建档成功且 age 回退默认 30（bmr 按 age=30 口径）；
- 饮食 amount_g <= 0 → 拒绝（422/2001）；
- gender/activity_level/target_type 越界 → 拒绝（422/2001）。
"""

import pytest

from app.models import Food

_BASE = {
    "gender": 1,
    "height_cm": 175,
    "birth_year": 1995,
    "current_weight": 70,
    "target_weight": 65,
    "target_type": 1,
    "activity_level": 3,
}


async def _post_profile(db_client, authed, overrides: dict):
    """以 _BASE 为底稿推送建档请求（覆盖 overrides）。"""
    return await db_client.post(
        "/api/body-profile", json={**_BASE, **overrides}, headers=authed["headers"]
    )


async def _seed_food(db_session) -> Food:
    """造一条启用食物，供饮食记录边界用例引用。"""
    food = Food(name="边界测试食物", calories_100g=100.0, status=1)
    db_session.add(food)
    await db_session.commit()
    return food


# ---------------------------------------------------------------------------
# 身高边界 (0, 200]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("height", [0, 250])
async def test_height_out_of_range_rejected(db_client, authed, height: float):
    resp = await _post_profile(db_client, authed, {"height_cm": height})
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_height_upper_boundary_200_accepted(db_client, authed):
    resp = await _post_profile(db_client, authed, {"height_cm": 200})
    assert resp.status_code == 200
    assert resp.json()["data"]["height_cm"] == 200.0


# ---------------------------------------------------------------------------
# 体重边界 (0, 500]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("weight", [0, 501])
async def test_weight_out_of_range_rejected(db_client, authed, weight: float):
    resp = await _post_profile(db_client, authed, {"current_weight": weight})
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_weight_upper_boundary_500_accepted(db_client, authed):
    resp = await _post_profile(db_client, authed, {"current_weight": 500})
    assert resp.status_code == 200
    assert resp.json()["data"]["current_weight"] == 500.0


# ---------------------------------------------------------------------------
# 出生年份异常 → 422/2001（IS-005 修复后不再接受越界值）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", [1900, 1905, 3000, 9999])
async def test_birth_year_out_of_range_rejected(db_client, authed, year: int):
    """IS-005: birth_year 超出 [当前年份-120, 当前年份-10] 范围 → 422/2001"""
    resp = await _post_profile(db_client, authed, {"birth_year": year})
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


# ---------------------------------------------------------------------------
# 饮食分量边界 amount_g <= 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("amount", [0, -5])
async def test_meal_amount_non_positive_rejected(db_client, db_session, authed, amount: float):
    food = await _seed_food(db_session)
    resp = await db_client.post(
        "/api/meal",
        headers=authed["headers"],
        json={"meal_type": 2, "food_id": food.id, "amount_g": amount, "source": 1},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


# ---------------------------------------------------------------------------
# 枚举越界：gender / activity_level / target_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"gender": 0},
        {"gender": 3},
        {"activity_level": 0},
        {"activity_level": 6},
        {"target_type": 0},
        {"target_type": 4},
    ],
)
async def test_enum_out_of_range_rejected(db_client, authed, override: dict):
    resp = await _post_profile(db_client, authed, override)
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001
