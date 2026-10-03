"""步数同步接口测试（BE2b）：/api/steps/sync 的 NEAT 校准与幂等。

覆盖：0/3000/8000/12000/20000 步的分档行为（0 步=状态法未校准、>0 走校准且
met/delta 合理并随档递增）；逐时 MET 映射；重复 sync 同一天幂等（step_record 唯一、
daily_snapshot 不重复）；F-09 微信运动真链路（按用户 session_key 解密、watermark.appid
校验、目标日期缺记录**不得借用其它日期**、steps_source 三态与"不伪造步数"）；
F-09b 同步回填 31 天历史（仅解密成功才回填、不补历史快照、冲突只更新）与
GET /steps/trend 读曲线（区间/升序/不补零/days 越界/按 user_id 行级隔离）。
"""

import base64
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import BodyProfile, DailySnapshot, StepRecord, User
from app.services import auth_service, calorie
from app.services import steps as steps_service
from app.services.steps import extract_day_steps
from app.services.wechat_pay import _encrypt_block
from tests.conftest import make_settings

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


async def _sync(db_client, headers, day: date, steps: int, hourly=None, encrypted=None) -> dict:
    payload = {"date": day.isoformat(), "steps": steps}
    if hourly is not None:
        payload["hourly"] = hourly
    if encrypted is not None:
        payload["encrypted_data"], payload["iv"] = encrypted
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


# F-09：真实步数接入（微信运动解密骨架 / 明确降级）


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
    # 未带加密数据 → 来源如实标为"客户端传入值"
    assert data["steps"] == 6000
    assert data["steps_source"] == steps_service.SOURCE_CLIENT


async def test_steps_encrypted_without_session_key_degrades(
    db_client, db_session, authed, monkeypatch: pytest.MonkeyPatch
):
    """带加密字段但该用户没有 session_key（未登录/Redis 无值）：明确降级，不伪造步数。

    旧实现以静态 env `WECHAT_STEPS_SESSION_KEY` + `WECHAT_SECRET` 为门槛（生产恒空 →
    永远解不开）；现在门槛是"该用户本次登录的 session_key"。此处钉死 settings 排除
    本机 .env 干扰，并断言降级仍写 0 步、来源为 3（未取到，按 PAL 估算）。
    """
    uid = authed["user_id"]
    await _make_profile(db_session, uid)
    day = date(2026, 9, 4)
    monkeypatch.setattr(steps_service, "get_settings", lambda: _decrypt_settings())

    data = await _sync(
        db_client, authed["headers"], day, 0, encrypted=("ZmFrZS1lbmNyeXB0ZWQ=", "ZmFrZS1pdg==")
    )
    # 无 key → 不伪造，delta 为 0（等价 0 步的状态法）
    assert data["delta_calories"] == 0.0
    assert data["steps"] == 0
    assert data["steps_source"] == steps_service.SOURCE_NONE

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
    assert data["steps_source"] == steps_service.SOURCE_NONE

    snap = await db_session.scalar(
        select(DailySnapshot).where(
            DailySnapshot.user_id == uid, DailySnapshot.snapshot_date == day
        )
    )
    assert snap.steps == 0
    assert snap.calibration_used is False


# F-09：微信运动真链路（官方口径）
#   AES-128-CBC + PKCS#7，密钥 = 同一次 code2Session 的 session_key（按用户存 Redis）；
#   解密结果须过 watermark.appid 校验；stepInfoList 是固定 31 条**按天**记录。

WATERMARK_APPID = "wxtestappid0000000000"  # watermark 校验的比对基准（测试用 AppID）
SESSION_KEY_B64 = base64.b64encode(b"0123456789abcdef").decode()  # 16 字节 session_key
IV_B64 = base64.b64encode(b"fedcba9876543210").decode()
_STEPS_TZ = timezone(timedelta(hours=8))  # 微信运动时间戳按北京时间（与 services 一致）
TARGET_DAY = date(2026, 10, 3)
OTHER_DAY = TARGET_DAY - timedelta(days=30)  # 31 天窗口的最早一天


class _StubRedis:
    """Redis 替身：只提供 session_key 存取用到的 get/set。

    `tests/conftest.py` 把 REDIS_URL 钉成不可达端口（用例走进程内兜底）且属禁碰文件，
    故这里以注入方式塞 key，不动测试基座。
    """

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value


