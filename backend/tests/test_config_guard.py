"""FA-1 配置守卫：生产环境（ENV=prod）不得沿用默认密钥。

文档依据：主文档 §13.4「生产密钥走服务器环境变量」。
用 parametrize 覆盖同一行为的边界：prod 下任一密钥为默认即拒绝；
非 prod 或 prod 下均已自定义则放行。
"""

import pytest

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_settings

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
