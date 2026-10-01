"""用户自定义食物（F-02）：food 加 owner_user_id / audit_status 列。

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01

背景：01 文档 §2.4「食物库查不到 → 提示『这是新菜？手动填热量或先跳过』，进入用户自定义
食物（仅本人可见，标记待审核）」。food 表此前无创建者/可见性/审核字段，本迁移只加列：
- owner_user_id：自定义食物创建者；平台食物为 NULL，搜索时按「NULL 或 = 当前用户」过滤，
  保证仅本人可见、不泄露他人自定义食物；
- audit_status：0待审 1通过 2驳回（仅自定义食物有业务含义，新建时写 0）。
与 data/sql/001_schema.sql 同源更新。只加列、可回滚，风格对齐 0003。
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ADD_OWNER_SQL = (
    'ALTER TABLE food ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES "user"(id)'
)
ADD_AUDIT_SQL = (
    "ALTER TABLE food ADD COLUMN IF NOT EXISTS audit_status SMALLINT NOT NULL DEFAULT 0"
)
ADD_AUDIT_CHECK_SQL = (
    "ALTER TABLE food ADD CONSTRAINT food_audit_status_check CHECK (audit_status IN (0, 1, 2))"
)
DROP_AUDIT_CHECK_SQL = "ALTER TABLE food DROP CONSTRAINT IF EXISTS food_audit_status_check"
CREATE_OWNER_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_food_owner ON food(owner_user_id)"
DROP_OWNER_INDEX_SQL = "DROP INDEX IF EXISTS idx_food_owner"
COMMENT_OWNER_SQL = (
    "COMMENT ON COLUMN food.owner_user_id IS "
    "'自定义食物创建者；平台食物为 NULL（仅本人可见，F-02）'"
)
COMMENT_AUDIT_SQL = "COMMENT ON COLUMN food.audit_status IS '审核状态：0待审 1通过 2驳回（F-02）'"


def upgrade() -> None:
    op.execute(ADD_OWNER_SQL)
    op.execute(ADD_AUDIT_SQL)
    op.execute(ADD_AUDIT_CHECK_SQL)
    op.execute(CREATE_OWNER_INDEX_SQL)
    op.execute(COMMENT_OWNER_SQL)
    op.execute(COMMENT_AUDIT_SQL)


def downgrade() -> None:
    op.execute(DROP_AUDIT_CHECK_SQL)
    op.execute(DROP_OWNER_INDEX_SQL)
    op.execute("ALTER TABLE food DROP COLUMN IF EXISTS audit_status")
    op.execute("ALTER TABLE food DROP COLUMN IF EXISTS owner_user_id")