def _stub_redis(monkeypatch: pytest.MonkeyPatch, values: dict[str, str] | None = None) -> None:
    """把替身装进 auth_service（session_key 的读写都经它的 get_redis）。"""

    async def _get_redis():
        return _StubRedis(values)

    monkeypatch.setattr(auth_service, "get_redis", _get_redis)


def _user_key(user_id: int, key: str = SESSION_KEY_B64) -> dict[str, str]:
    """构造 {该用户的 session_key 键: 值}，键名取自生产同一函数，避免测试自说自话。"""
    return {auth_service.session_key_redis_key(user_id): key}


def _ts(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=_STEPS_TZ).timestamp())


def _werun_payload(days: list[tuple[date, int]], appid: str = WATERMARK_APPID) -> dict:
    """构造微信运动解密明文的形态：stepInfoList（按天）+ watermark。"""
    return {
        "stepInfoList": [{"timestamp": _ts(d), "step": s} for d, s in days],
        "watermark": {"appid": appid, "timestamp": _ts(days[-1][0])},
    }


def _encrypt(
    payload: dict, session_key: str = SESSION_KEY_B64, iv: str = IV_B64
) -> tuple[str, str]:
    """按微信口径（AES-128-CBC + PKCS#7，base64）造 encryptedData。

    密文用 `wechat_pay._encrypt_block`（**加密**核）生成，被测的是 `steps.py` 的**解密**侧；
    加密核本身已由 test_pay_wechat 的 NIST 向量钉住，此处不重复验它。
    """
    key, prev = base64.b64decode(session_key), base64.b64decode(iv)
    plain = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    pad = 16 - len(plain) % 16
    plain += bytes([pad]) * pad
    out = bytearray()
    for i in range(0, len(plain), 16):
        block = bytes(a ^ b for a, b in zip(plain[i : i + 16], prev, strict=True))
        prev = _encrypt_block(block, key)
        out.extend(prev)
    return base64.b64encode(bytes(out)).decode(), iv


def _decrypt_settings():
    """解密用例的 settings：只配 WECHAT_APPID（watermark 比对基准），**故意不配 WECHAT_SECRET**
    （解密与支付凭证无关），静态 session_key 钉死为空（排除本机 .env 干扰）。
    """
    return make_settings(
        WECHAT_APPID=WATERMARK_APPID,
        WECHAT_SECRET="",
        WECHAT_STEPS_SESSION_KEY="",
    )


def test_extract_day_steps_target_day_only_no_borrowing():
    """31 条按天记录：命中当天才取值，缺当天返回 None（旧实现返回 items[-1] → 借数污染）。"""
    days = [(TARGET_DAY - timedelta(days=30 - i), 1000 + i * 100) for i in range(31)]
    payload = _werun_payload(days)
    assert extract_day_steps(payload, TARGET_DAY) == 4000  # index 30 = 今天
    assert extract_day_steps(payload, OTHER_DAY) == 1000  # index 0 = 30 天前
    # 窗口里没有的日期：绝不拿"最新一条"顶替（那会把别处的步数当成这天）
    assert extract_day_steps(payload, TARGET_DAY + timedelta(days=1)) is None


async def test_resolve_steps_missing_day_degrades_instead_of_borrowing(
    monkeypatch: pytest.MonkeyPatch,
):
    """解密成功但 stepInfoList 没有目标日期 → 不猜不借，降级用传入值（steps_source=2）。

    回归防线：被借的那条记录（30 天前 30000 步）绝不能当成当天步数写进热量账户。
    """
    _stub_redis(monkeypatch, _user_key(7))
    encrypted, iv = _encrypt(_werun_payload([(OTHER_DAY, 30000)]))

    resolved, source, _ = await steps_service._resolve_steps(
        7, 1000, encrypted, iv, TARGET_DAY, _decrypt_settings()
    )

    assert (resolved, source) == (1000, steps_service.SOURCE_CLIENT)
    assert resolved != 30000


async def test_resolve_steps_decrypts_with_user_session_key(monkeypatch: pytest.MonkeyPatch):
    """Redis 有该用户 session_key（且无 WECHAT_SECRET）→ 真解密取当天步数，steps_source=1。"""
    _stub_redis(monkeypatch, _user_key(7))
    encrypted, iv = _encrypt(_werun_payload([(OTHER_DAY, 1000), (TARGET_DAY, 9000)]))

    resolved, source, _ = await steps_service._resolve_steps(
        7, 0, encrypted, iv, TARGET_DAY, _decrypt_settings()
    )

    assert (resolved, source) == (9000, steps_service.SOURCE_WERUN)


