"""商家权重保护/清退（R-01）：merchant 加合作层级与最近贡献时间列。

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01

背景：主文档 §6.3.4 :904「权重分 = 拉新贡献 40% + 券贡献 40% + 过程贡献 20%；
前 20% 战略合作独家区域，前 50% 优选合作保护，连续零贡献清退」——此前仅有 40/40/20
权重分，无「战略合作/优选保护/清退」机制。本迁移只加列、可回滚：
- partner_level：0 普通 / 1 优选合作 / 2 战略合作；由
  app/services/merchant_service.py::evaluate_partner_levels 按权重分排名批量回写（【假设】阈值）；
- last_contribution_at：最近一次贡献（成功核销）时间；连续零贡献清退判定依据，
  由 merchant_service.py::evict_zero_contribution 回填/判定（【假设】口径）。
与 data/sql/001_schema.sql 同源更新。只加列、可回滚，风格对齐 0003/0004。
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

ADD_PARTNER_SQL = (
    "ALTER TABLE merchant ADD COLUMN IF NOT EXISTS partner_level "
    "SMALLINT NOT NULL DEFAULT 0"
)
ADD_PARTNER_CHECK_SQL = (
    "ALTER TABLE merchant ADD CONSTRAINT merchant_partner_level_check "
    "CHECK (partner_level IN (0, 1, 2))"
)
DROP_PARTNER_CHECK_SQL = (
    "ALTER TABLE merchant DROP CONSTRAINT IF EXISTS merchant_partner_level_check"
)
ADD_LAST_CONTRIB_SQL = (
    "ALTER TABLE merchant ADD COLUMN IF NOT EXISTS last_contribution_at TIMESTAMPTZ"
)
COMMENT_PARTNER_SQL = (
    "COMMENT ON COLUMN merchant.partner_level IS "
    "'合作层级：0普通 1优选合作 2战略合作（§6.3.4 权重保护，R-01）'"
)
COMMENT_LAST_CONTRIB_SQL = (
    "COMMENT ON COLUMN merchant.last_contribution_at IS "
    "'最近一次贡献（成功核销）时间；连续零贡献清退判定（R-01）'"
)


def upgrade() -> None:
    op.execute(ADD_PARTNER_SQL)
    op.execute(ADD_PARTNER_CHECK_SQL)
    op.execute(ADD_LAST_CONTRIB_SQL)
    op.execute(COMMENT_PARTNER_SQL)
    op.execute(COMMENT_LAST_CONTRIB_SQL)


def downgrade() -> None:
    op.execute(DROP_PARTNER_CHECK_SQL)
    op.execute("ALTER TABLE merchant DROP COLUMN IF EXISTS last_contribution_at")
    op.execute("ALTER TABLE merchant DROP COLUMN IF EXISTS partner_level")
