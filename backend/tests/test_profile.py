"""BE1 身体档案 DB 集成测试：POST upsert + BMR/目标热量计算、GET、校园边界 422。"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BodyProfile
from app.services import calorie

_BASE = {
    "gender": 1,
    "height_cm": 175,
    "birth_year": 1995,
    "current_weight": 70,
    "target_weight": 65,
    "target_type": 1,
    "activity_level": 3,
}


def _expected_bmr(weight: float, activity_level: int, gender: int = 1) -> tuple[float, int]:
    age = calorie.age_from_birth_year(_BASE["birth_year"])
    bmr = calorie.bmr_mifflin_st_jeor(
        gender=gender, weight_kg=weight, height_cm=_BASE["height_cm"], age=age
    )
    return bmr, round(bmr * calorie.pal_for_level(activity_level))


async def _count(session: AsyncSession, user_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(BodyProfile).where(BodyProfile.user_id == user_id)
        )
    )


async def test_get_body_profile_none_before_create(db_client: AsyncClient, authed: dict):
    resp = await db_client.get("/api/body-profile", headers=authed["headers"])
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    assert resp.json()["data"] is None


async def test_body_profile_create_calculates_bmr_and_target(
    db_session: AsyncSession, db_client: AsyncClient, authed: dict
):
    resp = await db_client.post("/api/body-profile", json=_BASE, headers=authed["headers"])
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] > 0
    bmr, target = _expected_bmr(70, 3)
    assert data["bmr"] == bmr
    assert data["target_calories"] == target
    assert data["goal_pace"] == 1  # 未填默认 1

    # GET 回读
    got = await db_client.get("/api/body-profile", headers=authed["headers"])
    assert got.json()["data"]["id"] == data["id"]
    assert await _count(db_session, authed["user_id"]) == 1


async def test_body_profile_upsert_same_row(
    db_session: AsyncSession, db_client: AsyncClient, authed: dict
):
    first = (
        await db_client.post("/api/body-profile", json=_BASE, headers=authed["headers"])
    ).json()["data"]

    payload2 = {**_BASE, "current_weight": 68, "activity_level": 2}
    second = (
        await db_client.post("/api/body-profile", json=payload2, headers=authed["headers"])
    ).json()["data"]

    assert second["id"] == first["id"]  # 同 user 复用同一行
    bmr, target = _expected_bmr(68, 2)
    assert second["bmr"] == bmr
    assert second["target_calories"] == target
    assert await _count(db_session, authed["user_id"]) == 1


async def test_body_profile_future_birth_year_falls_back_age_30(
    db_session: AsyncSession, db_client: AsyncClient, authed: dict
):
    payload = {**_BASE, "birth_year": 3000}  # 未来年份 → 引擎回退默认 30
    data = (
        await db_client.post("/api/body-profile", json=payload, headers=authed["headers"])
    ).json()["data"]
    bmr = calorie.bmr_mifflin_st_jeor(gender=1, weight_kg=70, height_cm=175, age=30)
    assert data["bmr"] == bmr
    assert data["target_calories"] == round(bmr * calorie.pal_for_level(3))


@pytest.mark.parametrize(
    "override",
    [
        {"height_cm": 0},  # 身高下界外
        {"height_cm": 250},  # 身高上界外
        {"current_weight": 0},  # 体重下界外
        {"current_weight": 600},  # 体重上界外
    ],
)
async def test_body_profile_out_of_range_422(db_client: AsyncClient, authed: dict, override: dict):
    resp = await db_client.post(
        "/api/body-profile", json={**_BASE, **override}, headers=authed["headers"]
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_body_profile_boundary_values_accepted(db_client: AsyncClient, authed: dict):
    """边界值 身高 200 / 体重 500 应通过。"""
    payload = {**_BASE, "height_cm": 200, "current_weight": 500}
    resp = await db_client.post("/api/body-profile", json=payload, headers=authed["headers"])
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["height_cm"] == 200.0
    assert data["current_weight"] == 500.0
