"""Phase 1（M1）端到端冒烟：登录 → 建档 → 记录 → 账户 → 步数 → 体重 → 订阅。

真实 DB（db_client + db_session）。串起 M1 核心闭环，重点对拍
    today_left = round(BMR×PAL − 摄入 + EAT − TEF, 1)  误差 0
（plan.md §7 退出标准 / 09-排期与验收交付 §11.3 M1）。

说明：闭环第一步是「登录（无 token）」→ 取真实签发的 JWT（auth_service 真实 upsert
user/user_auth/user_benefit），因此本用例用登录返回的 token 全流程身份，_BASE 用户不复用
authed 预置（避免双身份）。
"""

from app.models import Food
from app.services import calorie

GENDER = 1
HEIGHT = 175.0
WEIGHT = 70.0
BIRTH_YEAR = 1995
ACTIVITY_LEVEL = 3
TARGET_TYPE = 1


def _expected_today_left(bmr: float, pal: float, intake: float, eat: float) -> float:
    """M1 对拍口径：BMR×PAL − 摄入 + 运动 − TEF（TEF=摄入×10%），round 1 位。"""
    tef = round(intake * calorie.TEF_RATE, 1)
    return round(bmr * pal - intake + eat - tef, 1)


async def _seed_food(db_session, name: str, kcal_100g: float) -> Food:
    """造一条启用食物（真实 DB），供饮食记录引用。"""
    food = Food(
        name=name,
        calories_100g=kcal_100g,
        protein_100g=10.0,
        fat_100g=5.0,
        carb_100g=8.0,
        status=1,
    )
    db_session.add(food)
    await db_session.commit()
    return food


async def test_phase1_core_loop_smoke(db_client, db_session):
    # 1) 登录（无 token）→ 用返回 token
    login = (await db_client.post("/api/auth/login", json={"code": "smoke-phase1"})).json()
    assert login["code"] == 0
    token = login["data"]["token"]
    refresh = login["data"]["refresh_token"]
    assert token and refresh
    headers = {"Authorization": f"Bearer {token}"}
    user_id = login["data"]["user"]["id"]
    assert login["data"]["need_profile"] is True

    # token 生效：/auth/me 返回同一用户
    me = (await db_client.get("/api/auth/me", headers=headers)).json()["data"]
    assert me["id"] == user_id

    # 2) 建档 → 断言 bmr/target_calories 与引擎独立复算一致
    prof_in = {
        "gender": GENDER,
        "height_cm": HEIGHT,
        "birth_year": BIRTH_YEAR,
        "current_weight": WEIGHT,
        "target_weight": 65,
        "target_type": TARGET_TYPE,
        "activity_level": ACTIVITY_LEVEL,
    }
    prof = (await db_client.post("/api/body-profile", json=prof_in, headers=headers)).json()["data"]
    age = calorie.age_from_birth_year(BIRTH_YEAR)
    bmr = calorie.bmr_mifflin_st_jeor(gender=GENDER, weight_kg=WEIGHT, height_cm=HEIGHT, age=age)
    pal = calorie.pal_for_level(ACTIVITY_LEVEL)
    assert prof["bmr"] == bmr
    assert prof["target_calories"] == round(bmr * pal)

    # 3) 新增 2 条饮食记录（燕麦早餐 100g / 清蒸鱼午餐 150g）
    oats = await _seed_food(db_session, "燕麦", 380.0)
    fish = await _seed_food(db_session, "清蒸鱼", 120.0)
    m1 = (
        await db_client.post(
            "/api/meal",
            headers=headers,
            json={"meal_type": 1, "food_id": oats.id, "amount_g": 100, "source": 3},
        )
    ).json()["data"]
    m2 = (
        await db_client.post(
            "/api/meal",
            headers=headers,
            json={"meal_type": 2, "food_id": fish.id, "amount_g": 150, "source": 1},
        )
    ).json()["data"]
    assert m1["calories"] == 380.0  # 380 × 100/100
    assert m2["calories"] == 180.0  # 120 × 150/100
    intake = 560.0

    # 4) account/today：摄入正确、meals 汇总正确、today_left 误差 0
    today = (await db_client.get("/api/account/today", headers=headers)).json()["data"]
    assert today["intake"] == intake
    meals = {m["meal_type"]: m for m in today["meals"]}
    assert meals[1]["name"] == "早餐" and meals[1]["calories"] == 380.0
    assert meals[2]["name"] == "午餐" and meals[2]["calories"] == 180.0
    assert today["eat"] == 0.0
    assert today["calibration_used"] is False
    assert today["today_left"] == _expected_today_left(bmr, pal, intake, 0.0)

    # 5) 新增 1 条运动记录 → eat/calories_burnt 增加、today_left 同步变化
    sport = (
        await db_client.post(
            "/api/sport", headers=headers, json={"sport_name": "慢跑", "duration_min": 30}
        )
    ).json()["data"]
    eat = sport["calories"]  # MET 8.0 × 70kg × 0.5h = 280.0
    assert eat == 280.0
    after_sport = (await db_client.get("/api/account/today", headers=headers)).json()["data"]
    assert after_sport["eat"] == eat
    assert after_sport["calories_burnt"] == eat
    assert after_sport["today_left"] == _expected_today_left(bmr, pal, intake, eat)
    assert after_sport["today_left"] == round(today["today_left"] + eat, 1)

    # 6) steps/sync（12000 步）→ steps=12000、calibration_used=True
    steps = (
        await db_client.post(
            "/api/steps/sync",
            headers=headers,
            json={"date": today["date"], "steps": 12000},
        )
    ).json()["data"]
    assert steps["neat_calibrated"] > 0
    after_steps = (await db_client.get("/api/account/today", headers=headers)).json()["data"]
    assert after_steps["steps"] == 12000
    assert after_steps["calibration_used"] is True
    # NEAT 校准不进入 today_left 公式 → 数值与运动后保持一致
    assert after_steps["today_left"] == after_sport["today_left"]

    # 7) 体重：新增 → 列表 → 趋势
    w = (await db_client.post("/api/weight", headers=headers, json={"weight": 68.5})).json()["data"]
    assert w["weight"] == 68.5
    wl = (await db_client.get("/api/weight/list", headers=headers)).json()["data"]
    assert wl["page"]["total"] == 1
    wt = (await db_client.get("/api/weight/trend", headers=headers)).json()["data"]
    assert wt["items"][-1]["weight"] == 68.5
    assert wt["latest_weight"] == 68.5 and wt["start_weight"] == 68.5

    # 8) 订阅：subscribe → 列表可见 → cancel
    sub = (
        await db_client.post("/api/subscription", headers=headers, json={"template_type": 1})
    ).json()["data"]
    assert sub["status"] == 1
    subs = (await db_client.get("/api/subscription", headers=headers)).json()["data"]
    assert [it["template_type"] for it in subs["items"]] == [1]
    cancel = (
        await db_client.post("/api/subscription/cancel", headers=headers, json={"template_type": 1})
    ).json()["data"]
    assert cancel["status"] == 0
