"""步数同步服务（BE2b）：写 step_record（幂等）+ NEAT 校准 + 触发当日快照重算。

口径（04 §6.3.3）：
- NEAT_calibrated、calibration_used 由 `calorie.calibrate_neat` 给出：
  步数<=0 → 状态法（未校准）；步数>0 → 步数 0.6 + 状态 0.4 加权（已校准）。
- 逐时步频→MET 映射复用 `calorie`（散步 2.5 / 快走 4.3 / 跑步 8.0）。
- `met`（落 step_record.calibrated_met）【假设】= NEAT_calibrated / (体重 × 非睡眠小时)，
  即加权后的等效 MET；步数=0 时退化为状态法 MET（MET_state）。
- `delta_calories` = NEAT_calibrated − 状态法 NEAT（校准带来的额外消耗，步数=0 时为 0）。
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.models import StepRecord
from app.schemas.common import ErrorCode
from app.schemas.record import StepsSyncData
from app.services import account, calorie
from app.services.wechat_pay import _SBOX, _add_round_key, _gf_mul, _key_expansion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 微信运动步数解密（AES-128-CBC + PKCS#7）— 纯标准库骨架（F-09）
#
# 复用 `wechat_pay` 的 AES 加密核（S 盒 / 轮密钥扩展）补齐**解密**分支：
# 微信 `uni.getWeRunData` 的 encryptedData / iv 均为 base64，密钥为 16 字节
# session_key，填充方式 PKCS#7。无凭证 / 解密失败 → 明确降级（不伪造步数）。
# ---------------------------------------------------------------------------

_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i

_STEPS_TZ = timezone(timedelta(hours=8))  # 微信运动时间戳按北京时间（UTC+8）


def _inv_sub_bytes(state: list[int]) -> None:
    for i in range(16):
        state[i] = _INV_SBOX[state[i]]


def _inv_shift_rows(state: list[int]) -> None:
    for r in range(1, 4):
        row = [state[4 * c + r] for c in range(4)]
        row = row[-r:] + row[:-r]
        for c in range(4):
            state[4 * c + r] = row[c]


def _inv_mix_columns(state: list[int]) -> None:
    for c in range(4):
        i = 4 * c
        a0, a1, a2, a3 = state[i], state[i + 1], state[i + 2], state[i + 3]
        state[i] = _gf_mul(a0, 14) ^ _gf_mul(a1, 11) ^ _gf_mul(a2, 13) ^ _gf_mul(a3, 9)
        state[i + 1] = _gf_mul(a0, 9) ^ _gf_mul(a1, 14) ^ _gf_mul(a2, 11) ^ _gf_mul(a3, 13)
        state[i + 2] = _gf_mul(a0, 13) ^ _gf_mul(a1, 9) ^ _gf_mul(a2, 14) ^ _gf_mul(a3, 11)
        state[i + 3] = _gf_mul(a0, 11) ^ _gf_mul(a1, 13) ^ _gf_mul(a2, 9) ^ _gf_mul(a3, 14)


def _decrypt_block(block: bytes, key: bytes) -> bytes:
    """AES 单分组解密（128/192/256 通用，轮数由 `_key_expansion` 按密钥长度推断）。"""
    words, nr = _key_expansion(key)
    state = list(block)
    _add_round_key(state, words, nr)
    for rnd in range(nr - 1, 0, -1):
        _inv_shift_rows(state)
        _inv_sub_bytes(state)
        _add_round_key(state, words, rnd)
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    _inv_sub_bytes(state)
    _add_round_key(state, words, 0)
    return bytes(state)


def _aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-CBC 解密 + PKCS#7 去填充（密文长度须为 16 的整数倍）。"""
    if len(key) not in (16, 24, 32):
        raise ValueError("AES 密钥长度非法")
    if len(iv) != 16:
        raise ValueError("iv 应为 16 字节")
    if not data or len(data) % 16 != 0:
        raise ValueError("密文长度非法")
    plain = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        block = data[i : i + 16]
        decrypted = _decrypt_block(block, key)
        plain.extend(a ^ b for a, b in zip(decrypted, prev, strict=True))
        prev = block
    pad = plain[-1]
    if pad < 1 or pad > 16 or pad > len(plain) or bytes(plain[-pad:]) != bytes([pad]) * pad:
        raise ValueError("PKCS#7 填充非法")
    return bytes(plain[:-pad])


