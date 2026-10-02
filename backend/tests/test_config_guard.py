"""配置守卫：生产环境（ENV=prod）不得沿用默认密钥 + 连接池配置回归。

文档依据：主文档 §13.4「生产密钥走服务器环境变量」。
用 parametrize 覆盖同一行为的边界：prod 下任一密钥为默认即拒绝；
非 prod 或 prod 下均已自定义则放行。

连接池守卫（原 `tests/test_db_pool.py`，Phase 5 F5）：默认启用异步池且池容量 > 0，
`DB_POOL_DISABLED=False` 时 `get_engine()` 返回真实异步池（非 NullPool）。

⚠️ app 引擎是进程级单例，pytest 每个用例独立事件循环：带池引擎若在用例内建连即绑定
当前 loop，后续用例复用会报「attached to a different loop」。故池用例只建池后立即
`dispose()` 并复位 `_engine`/`_sessionmaker`（不建立连接），不做任何查询。
"""

import pytest
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.main import create_app
from tests.conftest import DB_URL, make_settings

# 默认密钥取自定义真源（config.py 字段默认值），避免在用例里重复硬编码。
_DEFAULT_JWT_SECRET = Settings.model_fields["JWT_SECRET"].default
_DEFAULT_ADMIN_PASSWORD = Settings.model_fields["ADMIN_INIT_PASSWORD"].default


def _settings(**overrides) -> Settings:
    base = {
        "JWT_SECRET": _DEFAULT_JWT_SECRET,
        "ADMIN_INIT_PASSWORD": _DEFAULT_ADMIN_PASSWORD,
    }
    base.update(overrides)
    return make_settings(**base)


@pytest.mark.parametrize(
    "overrides",
    [
        {"ENV": "prod"},  # 两把密钥皆为默认
        {"ENV": "prod", "ADMIN_INIT_PASSWORD": "custom-strong-pwd"},  # 仅 JWT_SECRET 默认
        {"ENV": "prod", "JWT_SECRET": "custom-strong-secret"},  # 仅 ADMIN_INIT_PASSWORD 默认
    ],
)
def test_prod_rejects_default_secrets(overrides: dict) -> None:
    with pytest.raises(RuntimeError):
        create_app(_settings(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"ENV": "dev"},  # 非生产：默认密钥行为不变
        {"ENV": "sandbox"},
        {
            "ENV": "prod",
            "JWT_SECRET": "custom-strong-secret",
            "ADMIN_INIT_PASSWORD": "custom-strong-pwd",
        },  # 生产且已自定义：放行
    ],
)
def test_non_prod_or_custom_secrets_allowed(overrides: dict) -> None:
    app = create_app(_settings(**overrides))
    assert app is not None


async def test_db_pool_config_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """连接池配置守卫：默认启用池（容量 > 0），且该配置下 get_engine() 用真实异步池。

    conftest 为 pytest 跨 loop 场景注入了 DB_POOL_DISABLED=true，故先剔除该环境变量，
    以断言 Settings 的类默认值（而非被测试环境覆盖后的运行值）。
    """
    monkeypatch.delenv("DB_POOL_DISABLED", raising=False)
    settings = Settings(_env_file=None)
    assert settings.DB_POOL_DISABLED is False
    assert settings.DB_POOL_SIZE > 0

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
