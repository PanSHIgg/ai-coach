"""步数同步接口测试（BE2b）：/api/steps/sync 的 NEAT 校准与幂等。

覆盖：0/3000/8000/12000/20000 步的分档行为（0 步=状态法未校准、>0 走校准且
met/delta 合理并随档递增）；逐时 MET 映射；重复 sync 同一天幂等（step_record 唯一、
daily_snapshot 不重复）；F-09 微信运动解密骨架（无加密按原样、加密无凭证明确降级不伪造、
步数 0 走 PAL 估算）。
"""

from datetime import date

from sqlalchemy import func, select

from app.models import BodyProfile, DailySnapshot, StepRecord
from app.services import calorie

WEIGHT = 70.0
GENDER = 1
HEIGHT = 175.0
AGE = 31
LEVEL = 2
NON_SLEEP_HOURS = calorie.NON_SLEEP_HOURS


async def _make_profile(session, user_id: int) -> None:
    session.add(
        BodyProfile(
            user_id=user_id,
            gender=GENDER,
            height_cm=HEIGHT,
            birth_year=1995,
            age=AGE,
            current_weight=WEIGHT,
            target_type=1,
            activity_level=LEVEL,
            goal_pace=1,
        )
    )
    await session.commit()


async def _sync(db_client, headers, day: date, steps: int, hourly=None) -> dict:
    payload = {"date": day.isoformat(), "steps": steps}
    if hourly is not None:
        payload["hourly"] = hourly
    resp = await db_client.post("/api/steps/sync", json=payload, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    return body["data"]


async def test_steps_sync_without_profile_3001(db_client, authed):
    resp = await db_client.post(
        "/api/steps/sync",
        json={"date": "2026-09-28", "steps": 8000},
        headers=authed["headers"],
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 3001


async def test_steps_zero_uses_state_no_calibration(db_client, db_session, authed):
    uid = authed["user_id"]
    await _make_profile(db_session, uid)

    data = await _sync(db_client, authed["headers"], date(2026, 9, 20), 0)
    state = calorie.state_neat(weight_kg=WEIGHT, activity_level=LEVEL)
    assert data["neat_calibrated"] == state
    assert data["delta_calories"] == 0.0
    assert data["met"] == round(state / (WEIGHT * NON_SLEEP_HOURS), 2)

    snap = await db_session.scalar(
        select(DailySnapshot).where(
            DailySnapshot.user_id == uid, DailySnapshot.snapshot_date == date(2026, 9, 20)
        )
    )
    assert snap.calibration_used is False
    assert snap.steps == 0


async def test_steps_calibration_bands_increase(db_client, db_session, authed):
    uid = authed["user_id"]
    await _make_profile(db_session, uid)

    deltas: list[float] = []
    mets: list[float] = []
    for i, steps in enumerate([0, 3000, 8000, 12000, 20000]):
        day = date(2026, 9, 10 + i)
        data = await _sync(db_client, authed["headers"], day, steps)
        deltas.append(data["delta_calories"])
        mets.append(data["met"])

        snap = await db_session.scalar(
            select(DailySnapshot).where(
                DailySnapshot.user_id == uid, DailySnapshot.snapshot_date == day
            )
        )
        # 步数>0 → 已校准；0 → 未校准
        assert snap.calibration_used is (steps > 0)
        assert snap.steps == steps

    assert deltas[0] == 0.0  # 0 步不校准
    assert all(d >= 0 for d in deltas)
    # 非递减；跑步档（20000）严格高于快走档（12000）
    assert deltas == sorted(deltas)
    assert deltas[-1] > deltas[-2]
    assert mets == sorted(mets)
    assert mets[-1] > mets[-2]


async def test_steps_hourly_met_mapping(db_client, db_session, authed):
    uid = authed["user_id"]
    await _make_profile(db_session, uid)

    walk = await _sync(db_client, authed["headers"], date(2026, 9, 1), 500, hourly={"9": 500})
    run = await _sync(db_client, authed["headers"], date(2026, 9, 2), 3000, hourly={"9": 3000})
    # 逐时 MET：散步 2.5 < 跑步 8.0 → 校准 NEAT 递增
    assert run["neat_calibrated"] > walk["neat_calibrated"]

    row = await db_session.scalar(
        select(StepRecord).where(
            StepRecord.user_id == uid, StepRecord.record_date == date(2026, 9, 2)
        )
    )
    assert row.hourly_json == {"9": 3000}
    assert float(row.calibrated_met) == run["met"]


async def test_steps_sync_same_day_idempotent(db_client, db_session, authed):
    uid = authed["user_id"]
    await _make_profile(db_session, uid)
    day = date(2026, 9, 21)

    await _sync(db_client, authed["headers"], day, 8000)
    second = await _sync(db_client, authed["headers"], day, 12000)

    # 同日重复 sync：更新而非新增
    step_count = await db_session.scalar(
        select(func.count())
        .select_from(StepRecord)
        .where(StepRecord.user_id == uid, StepRecord.record_date == day)
    )
    snap_count = await db_session.scalar(
        select(func.count())
        .select_from(DailySnapshot)
        .where(DailySnapshot.user_id == uid, DailySnapshot.snapshot_date == day)
    )
    assert step_count == 1
    assert snap_count == 1

    row = await db_session.scalar(
        select(StepRecord).where(StepRecord.user_id == uid, StepRecord.record_date == day)
    )
    assert row.steps == 12000
    assert float(row.calibrated_met) == second["met"]


# ---------------------------------------------------------------------------
# F-09：真实步数接入（微信运动解密骨架 / 明确降级）
# ---------------------------------------------------------------------------


async def test_steps_sync_without_encrypted_as_is(db_client, db_session, authed):
    """无加密数据：按传入 steps 原样同步，走既有校准路径。"""
    uid = authed["user_id"]
    await _make_profile(db_session, uid)
    day = date(2026, 9, 3)

    data = await _sync(db_client, authed["headers"], day, 6000)

    row = await db_session.scalar(
        select(StepRecord).where(StepRecord.user_id == uid, StepRecord.record_date == day)
    )
    snap = await db_session.scalar(
        select(DailySnapshot).where(
            DailySnapshot.user_id == uid, DailySnapshot.snapshot_date == day
        )
    )
    assert row.steps == 6000
    assert snap.steps == 6000
    assert snap.calibration_used is True
    assert data["delta_calories"] >= 0


async def test_steps_encrypted_without_credentials_degrades(db_client, db_session, authed):
    """加密字段存在但无微信凭证：明确降级按传入 steps（0）计，不伪造、不报错。"""
    uid = authed["user_id"]
    await _make_profile(db_session, uid)
    day = date(2026, 9, 4)

    resp = await db_client.post(
        "/api/steps/sync",
        json={
            "date": day.isoformat(),
            "steps": 0,
            "encrypted_data": "ZmFrZS1lbmNyeXB0ZWQ=",
            "iv": "ZmFrZS1pdg==",
        },
        headers=authed["headers"],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    # 无凭证 → 不伪造，delta 为 0（等价 0 步的状态法）
    assert body["data"]["delta_calories"] == 0.0

    row = await db_session.scalar(
        select(StepRecord).where(StepRecord.user_id == uid, StepRecord.record_date == day)
    )
    snap = await db_session.scalar(
        select(DailySnapshot).where(
            DailySnapshot.user_id == uid, DailySnapshot.snapshot_date == day
        )
    )
    assert row.steps == 0  # 未伪造成任何步数常量
    assert snap.steps == 0
    assert snap.calibration_used is False


async def test_steps_zero_uses_pal_estimate(db_client, db_session, authed):
    """步数 0（未取到/降级）→ 走 PAL（状态法）估算 NEAT，不报错。"""
    uid = authed["user_id"]
    await _make_profile(db_session, uid)
    day = date(2026, 9, 7)

    data = await _sync(db_client, authed["headers"], day, 0)

    state = calorie.state_neat(weight_kg=WEIGHT, activity_level=LEVEL)
    assert data["neat_calibrated"] == state
    assert data["delta_calories"] == 0.0

    snap = await db_session.scalar(
        select(DailySnapshot).where(
            DailySnapshot.user_id == uid, DailySnapshot.snapshot_date == day
        )
    )
    assert snap.steps == 0
    assert snap.calibration_used is False