def decrypt_we_run_data(encrypted_data: str, iv: str, session_key: str) -> dict:
    """解密微信 `getWeRunData` 的 encrypted_data（base64）→ 明文 JSON dict。"""
    plain = _aes_cbc_decrypt(
        base64.b64decode(session_key), base64.b64decode(iv), base64.b64decode(encrypted_data)
    )
    payload = json.loads(plain.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("解密结果不是 JSON 对象")
    return payload


def extract_day_steps(payload: dict, day: date) -> int:
    """从解密后 `stepInfoList` 取目标日期步数；无当天记录则取最新一条。"""
    items = payload.get("stepInfoList")
    if not isinstance(items, list) or not items:
        raise ValueError("解密数据缺少 stepInfoList")
    matched: int | None = None
    for item in items:
        if not isinstance(item, dict) or "timestamp" not in item:
            continue
        item_day = datetime.fromtimestamp(int(item["timestamp"]), tz=_STEPS_TZ).date()
        if item_day == day:
            matched = int(item.get("step", 0))
    if matched is not None:
        return max(matched, 0)
    return max(int(items[-1].get("step", 0)), 0)


def _resolve_steps(
    steps: int, encrypted_data: str | None, iv: str | None, day: date, settings: Settings
) -> int:
    """有加密数据且凭证齐备 → 解密取真实步数；否则明确降级用传入 steps（不伪造）。"""
    if not encrypted_data or not iv:
        return steps
    if not (
        settings.WECHAT_APPID and settings.WECHAT_SECRET and settings.WECHAT_STEPS_SESSION_KEY
    ):
        logger.warning("微信步数解密未配置凭证，明确降级：按传入 steps=%s 计（不伪造）", steps)
        return steps
    try:
        payload = decrypt_we_run_data(encrypted_data, iv, settings.WECHAT_STEPS_SESSION_KEY)
        return extract_day_steps(payload, day)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        logger.warning("微信步数解密失败，明确降级：按传入 steps=%s 计（不伪造）：%s", steps, exc)
        return steps


async def _require_weight(session: AsyncSession, user_id: int) -> tuple[float, int]:
    """取建档体重与活动水平；未建档/体重非法抛 3001（与账户服务一致）。"""
    profile = await account.get_body_profile(session, user_id)
    weight = float(profile.current_weight) if profile and profile.current_weight else 0.0
    if profile is None or weight <= 0:
        raise AppException(ErrorCode.NOT_FOUND, "尚未创建身体档案")
    return weight, int(profile.activity_level or calorie.DEFAULT_ACTIVITY_LEVEL)


async def _upsert_step_record(
    session: AsyncSession,
    user_id: int,
    day: date,
    steps: int,
    hourly: dict | None,
    met: float,
) -> None:
    """(user_id, record_date) 幂等 upsert；重复同步同一天只更新不新增。"""
    values = {
        "user_id": user_id,
        "record_date": day,
        "steps": steps,
        "hourly_json": hourly or {},
        "calibrated_met": met,
    }
    stmt = pg_insert(StepRecord).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "record_date"],
        set_={"steps": steps, "hourly_json": hourly or {}, "calibrated_met": met},
    )
    await session.execute(stmt)
    await session.commit()


async def sync_steps(
    session: AsyncSession,
    user_id: int,
    day: date,
    steps: int,
    hourly: dict | None = None,
    *,
    encrypted_data: str | None = None,
    iv: str | None = None,
    settings: Settings | None = None,
) -> StepsSyncData:
    """落库步数 → 校准 NEAT → 重算当日快照，返回校准结果。

    F-09：有微信运动加密数据（encrypted_data/iv）且凭证齐备时解密取真实步数；
    无凭证 / 解密失败 → **明确降级**用传入 steps（前端回退传 0 → PAL 估算），不伪造。
    """
    resolved = _resolve_steps(steps, encrypted_data, iv, day, settings or get_settings())
    weight, level = await _require_weight(session, user_id)

    neat, _used = calorie.calibrate_neat(
        weight_kg=weight, activity_level=level, steps=resolved, hourly=hourly
    )
    state = calorie.state_neat(weight_kg=weight, activity_level=level)
    # 加权后等效 MET（见模块 docstring【假设】）
    met = round(neat / (weight * calorie.NON_SLEEP_HOURS), 2)

    await _upsert_step_record(session, user_id, day, resolved, hourly, met)
    # 步数变化影响 NEAT/校准标记 → 重算当日快照（幂等）
    await account.recompute_day(session, user_id, day)

    return StepsSyncData(
        neat_calibrated=neat,
        met=met,
        delta_calories=round(neat - state, 1),
    )
