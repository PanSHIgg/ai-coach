"""核销后三件套：merchant 加贡献分列 + meal_record.source 枚举扩展（01 文档 §2.3.2）。

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30

背景：核销闭环补齐（01 文档 §2.3.2「订单完成 → 商家获贡献分 + 摄入记录自动写入 +
生成社区经验卡」）。
- merchant.contribution_points：04 文档 §7.2 merchant 表结构暂无此列（本次不改文档，
  改动点由主 Agent 同步 Docs 侧）；代码按最简可行加列，每成功核销一单 +1
  （app/services/redeem_aftercare.py::CONTRIBUTION_PER_REDEEM）。
- meal_record.source：需标记「5=订单核销自动写入」，但 001_schema.sql（实现级，
  文档 04 无）有 CHECK (source IN (1,2,3,4))，故同迁移放宽为 (1,2,3,4,5)。
与 data/sql/001_schema.sql 同源更新。
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ADD_COLUMN_SQL = (
    "ALTER TABLE merchant ADD COLUMN IF NOT EXISTS contribution_points "
    "INTEGER NOT NULL DEFAULT 0"
)
COMMENT_SQL = (
    "COMMENT ON COLUMN merchant.contribution_points IS "
    "'贡献分：核销成功累计（每单 +1）'"
)
# 放宽 source 枚举：5 = 订单核销自动写入（先 DROP 再 ADD，约束名保持不变）
DROP_SOURCE_CHECK_SQL = "ALTER TABLE meal_record DROP CONSTRAINT IF EXISTS meal_record_source_check"
ADD_SOURCE_CHECK_SQL = (
    "ALTER TABLE meal_record ADD CONSTRAINT meal_record_source_check "
    "CHECK (source IN (1, 2, 3, 4, 5))"
)


def upgrade() -> None:
    op.execute(ADD_COLUMN_SQL)
    op.execute(COMMENT_SQL)
    op.execute(DROP_SOURCE_CHECK_SQL)
    op.execute(ADD_SOURCE_CHECK_SQL)


def downgrade() -> None:
    op.execute(DROP_SOURCE_CHECK_SQL)
    op.execute(
        "ALTER TABLE meal_record ADD CONSTRAINT meal_record_source_check "
        "CHECK (source IN (1, 2, 3, 4))"
    )
    op.execute("ALTER TABLE merchant DROP COLUMN IF EXISTS contribution_points")
