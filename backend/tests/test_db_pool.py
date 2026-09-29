"""Phase 5 F5：连接池配置回归（轻量，避免跨事件循环污染）。

- ① Settings 默认启用异步连接池（DB_POOL_DISABLED=False 且 DB_POOL_SIZE>0）；
- ② DB_POOL_DISABLED=False 时 get_engine() 返回异步池（非 NullPool）。

⚠️ app 引擎是进程级单例，pytest 每个用例独立事件循环：带池引擎若在用例内建连即绑定当前 loop，
后续用例复用会报「attached to a different loop」。故 ② 只在建池后立即 `dispose()` 并复位
`_engine`/`_sessionmaker`（避免连接建立），不做任何查询。
"""

from sqlalchemy.pool import NullPool

from app.core.config import Settings
from tests.conftest import DB_URL


def test_settings_default_pool_config(monkeypatch):
    """默认配置：启用连接池且池容量 > 0。

    conftest 为 pytest 跨 loop 场景注入了 DB_POOL_DISABLED=true，故先剔除该环境变量，
    以断言 Settings 的类默认值（而非被测试环境覆盖后的运行值）。
    """
    monkeypatch.delenv("DB_POOL_DISABLED", raising=False)
    settings = Settings(_env_file=None)
    assert settings.DB_POOL_DISABLED is False
    assert settings.DB_POOL_SIZE > 0


async def test_get_engine_uses_async_pool(monkeypatch):
    """DB_POOL_DISABLED=False 时 get_engine() 返回异步连接池（非 NullPool）。"""
    import app.db.session as session_mod

    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_sessionmaker", None)
    monkeypatch.setattr(
        session_mod,
        "get_settings",
        lambda: Settings(_env_file=None, DATABASE_URL=DB_URL, DB_POOL_DISABLED=False),
    )

    engine = session_mod.get_engine()
    try:
        assert not isinstance(engine.pool, NullPool)
    finally:
        await engine.dispose()
        session_mod._engine = None
        session_mod._sessionmaker = None
