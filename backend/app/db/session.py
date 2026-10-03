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

    Phase 5（F5）：默认改用**异步连接池**（SQLAlchemy 默认 AsyncAdaptedQueuePool），
    避免每请求新建 asyncpg 连接导致高并发下延迟劣化（本机百万行压测实测根因）。
    `DB_POOL_DISABLED=True` 时回退 NullPool —— 供「多事件循环复用同一 engine」的场景
    （pytest 的函数级 loop）使用；测试侧 `conftest.db_engine` 自建引擎，不受此处影响。
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"pool_pre_ping": True}
        if settings.DB_POOL_DISABLED:
            kwargs["poolclass"] = NullPool
        else:
            kwargs.update(
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_POOL_MAX_OVERFLOW,
                pool_recycle=settings.DB_POOL_RECYCLE,
            )
        _engine = create_async_engine(settings.DATABASE_URL, **kwargs)
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
