"""热量引擎基础测试（基础层，锁定 M1 对拍口径）。

M1 退出标准（01 §2.5 / plan.md §7）：环形图数值 = BMR×PAL − 已摄入 + 运动 − TEF，误差 0。
本文件由基础层维护；QA 轨（DATA4 50 行对拍）与 BE2 轨的用例文件另建，避免重复。
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import account, calorie
from app.services.calorie import CalorieInputs

TZ = timezone(timedelta(hours=8))


def _today_tz() -> date:
    """业务当日（UTC+8），与 account 服务的日界口径一致。"""
    return datetime.now(TZ).date()


def test_bmr_mifflin_male_female():
    # 男：10w + 6.25h − 5age + 5
    assert calorie.bmr_mifflin_st_jeor(gender=1, weight_kg=70, height_cm=175, age=30) == round(
        10 * 70 + 6.25 * 175 - 5 * 30 + 5, 1
    )
    # 女：−161
    assert calorie.bmr_mifflin_st_jeor(gender=2, weight_kg=55, height_cm=162, age=28) == round(
        10 * 55 + 6.25 * 162 - 5 * 28 - 161, 1
    )


def test_pal_defaults():
    assert calorie.pal_for_level(2) == 1.4
    assert calorie.pal_for_level(None) == 1.4  # 未填默认 2
    assert calorie.pal_for_level(5) == 2.0


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("gender", [1, 2])
def test_account_formula_exact(level: int, gender: int):
    """环形图「还能吃」= BMR×PAL − 摄入 + 运动 − TEF，误差 0。"""
    inp = CalorieInputs(
        gender=gender,
        weight_kg=68.5,
        height_cm=172,
        age=32,
        activity_level=level,
        intake=1418,
        eat=320,
        steps=0,
    )
    r = calorie.compute_account(inp)
    budget = round(r.bmr * r.pal, 1)
    expected_left = round(budget - inp.intake + inp.eat - r.tef, 1)
    assert r.today_left == expected_left
    # TEE = BMR×PAL + EAT + TEF
    assert r.tee == round(budget + inp.eat + r.tef, 1)
    # 缺口 = 摄入 − TEE
    assert r.deficit == round(inp.intake - r.tee, 1)
    assert r.tef == round(inp.intake * 0.10, 1)


def test_steps_zero_uses_pal_estimate():
    r = calorie.compute_account(
        CalorieInputs(
            gender=1,
            weight_kg=70,
            height_cm=175,
            age=30,
            activity_level=2,
            intake=0,
            eat=0,
            steps=0,
        )
    )
    assert r.calibration_used is False
    assert r.neat == calorie.state_neat(weight_kg=70, activity_level=2)


def test_steps_positive_uses_calibration():
    r = calorie.compute_account(
        CalorieInputs(
            gender=1,
            weight_kg=70,
            height_cm=175,
            age=30,
            activity_level=2,
            intake=0,
            eat=0,
            steps=12000,
        )
    )
    assert r.calibration_used is True
    state = calorie.state_neat(weight_kg=70, activity_level=2)
    steps_val = calorie.steps_neat(weight_kg=70, steps=12000, hourly=None)
    assert r.neat == round(0.6 * steps_val + 0.4 * state, 1)


def test_cadence_met_mapping():
    # 散步/快走/跑步三档（04 §6.3.3）
    assert calorie.steps_neat(weight_kg=70, steps=0, hourly={"9": 500}) == round(2.5 * 70 * 1, 1)
    assert calorie.steps_neat(weight_kg=70, steps=0, hourly={"9": 1500}) == round(4.3 * 70 * 1, 1)
    assert calorie.steps_neat(weight_kg=70, steps=0, hourly={"9": 3000}) == round(8.0 * 70 * 1, 1)


@pytest.mark.asyncio
async def test_account_service_db_roundtrip(db_session, authed):
    """建档 + 两餐 → account/today 摄入/明细/快照幂等。"""
    from app.models import BodyProfile, MealRecord

    uid = authed["user_id"]
    db_session.add(
        BodyProfile(
            user_id=uid,
            gender=1,
            height_cm=175,
            birth_year=1995,
            age=31,
            current_weight=70,
            target_type=1,
            activity_level=2,
            goal_pace=1,
        )
    )
    db_session.add_all(
        [
            MealRecord(
                user_id=uid,
                record_date=_today_tz(),
                meal_type=1,
                food_id=None,
                food_name_snapshot="燕麦",
                amount_g=100,
                calories=380,
                source=3,
            ),
            MealRecord(
                user_id=uid,
                record_date=_today_tz(),
                meal_type=2,
                food_id=None,
                food_name_snapshot="清蒸鱼",
                amount_g=150,
                calories=620,
                source=1,
            ),
        ]
    )
    await db_session.commit()

    today = await account.get_today(db_session, uid)
    assert today.intake == 1000.0
    assert {m.meal_type for m in today.meals} == {1, 2}
    # 幂等：重复调用快照仍唯一
    today2 = await account.get_today(db_session, uid)
    assert today2.intake == today.intake

    from sqlalchemy import func, select

    from app.models import DailySnapshot

    cnt = await db_session.scalar(
        select(func.count()).select_from(DailySnapshot).where(DailySnapshot.user_id == uid)
    )
    assert cnt == 1
