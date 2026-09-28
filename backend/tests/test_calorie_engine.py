"""热量引擎基础测试（基础层，锁定 M1 对拍口径）。

M1 退出标准（01 §2.5 / plan.md §7）：环形图数值 = BMR×PAL − 已摄入 + 运动 − TEF，误差 0。
本文件由基础层维护；QA 轨（DATA4 50 行对拍）与 BE2 轨的用例文件另建，避免重复。
"""

import pytest

from app.services import calorie
from app.services.calorie import CalorieInputs


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
