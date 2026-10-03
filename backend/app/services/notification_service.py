"""提醒订阅服务（BE-n + F-06）：订阅设置 upsert + 提醒调度入队 + 订阅消息发送抽象。

- 订阅：(user_id, template_type) 唯一；订阅幂等 upsert（status=1、subscribe_count+1、
  last_subscribe_at=now）；取消置 status=0（保留累计次数）。
- 调度：`enqueue_due_reminders` 到点把待发提醒投入 Redis Stream `notification:reminders`；
  Redis 不可用时优雅降级（仅记录待发列表、不抛异常）。
- 场景模板（F-06）：`SCENE_TEMPLATES` 覆盖文档 §1.2 所述「12+ 触发场景」
  （餐前 11:00/17:00、下午茶防诱惑、深夜防崩塌、超标后运动建议等），
  模板 ID 为占位【假设】，可用配置 `WECHAT_SUBSCRIBE_TEMPLATE_IDS` 覆盖。
- 发送（F-06）：`send_subscribe_message` 为发送微信订阅消息的接口函数——有凭证时走
  真实调用骨架，**无凭证/未启用时明确降级为日志记录并在返回值标记 degraded**，
  绝不静默伪造成功（sent=True 仅出现在真实调用被微信受理时）。
- 消费者：见 `app/tasks/reminder_consumer.py`（从本 Stream 读取并调用上述发送）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.redis import get_redis
from app.models import Subscription
from app.schemas.notification import SubscriptionData, SubscriptionItem, SubscriptionOut

logger = get_logger(__name__)

TZ = timezone(timedelta(hours=8))
REMINDER_WINDOW = timedelta(minutes=30)  # 到点判定窗口
REMINDER_STREAM_KEY = "notification:reminders"

# 占位模板 ID 后缀：命中即视为「未配置真实模板」→ 发送降级（不伪造成功）。
PLACEHOLDER_SUFFIX = "_ASSUMED"


@dataclass(frozen=True)
class ReminderScene:
    """提醒场景模板。

    - template_type：与 subscription.template_type 对应的整型键（1-4 为既有 API 可订阅项）；
    - code：场景稳定标识（日志/测试引用）；
    - name：中文场景名；
    - schedule：定时触发时刻；None 表示事件型触发（如超标后运动建议，由业务事件驱动）；
    - template_id：微信订阅消息模板 ID（【假设】占位，可用配置覆盖）。
    """

    template_type: int
    code: str
    name: str
    schedule: time | None
    template_id: str


# 场景清单（【假设】）：编号 1-4 沿用既有语义（schema/04 §6.3），其余为 F-06 扩充。
# 文档明示：餐前 11:00/17:00、下午茶防诱惑、深夜防崩塌、超标后运动建议（§1.2/§2.3.1）；
# 另按 §2.3.1 深夜缺口达成、§3/§8「需要你关注」列表补全至 12+ 场景。
SCENE_TEMPLATES: dict[int, ReminderScene] = {
    1: ReminderScene(1, "lunch_pre", "午餐餐前提醒", time(11, 0), "TPL_LUNCH_PRE_ASSUMED"),
    2: ReminderScene(2, "dinner_pre", "晚餐餐前提醒", time(17, 0), "TPL_DINNER_PRE_ASSUMED"),
    3: ReminderScene(
        3, "late_night_guard", "深夜防崩塌", time(22, 30), "TPL_LATE_NIGHT_GUARD_ASSUMED"
    ),
    4: ReminderScene(4, "morning_weigh", "晨起称重提醒", time(8, 0), "TPL_MORNING_WEIGH_ASSUMED"),
    5: ReminderScene(
        5, "afternoon_tea_guard", "下午茶防诱惑", time(15, 0), "TPL_AFTERNOON_TEA_GUARD_ASSUMED"
    ),
    6: ReminderScene(
        6, "breakfast_pre", "早餐餐前提醒", time(8, 30), "TPL_BREAKFAST_PRE_ASSUMED"
    ),
    7: ReminderScene(
        7, "gap_achieved", "当日缺口达成提醒", time(21, 0), "TPL_GAP_ACHIEVED_ASSUMED"
    ),
    8: ReminderScene(
        8, "over_intake_sport", "超标后运动建议", None, "TPL_OVER_INTAKE_SPORT_ASSUMED"
    ),
    9: ReminderScene(
        9, "protein_deficit", "蛋白质摄入不足提醒", None, "TPL_PROTEIN_DEFICIT_ASSUMED"
    ),
    10: ReminderScene(10, "sport_deficit", "运动不足提醒", None, "TPL_SPORT_DEFICIT_ASSUMED"),
    11: ReminderScene(
        11, "membership_expiry", "会员到期提醒", None, "TPL_MEMBERSHIP_EXPIRY_ASSUMED"
    ),
    12: ReminderScene(12, "recheck_due", "复查提醒", None, "TPL_RECHECK_DUE_ASSUMED"),
    13: ReminderScene(13, "coupon_expiry", "券即将过期提醒", None, "TPL_COUPON_EXPIRY_ASSUMED"),
}

# template_type → 定时提醒时刻（由场景表派生；事件型场景 schedule=None 不参与定时调度）
REMINDER_SCHEDULE: dict[int, time] = {
    t: s.schedule for t, s in SCENE_TEMPLATES.items() if s.schedule is not None
}

# 微信订阅消息发送接口（真实调用骨架）
SUBSCRIBE_SEND_URL = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"
WECHAT_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"


class SendResult(NamedTuple):
    """订阅消息发送结果。

    sent=True 仅当真实调用被微信受理；未配置凭证/降级时 sent=False 且 degraded=True，
    reason 说明降级/失败原因（绝不静默伪造成功）。
    """

    user_id: int
    template_type: int
    sent: bool
    degraded: bool
    reason: str | None = None


def _to_out(row: Subscription) -> SubscriptionOut:
    return SubscriptionOut(
        template_type=int(row.template_type),
        status=int(row.status),
        subscribe_count=int(row.subscribe_count or 0),
        last_subscribe_at=row.last_subscribe_at,
    )


def _to_item(row: Subscription) -> SubscriptionItem:
    return SubscriptionItem(
        template_type=int(row.template_type),
        status=int(row.status),
        subscribe_count=int(row.subscribe_count or 0),
        last_subscribe_at=row.last_subscribe_at,
    )


async def list_subscriptions(session: AsyncSession, user_id: int) -> SubscriptionData:
    """当前用户订阅列表（行级隔离）。"""
    rows = (
        (
            await session.execute(
                select(Subscription)
                .where(Subscription.user_id == user_id)
                .order_by(Subscription.template_type)
            )
        )
        .scalars()
        .all()
    )
    return SubscriptionData(items=[_to_item(r) for r in rows])


async def subscribe(session: AsyncSession, user_id: int, template_type: int) -> SubscriptionOut:
    """幂等订阅：(user_id, template_type) 冲突则 status=1、次数+1、刷新时间。"""
    stmt = pg_insert(Subscription).values(
        user_id=user_id,
        template_type=template_type,
        status=1,
        subscribe_count=1,
        last_subscribe_at=datetime.now(TZ),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "template_type"],
        set_={
            "status": 1,
            "subscribe_count": Subscription.subscribe_count + 1,
            "last_subscribe_at": datetime.now(TZ),
            "updated_at": datetime.now(TZ),
        },
    )
    await session.execute(stmt)
    await session.commit()
    row = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user_id, Subscription.template_type == template_type
            )
        )
    ).scalar_one()
    return _to_out(row)


async def cancel_subscription(
    session: AsyncSession, user_id: int, template_type: int
) -> SubscriptionOut:
    """取消订阅：status=0（保留 subscribe_count 累计）；无记录则建一条 status=0。"""
    stmt = pg_insert(Subscription).values(
        user_id=user_id, template_type=template_type, status=0, subscribe_count=0
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "template_type"],
        set_={"status": 0, "updated_at": datetime.now(TZ)},
    )
    await session.execute(stmt)
    await session.commit()
    row = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user_id, Subscription.template_type == template_type
            )
        )
    ).scalar_one()
    return _to_out(row)


def _due_template_types(at: datetime) -> list[int]:
    """当前时刻命中的提醒类型（±30 分钟窗口）。"""
    now_minutes = at.hour * 60 + at.minute
    due: list[int] = []
    for template_type, at_time in REMINDER_SCHEDULE.items():
        scheduled = at_time.hour * 60 + at_time.minute
        if abs(now_minutes - scheduled) <= REMINDER_WINDOW.total_seconds() // 60:
            due.append(template_type)
    return due


async def enqueue_due_reminders(session: AsyncSession, at: datetime | None = None) -> list[dict]:
    """调度入口：把到点且已订阅的提醒投入 Redis Stream；Redis 不可用则降级返回待发列表。"""
    now = at or datetime.now(TZ)
    due = _due_template_types(now)
    if not due:
        return []
    rows = (
        (
            await session.execute(
                select(Subscription).where(
                    Subscription.user_id.is_not(None),
                    Subscription.template_type.in_(due),
                    Subscription.status == 1,
                )
            )
        )
        .scalars()
        .all()
    )
    payloads = [
        {"user_id": int(r.user_id), "template_type": int(r.template_type), "at": now.isoformat()}
        for r in rows
    ]
    if not payloads:
        return []
    redis = await get_redis()
    if redis is None:
        # 优雅降级：不阻断、不抛错，仅记录待发列表待后续补发
        logger.warning("Redis 不可用，提醒调度降级（待发 %d 条）", len(payloads))
        return payloads
    try:
        for payload in payloads:
            await redis.xadd(
                REMINDER_STREAM_KEY, {"payload": json.dumps(payload, ensure_ascii=False)}
            )
    except Exception as exc:  # noqa: BLE001 - Redis 异常一律降级
        logger.warning("提醒入队失败，降级", extra={"reason": str(exc)})
    return payloads


# 微信订阅消息发送抽象（F-06）


def _template_id_map(settings: Settings | None = None) -> dict[int, str]:
    """解析配置 `WECHAT_SUBSCRIBE_TEMPLATE_IDS`（"type:id,..."）为映射；非法项跳过。"""
    s = settings or get_settings()
    raw = (getattr(s, "WECHAT_SUBSCRIBE_TEMPLATE_IDS", "") or "").strip()
    mapping: dict[int, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        key, value = pair.split(":", 1)
        try:
            mapping[int(key.strip())] = value.strip()
        except ValueError:
            continue
    return mapping


def resolve_template_id(template_type: int, settings: Settings | None = None) -> str:
    """模板 ID 解析：优先配置覆盖，回落场景表占位 ID；未知场景返回空串。"""
    configured = _template_id_map(settings).get(template_type)
    if configured:
        return configured
    scene = SCENE_TEMPLATES.get(template_type)
    return scene.template_id if scene else ""


def _has_real_template_id(template_id: str) -> bool:
    """真实模板 ID 判定：非空且非占位（不以后缀 PLACEHOLDER_SUFFIX 结尾）。"""
    return bool(template_id) and not template_id.endswith(PLACEHOLDER_SUFFIX)


def subscribe_message_ready(settings: Settings | None = None) -> bool:
    """订阅消息发送是否具备真实调用条件（开关 + 凭证）。模板 ID 需逐条判定。"""
    s = settings or get_settings()
    return bool(
        getattr(s, "WECHAT_SUBSCRIBE_ENABLED", False) and s.WECHAT_APPID and s.WECHAT_SECRET
    )


def build_scene_payload(template_type: int) -> dict:
    """构造订阅消息 data 占位（【假设】字段名对齐微信 thing/number/time 类目）。

    真实字段需按所选模板类目在微信后台定义后回填；此处仅给出骨架结构。
    """
    scene = SCENE_TEMPLATES.get(template_type)
    name = scene.name if scene else f"提醒类型{template_type}"
    return {
        "thing1": {"value": name[:20]},
        "thing2": {"value": "AI 教练提醒，点击查看详情"},
        "time3": {"value": datetime.now(TZ).strftime("%Y-%m-%d %H:%M")},
    }


async def send_subscribe_message(
    user_id: int,
    template_type: int,
    *,
    openid: str | None = None,
    page: str = "pages/index/index",
    data: dict | None = None,
    settings: Settings | None = None,
) -> SendResult:
    """发送微信订阅消息的接口函数。

    - 有凭证（WECHAT_SUBSCRIBE_ENABLED + WECHAT_APPID/SECRET + 真实模板 ID）→ 走真实调用；
    - 否则明确降级为日志记录，返回 `degraded=True`（**绝不静默伪造成功**）。
    """
    s = settings or get_settings()
    template_id = resolve_template_id(template_type, s)

    if not subscribe_message_ready(s) or not _has_real_template_id(template_id):
        reason = "no_credentials"
        logger.info(
            "订阅消息发送降级（未启用/无凭证/模板未配置），仅记录不发送",
            extra={
                "user_id": user_id,
                "template_type": template_type,
                "template_id": template_id,
                "reason": reason,
            },
        )
        return SendResult(user_id, template_type, sent=False, degraded=True, reason=reason)

    if not openid:
        logger.warning(
            "订阅消息发送降级（缺少 openid）",
            extra={"user_id": user_id, "template_type": template_type},
        )
        return SendResult(user_id, template_type, sent=False, degraded=True, reason="no_openid")

    try:
        await _wechat_send_subscribe_message(
            openid, template_id, page=page, data=data or build_scene_payload(template_type)
        )
    except Exception as exc:  # noqa: BLE001 - 发送失败一律降级，不向调用方抛错
        logger.warning(
            "订阅消息发送失败，已降级",
            extra={"user_id": user_id, "template_type": template_type, "reason": str(exc)},
        )
        return SendResult(user_id, template_type, sent=False, degraded=True, reason=str(exc))

    logger.info(
        "订阅消息发送成功", extra={"user_id": user_id, "template_type": template_type}
    )
    return SendResult(user_id, template_type, sent=True, degraded=False)


async def _wechat_access_token(settings: Settings) -> str:  # pragma: no cover - 依赖真实凭据
    import httpx

    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(
            WECHAT_TOKEN_URL,
            params={
                "grant_type": "client_credential",
                "appid": settings.WECHAT_APPID,
                "secret": settings.WECHAT_SECRET,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    if payload.get("errcode"):
        raise RuntimeError(f"获取 access_token 失败: {payload.get('errmsg')}")
    return payload["access_token"]


async def _wechat_send_subscribe_message(
    openid: str, template_id: str, *, page: str, data: dict
) -> dict:  # pragma: no cover - 依赖真实凭据（沙箱无凭证，不进入）
    """真实发送骨架：access_token → subscribe/send。

    未在沙箱验证；生产需 WECHAT_SUBSCRIBE_ENABLED=true + 真实模板 ID。
    """
    import httpx

    settings = get_settings()
    token = await _wechat_access_token(settings)
    body = {
        "touser": openid,
        "template_id": template_id,
        "page": page,
        "miniprogram_state": "formal" if settings.ENV == "prod" else "developer",
        "lang": "zh_CN",
        "data": data,
    }
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.post(
            SUBSCRIBE_SEND_URL, params={"access_token": token}, json=body
        )
        resp.raise_for_status()
        payload = resp.json()
    if payload.get("errcode"):
        raise RuntimeError(f"订阅消息发送失败: {payload.get('errmsg')}")
    return payload