async def test_resolve_steps_rejects_foreign_watermark_appid(monkeypatch: pytest.MonkeyPatch):
    """watermark.appid 与本小程序 AppID 不符 → 数据不可信，不得采用该步数（防串号）。"""
    _stub_redis(monkeypatch, _user_key(7))
    encrypted, iv = _encrypt(_werun_payload([(TARGET_DAY, 50000)], appid="wxOTHERAPPID0000000"))

    resolved, source, _ = await steps_service._resolve_steps(
        7, 1000, encrypted, iv, TARGET_DAY, _decrypt_settings()
    )

    assert (resolved, source) == (1000, steps_service.SOURCE_CLIENT)
    assert resolved != 50000


@pytest.mark.parametrize(
    "stored_uid, client_steps, expected",
    [
        (None, 6000, (6000, 2)),  # 无 key，客户端传了值 → 采用传入值
        (None, 0, (0, 3)),  # 既无 key 也无传入值 → 完全未取到（走 PAL 估算）
        (999, 6000, (6000, 2)),  # key 属于别人 → 不得挪用他人 session_key
    ],
    ids=["无key有传入值", "无key也无传入值", "key属于他人"],
)
async def test_resolve_steps_without_own_key_marks_source(
    monkeypatch: pytest.MonkeyPatch, stored_uid, client_steps, expected
):
    """无本人 session_key 时按三态如实标注来源，且不伪造步数（steps 恒等于传入值）。"""
    values = None if stored_uid is None else _user_key(stored_uid)
    _stub_redis(monkeypatch, values)
    # 数据本身是"今天 9000 步"，但拿不到本人 key 就只能降级
    encrypted, iv = _encrypt(_werun_payload([(TARGET_DAY, 9000)]))

    resolved, source, _ = await steps_service._resolve_steps(
        7, client_steps, encrypted, iv, TARGET_DAY, _decrypt_settings()
    )

    assert (resolved, source) == expected


async def test_steps_sync_http_returns_source_1(
    db_client, db_session, authed, monkeypatch: pytest.MonkeyPatch
):
    """端到端：登录持久化的 session_key 生效 → 解密步数入库、steps_source=1 回传前端。

    与 `_resolve_steps` 层用例不重复：这里验的是**路由把 user_id 与 encrypted_data/iv
    串起来**（旧代码根本不按用户取 key）+ 新增必填字段落进 envelope。
    """
    uid = authed["user_id"]
    await _make_profile(db_session, uid)
    _stub_redis(monkeypatch, _user_key(uid))
    monkeypatch.setattr(steps_service, "get_settings", lambda: _decrypt_settings())
    encrypted, iv = _encrypt(_werun_payload([(OTHER_DAY, 1000), (TARGET_DAY, 9000)]))

    data = await _sync(db_client, authed["headers"], TARGET_DAY, 0, encrypted=(encrypted, iv))

    assert (data["steps"], data["steps_source"]) == (9000, steps_service.SOURCE_WERUN)
    row = await db_session.scalar(
        select(StepRecord).where(StepRecord.user_id == uid, StepRecord.record_date == TARGET_DAY)
    )
    snap = await db_session.scalar(
        select(DailySnapshot).where(
            DailySnapshot.user_id == uid, DailySnapshot.snapshot_date == TARGET_DAY
        )
    )
    assert row.steps == 9000  # 入库的是解密值，不是前端回退传的 0
    assert snap.steps == 9000
    assert snap.calibration_used is True


# F-09b：同步时回填微信运动 31 天历史 + GET /steps/trend 读曲线
#   官方事实：解密明文 stepInfoList 固定 31 条**按天**记录（index 0=30 天前、30=今天），
#   无逐时数据。旧实现只挑当天一条、丢弃其余 30 天 —— 这就是历史曲线恒空的根因。

FULL_WINDOW = [(TARGET_DAY - timedelta(days=30 - i), 1000 + i * 100) for i in range(31)]


