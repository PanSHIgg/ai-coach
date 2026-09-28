"""异步数据库会话（惰性建引擎，导入即用、连接延迟到首次请求）。"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """进程级单例引擎。

    【假设】使用 NullPool：asyncpg 连接绑定事件循环，而 pytest 每个用例独立 loop、
    复用连接池会报「attached to a different loop」；NullPool 即用即关，跨 loop 安全。
    生产如需连接池，可在此改回默认池并保证单 loop 运行。
    """
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().DATABASE_URL, pool_pre_ping=True, poolclass=NullPool
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每请求一个会话，用完即关。"""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """应用关闭时释放连接池（可选调用）。"""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
