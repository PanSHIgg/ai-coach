"""埋点服务（F3）：批量落库 `track_event`，返回受理条数。

契约：`POST /api/track`（批量上报，openapi.yaml 的 TrackIn / TrackData）。
- 允许匿名：`user_id` 为 None 时按匿名行落库（登录前事件，如扫码进入）。
- `occurred_at` 缺省时不显式赋值，交由列 `server_default=func.now()`（服务端 NOW()）。
- 批量一次提交（避免逐行 commit 的写放大）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TrackEvent
from app.schemas import TrackData, TrackIn


async def record_events(
    session: AsyncSession, user_id: int | None, payload: TrackIn
) -> TrackData:
    """批量写入埋点事件并返回 {"accepted": n}。

    使用 ORM 参数化写入（不拼 SQL）；`occurred_at` 为 None 时不给属性赋值，
    使 INSERT 省略该列从而走数据库 `NOW()` 默认值（显式 None 会写入 NULL 违反非空约束）。
    """
    events: list[TrackEvent] = []
    for ev in payload.events:
        row = TrackEvent(
            event=ev.event,
            user_id=user_id,
            device_id=payload.device_id,
            platform=payload.platform,
            properties=ev.properties,
        )
        if ev.occurred_at is not None:
            row.occurred_at = ev.occurred_at
        events.append(row)

    session.add_all(events)
    await session.commit()
    return TrackData(accepted=len(events))
