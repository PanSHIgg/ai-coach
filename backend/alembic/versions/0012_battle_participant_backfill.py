"""约战成员回填（battle_participant 历史发起人行）。

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04

0011 之前发起的约战只有 join_count>0、没有发起人成员行。而约战的「谁在场上」自本次起
完全以成员表判定（list_battles 的 joined、join/quit 的重复判定都不再看 creator_id），
这类旧数据会显示为「未加入」，发起人再加入即重复占位、人数越加越虚。

回填口径：join_count>0 且缺发起人行的约战补一行——发起人退出后 join_count 归 0
（quit_battle 自减），不会被误回填，退出后仍能正常再加入；0011 起 create_battle 已同步
写行，新数据不受影响。只补数据、不动表结构（additive-only）。
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
INSERT INTO battle_participant (battle_id, user_id)
SELECT b.id, b.creator_id
FROM battle b
WHERE b.creator_id IS NOT NULL
  AND b.join_count > 0
  AND NOT EXISTS (
      SELECT 1 FROM battle_participant p
      WHERE p.battle_id = b.id AND p.user_id = b.creator_id
  );
"""


def upgrade() -> None:
    """为 0011 前的历史约战补发起人成员行（NOT EXISTS 守卫，可重复执行）。"""
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    """无操作：回填行与正常加入行同构，无法区分，回滚不删数据。"""
