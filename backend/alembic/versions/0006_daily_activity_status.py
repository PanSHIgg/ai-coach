"""每日状态选择（F-01）：daily_snapshot 加当日所选活动状态列。

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01

背景：主文档 §2.3.1 :98「每日早晨：首页弹『今天什么状态』（卧床/久坐/轻度/中度/高度
五选一），或用户不点则用默认 PAL」；§6.3.3 :897 NEAT 四层融合第一层「状态选择（粗调）」。
此前仅有建档时静态 body_profile.activity_level，无「每日状态」记录。本迁移只加列、可回滚：
- daily_snapshot.activity_level：当日所选状态 1~5；NULL=未选，读时回退建档 activity_level
  （「不点则用默认 PAL」）。由 app/services/account.py::set_today_status 写入，
  compute_result 读取该列取当日 PAL/NEAT（不改 TEE 结构）。
与 data/sql/001_schema.sql 同源更新。只加列、可回滚，风格对齐 0003~0005。
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

ADD_STATUS_SQL = "ALTER TABLE daily_snapshot ADD COLUMN IF NOT EXISTS activity_level SMALLINT"
ADD_STATUS_CHECK_SQL = (
    "ALTER TABLE daily_snapshot ADD CONSTRAINT daily_snapshot_activity_level_check "
    "CHECK (activity_level IS NULL OR activity_level IN (1, 2, 3, 4, 5))"
)
DROP_STATUS_CHECK_SQL = (
    "ALTER TABLE daily_snapshot DROP CONSTRAINT IF EXISTS daily_snapshot_activity_level_check"
)
COMMENT_STATUS_SQL = (
    "COMMENT ON COLUMN daily_snapshot.activity_level IS "
    "'当日所选状态（1~5）；NULL=未选，回退建档 activity_level（§2.3.1/§6.3.3，F-01）'"
)


def upgrade() -> None:
    op.execute(ADD_STATUS_SQL)
    op.execute(ADD_STATUS_CHECK_SQL)
    op.execute(COMMENT_STATUS_SQL)


def downgrade() -> None:
    op.execute(DROP_STATUS_CHECK_SQL)
    op.execute("ALTER TABLE daily_snapshot DROP COLUMN IF EXISTS activity_level")