async def _werun_setup(
    db_session,
    authed,
    monkeypatch: pytest.MonkeyPatch,
    days: list[tuple[date, int]],
    *,
    keyed: bool = True,
) -> tuple[str, str]:
    """配好解密链路（建档 + 本人 session_key + 测试 AppID），返回加密后的 payload。

    `keyed=False` 造「Redis 里没有这个用户的 key」这条降级分支。
    """
    uid = authed["user_id"]
    await _make_profile(db_session, uid)
    _stub_redis(monkeypatch, _user_key(uid) if keyed else {})
    monkeypatch.setattr(steps_service, "get_settings", lambda: _decrypt_settings())
    return _encrypt(_werun_payload(days))


async def _add_step_rows(session, user_id: int, rows: list[tuple[date, int]]) -> None:
    """直插 step_record：曲线读侧只关心"某天有没有行"，无须绕一圈同步。"""
    session.add_all([StepRecord(user_id=user_id, record_date=d, steps=s) for d, s in rows])
    await session.commit()


async def _trend(db_client, headers, days: int | None = None) -> list[dict]:
    params = {} if days is None else {"days": days}
    resp = await db_client.get("/api/steps/trend", params=params, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    return body["data"]["items"]


async def test_steps_sync_backfills_full_werun_window(
    db_client, db_session, authed, monkeypatch: pytest.MonkeyPatch
):
    """解密成功 → 31 条按天记录全量入库；backfilled_days 只数非当天（旧实现只留 1 行）。"""
    uid = authed["user_id"]
    encrypted, iv = await _werun_setup(db_session, authed, monkeypatch, FULL_WINDOW)

    data = await _sync(db_client, authed["headers"], TARGET_DAY, 0, encrypted=(encrypted, iv))

    assert (data["steps"], data["steps_source"]) == (4000, steps_service.SOURCE_WERUN)
    assert data["backfilled_days"] == 30
    rows = (
        await db_session.scalars(
            select(StepRecord).where(StepRecord.user_id == uid).order_by(StepRecord.record_date)
        )
    ).all()
    # 全量、按日期升序，且当天有且只有一行
    assert [(r.record_date, r.steps) for r in rows] == FULL_WINDOW
    history = [r for r in rows if r.record_date != TARGET_DAY]
    # 历史行不编逐时（微信运动根本没有）、不拿"今天的档案"倒算 MET，来源如实标 1=微信
    assert all(
        r.hourly_json == {} and r.calibrated_met is None and int(r.source) == 1 for r in history
    )
    # 硬约束：只有当天补/重算快照，历史日期一行都不补
    # （daily_snapshot 是热量账户落点，为画步数补快照 = 把从未记录的 intake/tee/deficit 伪造成 0）
    snap_stmt = select(DailySnapshot.snapshot_date).where(DailySnapshot.user_id == uid)
    assert list((await db_session.scalars(snap_stmt)).all()) == [TARGET_DAY]


@pytest.mark.parametrize(
    "keyed, use_full_window",
    [(False, True), (True, False)],
    ids=["无本人key降级(含当天记录)", "解密成功但缺当天记录"],
)
async def test_steps_sync_degraded_backfills_nothing(
    db_client,
    db_session,
    authed,
    monkeypatch: pytest.MonkeyPatch,
    keyed: bool,
    use_full_window: bool,
):
    """降级路径（steps_source=2/3）一律不回填：payload 里带着整段历史也一行都不许写。"""
    uid = authed["user_id"]
    days = FULL_WINDOW if use_full_window else [p for p in FULL_WINDOW if p[0] != TARGET_DAY]
    encrypted, iv = await _werun_setup(db_session, authed, monkeypatch, days, keyed=keyed)

    data = await _sync(db_client, authed["headers"], TARGET_DAY, 1000, encrypted=(encrypted, iv))

    assert data["steps"] == 1000  # 用的是传入值，不是 payload 里的任何一条
    assert data["steps_source"] == steps_service.SOURCE_CLIENT
    assert data["backfilled_days"] == 0
    dates = (
        await db_session.scalars(select(StepRecord.record_date).where(StepRecord.user_id == uid))
    ).all()
    assert list(dates) == [TARGET_DAY]  # 除当天外没有任何历史行被"顺手"写进去


async def test_steps_sync_backfill_conflict_updates_in_place(
    db_client, db_session, authed, monkeypatch: pytest.MonkeyPatch
):
    """重复同步幂等：行数不翻倍、改动后的真值被刷新，且不抹平既有逐时/校准 MET。"""
    uid = authed["user_id"]
    early_day = FULL_WINDOW[3][0]
    encrypted, iv = await _werun_setup(db_session, authed, monkeypatch, FULL_WINDOW)
    # 先用客户端逐时数据同步窗口内的某一天 → 这行带 hourly_json 与 calibrated_met
    await _sync(db_client, authed["headers"], early_day, 1234, hourly={"9": 1234})

    first = await _sync(db_client, authed["headers"], TARGET_DAY, 0, encrypted=(encrypted, iv))
    changed = [(d, s + 500) for d, s in FULL_WINDOW]
    encrypted2, iv2 = _encrypt(_werun_payload(changed))
    second = await _sync(db_client, authed["headers"], TARGET_DAY, 0, encrypted=(encrypted2, iv2))

    # 口径：backfilled_days = 本次回填的非当天行数（与是否首次插入无关）
    assert (first["backfilled_days"], second["backfilled_days"]) == (30, 30)
    rows = (
        await db_session.scalars(
            select(StepRecord).where(StepRecord.user_id == uid).order_by(StepRecord.record_date)
        )
    ).all()
    assert [(r.record_date, r.steps) for r in rows] == changed  # 31 行仍是 31 行，值刷成新真值
    early = next(r for r in rows if r.record_date == early_day)
    assert early.hourly_json == {"9": 1234}  # 按天回填不得把更丰富的既有逐时数据清成 {}
    assert early.calibrated_met is not None


@pytest.mark.parametrize(
    "days, expected_offsets",
    [
        (None, [0, 1, 2, 6]),  # 缺省 31 天
        (1, [0]),
        (2, [0, 1]),
        (7, [0, 1, 2, 6]),  # 左端点 today-6 当天含进来
        (31, [0, 1, 2, 6]),  # 第 40 天那条落在 31 天窗口外
    ],
    ids=["缺省31", "days=1", "days=2", "days=7", "days=31"],
)
async def test_steps_trend_window_order_and_no_zero_fill(
    db_client, db_session, authed, days: int | None, expected_offsets: list[int]
):
    """曲线直读 step_record：区间内升序返回、缺记录的日期不出现（不补零）、窗口外不出现。"""
    uid = authed["user_id"]
    today = datetime.now(_STEPS_TZ).date()
    seeded = {offset: 1000 + offset for offset in (0, 1, 2, 6, 40)}
    await _add_step_rows(
        db_session, uid, [(today - timedelta(days=o), s) for o, s in seeded.items()]
    )

    items = await _trend(db_client, authed["headers"], days)

    # 偏移量**降序**= 日期升序；逐日比对同时证明中间空掉的 3/4/5 天没被补成 0 步
    # （"没同步过"若被画成"走了 0 步"，这里就会多出一截）
    offsets = sorted(expected_offsets, reverse=True)
    assert [item["date"] for item in items] == [
        (today - timedelta(days=o)).isoformat() for o in offsets
    ]
    assert [item["steps"] for item in items] == [seeded[o] for o in offsets]
    assert [item["source"] for item in items] == [1] * len(offsets)


@pytest.mark.parametrize("days", [0, 32], ids=["days=0", "days=32"])
async def test_steps_trend_days_out_of_range_422(db_client, authed, days: int):
    """days 越界 → 422/2001（契约 minimum 1 / maximum 31），不许静默夹到合法区间后多读天数。"""
    resp = await db_client.get("/api/steps/trend", params={"days": days}, headers=authed["headers"])
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_steps_trend_isolated_per_user(db_client, db_session, authed):
    """行级隔离（AGENTS §7.3）：A 读不到 B 的行，B 也读不到 A 的行。"""
    today = datetime.now(_STEPS_TZ).date()
    other_user = User(openid=f"trend-other-{id(db_session)}", nickname="隔壁减友", gender=1)
    db_session.add(other_user)
    await db_session.flush()
    other_token = create_access_token(str(other_user.id), openid=other_user.openid)
    await db_session.commit()
    other_headers = {"Authorization": f"Bearer {other_token}"}
    await _add_step_rows(db_session, authed["user_id"], [(today, 1111)])
    await _add_step_rows(db_session, other_user.id, [(today - timedelta(days=1), 9999)])

    mine = [(i["date"], i["steps"]) for i in await _trend(db_client, authed["headers"])]
    theirs = [(i["date"], i["steps"]) for i in await _trend(db_client, other_headers)]
    assert mine == [(today.isoformat(), 1111)]
    assert theirs == [((today - timedelta(days=1)).isoformat(), 9999)]
