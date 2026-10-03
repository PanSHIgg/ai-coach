"""步数同步服务（BE2b）：写 step_record（幂等）+ NEAT 校准 + 触发当日快照重算。

口径（04 §6.3.3）：
- NEAT_calibrated、calibration_used 由 `calorie.calibrate_neat` 给出：
  步数<=0 → 状态法（未校准）；步数>0 → 步数 0.6 + 状态 0.4 加权（已校准）。
- 逐时步频→MET 映射复用 `calorie`（散步 2.5 / 快走 4.3 / 跑步 8.0）。
- 微信运动只有**按天**数据（stepInfoList 固定 31 条），无逐时来源；`hourly` 是客户端
  另行提供的可选补充，与解密结果互不伪造。
- 实际入库步数与数据来源随 `steps_source` 返回：1=微信运动解密成功、2=采用客户端传入值、
  3=完全未取到（steps=0，按 PAL 估算）——§2.4「步数取不到 → 用 PAL 系数估算 NEAT」。
- `met`（落 step_record.calibrated_met）【假设】= NEAT_calibrated / (体重 × 非睡眠小时)，
  即加权后的等效 MET；步数=0 时退化为状态法 MET（MET_state）。
- `delta_calories` = NEAT_calibrated − 状态法 NEAT（校准带来的额外消耗，步数=0 时为 0）。
- **同步即回填 31 天历史**：解密成功时 stepInfoList 的**全部**条目都按天 upsert 进
  step_record（旧实现只挑当天一条、丢弃其余 30 天 → 历史曲线恒空）；降级路径一律不回填。
  历史日期**不生成/不重算 daily_snapshot**（理由见 `sync_steps`），步数曲线另由
  `get_step_trend`（`GET /steps/trend`）直读 step_record。
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.models import StepRecord
from app.schemas.common import ErrorCode
from app.schemas.record import StepsSyncData, StepsTrendData, StepTrendItem
from app.services import account, auth_service, calorie
from app.services.wechat_pay import _SBOX, _add_round_key, _gf_mul, _key_expansion

logger = logging.getLogger(__name__)


# steps_source 三态（契约 `StepsSyncData.steps_source`，openapi enum [1,2,3]）
SOURCE_WERUN = 1  # 微信运动解密成功：session_key 命中 + watermark.appid 校验通过 + 目标日期有记录
SOURCE_CLIENT = 2  # 采用客户端传入的 steps（解密链路任一环节不可用，但客户端给了非 0 值）
SOURCE_NONE = 3  # 完全未取到：steps=0，NEAT 按 PAL（状态法）估算

# 微信运动 `stepInfoList` 官方固定 31 条按天记录（index 0 = 30 天前，index 30 = 今天）。
# 既是回填条数上限，也是 `GET /steps/trend` 的 `days` 上限（契约 maximum: 31）。
WERUN_MAX_DAYS = 31


# 微信运动步数解密（AES-128-CBC + PKCS#7）— 官方链路（F-09）
#
# 复用 `wechat_pay` 的 AES 加密核（S 盒 / 轮密钥扩展）补齐**解密**分支：
# 微信 `uni.getWeRunData` 的 encryptedData / iv 均为 base64，密钥是 code2Session 返回的
# **session_key**（base64，会话态、每次登录轮换）→ 按用户从 Redis 取（`auth_service`），
# 而不是读静态环境变量。解密结果须过 `watermark.appid` 校验（确认来源、防串号），
# 且目标日期在 `stepInfoList`（固定 31 条**按天**记录）里必须有记录。
# 任一环节不满足 → 明确降级（steps_source=2/3），**绝不伪造或借用步数**。

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
    """解密微信 `getWeRunData` 的 encrypted_data（base64）→ 明文 JSON dict。

    session_key 必须是**同一次登录** code2Session 返回值（base64）；会话轮换后用旧 key
    解密会因 PKCS#7 填充非法而抛错，由调用方明确降级。
    """
    plain = _aes_cbc_decrypt(
        base64.b64decode(session_key), base64.b64decode(iv), base64.b64decode(encrypted_data)
    )
    payload = json.loads(plain.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("解密结果不是 JSON 对象")
    return payload


def verify_watermark(payload: dict, appid: str) -> None:
    """校验解密结果的 `watermark.appid` 等于本小程序 AppID（确认数据来源、防串号）。

    官方口径：敏感数据明文里带 watermark 字段，后端据此确认数据确实签发给本小程序。
    不符 / 缺失 / 本服务未配置 WECHAT_APPID（无从比对）→ 视为**不可信**，抛错由调用方降级。
    """
    if not appid:
        raise ValueError("未配置 WECHAT_APPID，无法校验 watermark.appid")
    mark = payload.get("watermark")
    source_appid = mark.get("appid") if isinstance(mark, dict) else None
    if not source_appid:
        raise ValueError("解密数据缺少 watermark.appid，无法确认数据来源")
    if source_appid != appid:
        raise ValueError(f"watermark.appid 与本小程序 AppID 不一致（疑似串号）：{source_appid!r}")


def extract_day_steps(payload: dict, day: date) -> int | None:
    """从解密后 `stepInfoList`（固定 31 条按天记录）取目标日期步数。

    **找不到目标日期 → 返回 None**。旧实现在此返回 `items[-1]` 的步数，等于把另一天的
    步数当成当天写进 `step_record` 并参与 NEAT 校准（热量账户被陌生日期的数据污染）；
    现在由调用方按 steps_source=2/3 明确降级，不猜、不借。
    """
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
    return None if matched is None else max(matched, 0)


def extract_step_history(payload: dict) -> dict[date, int]:
    """全量展开解密后的 `stepInfoList`（≤31 条按天记录）→ {北京时间日期: 步数}。

    历史曲线没数据的根因就在这：只调 `extract_day_steps` 取当天一条，其余 30 天随手丢弃。
    取值口径与 `extract_day_steps` 一致——非 dict / 缺 timestamp 的条目跳过、同一天重复条目
    取后出现的一条、负数按 0 计；「缺当天不借用其它日期」那条语义仍由它守住。
    """
    items = payload.get("stepInfoList")
    if not isinstance(items, list) or not items:
        raise ValueError("解密数据缺少 stepInfoList")
    history: dict[date, int] = {}
    for item in items:
        if not isinstance(item, dict) or "timestamp" not in item:
            continue
        item_day = datetime.fromtimestamp(int(item["timestamp"]), tz=_STEPS_TZ).date()
        history[item_day] = max(int(item.get("step", 0)), 0)
    return history


def _client_source(steps: int) -> int:
    """降级来源标注：客户端给了非 0 步数 → 2（采用传入值）；连值都没有（0）→ 3（未取到）。"""
    return SOURCE_CLIENT if steps > 0 else SOURCE_NONE


# 静态 env 兜底只用于本地调试：整进程只 warning 一次，免得刷日志。
_static_key_warned = False


def _warn_static_key_once() -> None:
    global _static_key_warned
    if _static_key_warned:
        return
    _static_key_warned = True
    logger.warning(
        "Redis 无该用户 session_key，回落静态 WECHAT_STEPS_SESSION_KEY（仅本地调试用，"
        "生产应按登录持久化的 key 解密）"
    )


async def _resolve_steps(
    user_id: int,
    steps: int,
    encrypted_data: str | None,
    iv: str | None,
    day: date,
    settings: Settings,
) -> tuple[int, int, dict[date, int]]:
    """定源解析当天步数，返回 (实际入库步数, steps_source, 解密得到的按天历史)。

    官方链路：有加密数据 → 取**该用户本次登录**的 session_key（Redis）解密 → 校验
    watermark.appid → 在 stepInfoList 里找**目标日期**的记录。任一环节不满足都明确降级
    为客户端传入值（steps>0 → 2；steps=0 → 3），绝不伪造步数，也不再要求 WECHAT_SECRET
    （解密与支付凭证无关）。

    第三个返回值是**回填用的历史窗口**：只有解密成功（source=1）才非空，降级路径恒为 `{}`。
    这是刻意的构造方式——把「能不能回填」的判定收敛到唯一的赋值点，调用方无须再判 source，
    也就不存在「拿客户端假数据填历史」的分支。
    """
    if not encrypted_data or not iv:
        return steps, _client_source(steps), {}
    session_key = await auth_service.get_session_key(user_id)
    if not session_key:
        # 主路径只有"登录时持久化的 per-user key"；静态 env 仅作显式本地调试兜底
        session_key = settings.WECHAT_STEPS_SESSION_KEY
        if session_key:
            _warn_static_key_once()
        else:
            logger.warning(
                "无 session_key（用户未登录或 Redis 无值），微信步数明确降级：按传入 steps=%s 计",
                steps,
            )
            return steps, _client_source(steps), {}
    try:
        payload = decrypt_we_run_data(encrypted_data, iv, session_key)
        verify_watermark(payload, settings.WECHAT_APPID)
        day_steps = extract_day_steps(payload, day)
        history = extract_step_history(payload)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        logger.warning("微信步数解密失败，明确降级：按传入 steps=%s 计（不伪造）：%s", steps, exc)
        return steps, _client_source(steps), {}
    if day_steps is None:
        # 借数污染防线：stepInfoList 里没有当天记录时，不得用其它日期的步数顶替。
        # 历史窗口此时同样**不许回填**：当天都对不上，说明这份 payload 与本请求不同源，
        # 整段写进 step_record 等于用未经确认的数据铺历史曲线。
        logger.warning(
            "微信运动解密成功但 stepInfoList 无 %s 当天记录，明确降级：按传入 steps=%s 计",
            day,
            steps,
        )
        return steps, _client_source(steps), {}
    # 当天记录为 0 也算"解密取到"（source=1，真·零步），与"没取到"（source=3）区分开
    return day_steps, SOURCE_WERUN, history


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


async def _backfill_history(
    session: AsyncSession,
    user_id: int,
    day: date,
    history: dict[date, int],
) -> int:
    """把微信运动一次解出的历史步数 upsert 进 step_record，返回写入的**非当天**行数。

    `history` 只在解密成功（steps_source=1）时非空（唯一赋值点在 `_resolve_steps` 末尾），
    所以降级路径（2/3）在这里天然一行都不写 —— 假数据铺进历史曲线比没有曲线更糟：
    前端会把编出来的步数当成真值参与达标判断与报告。

    写入口径：
    - 幂等键 (user_id, record_date)（表上唯一约束）：重复同步只更新不新增；
    - `hourly_json` 恒为 `{}`：微信运动**没有**逐时数据，编出来的逐时会被 `calorie`
      按小时步频映射 MET，反向污染校准；
    - `calibrated_met` 不写（留 NULL）：校准要用「现在」的体重/活动水平倒算历史，同样造数；
    - 冲突时 set_ 只更 `steps` + `source`：该日期若早有更丰富的记录（客户端逐时 + 已算 MET），
      按天回填只刷新步数真值，**不抹平**那些字段；
    - `source=1`（微信），与 04 §7.2 建表注释一致。
    """
    if not history:
        return 0
    # payload 由 session_key + watermark.appid 认证过，条数本应恒为 31；仍按最新 31 天封顶写，
    # 免得异常 payload 把写入行数放大成任意值。
    written = 0
    for item_day in sorted(history, reverse=True)[:WERUN_MAX_DAYS]:
        if item_day == day:
            continue  # 当天走 _upsert_step_record（带逐时与校准 MET）
        stmt = pg_insert(StepRecord).values(
            user_id=user_id,
            record_date=item_day,
            steps=history[item_day],
            hourly_json={},
            source=SOURCE_WERUN,
        ).on_conflict_do_update(
            index_elements=["user_id", "record_date"],
            set_={"steps": history[item_day], "source": SOURCE_WERUN},
        )
        await session.execute(stmt)
        written += 1
    await session.commit()
    return written


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
    """落库步数 → 校准 NEAT → 回填历史步数 → 重算当日快照，返回校准结果。

    F-09：有微信运动加密数据（encrypted_data/iv）时，按**该用户本次登录**持久化的
    session_key 解密并校验 watermark.appid；链路任一环节不满足（无 key / 解密失败 /
    appid 不符 / 当天无记录）→ **明确降级**用传入 steps（前端回退传 0 → PAL 估算），
    不伪造、不借用其它日期的步数。来源见 `steps_source`（1/2/3）。

    解密成功时顺带把 stepInfoList 的其余历史日期一并回填进 step_record（≤31 条按天记录，
    旧实现只留当天 → 历史曲线恒空），回填写入行数见 `backfilled_days`（不含当天）。
    """
    # 先校验档案（未建档 3001 直接返回），避免为注定失败的请求跑一遍纯 Python AES
    weight, level = await _require_weight(session, user_id)
    resolved, source, history = await _resolve_steps(
        user_id, steps, encrypted_data, iv, day, settings or get_settings()
    )

    neat, _used = calorie.calibrate_neat(
        weight_kg=weight, activity_level=level, steps=resolved, hourly=hourly
    )
    state = calorie.state_neat(weight_kg=weight, activity_level=level)
    # 加权后等效 MET（见模块 docstring【假设】）
    met = round(neat / (weight * calorie.NON_SLEEP_HOURS), 2)

    await _upsert_step_record(session, user_id, day, resolved, hourly, met)
    # 顺带回填历史天数；history 仅解密成功才非空，故降级路径这里一行都不写
    backfilled = await _backfill_history(session, user_id, day, history)
    # 步数变化影响 NEAT/校准标记 → **只重算当天**的快照。
    # 历史日期一律不生成/不重算 daily_snapshot：快照是热量账户（intake/tee/deficit）的落点，
    # 为画一条步数曲线给历史日期补快照，等于把这些天从未记录过的摄入与消耗伪造成 0，
    # 直接污染账户与报告（`account.get_trend` 明确"无快照的日期不造数"）。
    # 步数曲线的正当出口是直读 step_record 的 `get_step_trend`（GET /steps/trend）。
    await account.recompute_day(session, user_id, day)

    return StepsSyncData(
        neat_calibrated=neat,
        met=met,
        delta_calories=round(neat - state, 1),
        steps=resolved,
        steps_source=source,
        backfilled_days=backfilled,
    )


async def get_step_trend(
    session: AsyncSession, user_id: int, days: int = WERUN_MAX_DAYS
) -> StepsTrendData:
    """步数历史曲线：**直读 step_record**（不经 daily_snapshot）。

    区间 [今天-days+1, 今天]（北京时间，与步数时间戳同口径），按日期**升序**返回。
    两条硬口径：
    - 必须带 `user_id` 条件（AGENTS §7.3 行级隔离，越权即 P0）；
    - **没有记录的日期不出现、不补零**：「那天没同步过」和「那天走了 0 步」是两件事，
      补零会把前者画成后者（前端按柱状图渲染，用户会以为教练给了个差评日）。
    """
    today = datetime.now(_STEPS_TZ).date()
    rows = (
        await session.execute(
            select(StepRecord.record_date, StepRecord.steps, StepRecord.source)
            .where(
                StepRecord.user_id == user_id,
                StepRecord.record_date >= today - timedelta(days=days - 1),
                StepRecord.record_date <= today,
            )
            .order_by(StepRecord.record_date)
        )
    ).all()
    return StepsTrendData(
        items=[
            StepTrendItem(date=row.record_date, steps=int(row.steps), source=int(row.source))
            for row in rows
        ]
    )
