"""Alembic 迁移环境（P0-c）。

- 同步 engine（SQLAlchemy create_engine）
- offline / online 两种模式
- 连接 URL 只从环境变量 ALEMBIC_DATABASE_URL 读取（alembic.ini 中留空）
- target_metadata=None：初始迁移以内嵌 SQL 全文执行，不依赖 ORM 元数据
"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _get_url() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "环境变量 ALEMBIC_DATABASE_URL 未设置。"
            "示例：postgresql+psycopg2://user:pass@localhost:5432/ai_coach"
        )
    return url


def run_migrations_offline() -> None:
    """offline 模式：只生成 SQL 脚本，不连库。"""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """online 模式：连接数据库执行迁移。"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
