"""Phase 5 F5：meal_record 深分页索引（user_id, created_at DESC, id DESC）。

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29

背景：`record_service.list_meals` 按 `created_at DESC, id DESC` 排序，原库仅有
`idx_meal_user_date(user_id, record_date DESC, meal_type)`，深分页（offset≈50w）需对全量
行 external merge sort 落盘，百万行实测 ~920ms。本迁移新增覆盖「过滤列 + 排序键」的索引，
使首页与深页均走 Index Scan（避免排序），与 `data/sql/001_schema.sql` 保持一致。
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

INDEX_NAME = "idx_meal_user_created"
CREATE_INDEX_SQL = (
    f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
    "ON meal_record(user_id, created_at DESC, id DESC)"
)


def upgrade() -> None:
    op.execute(CREATE_INDEX_SQL)


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
