"""约战成员表（battle_participant）。

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-04

补齐约战成员数据地基（BE7b 社区约战）：
- battle_participant：约战成员表，一战一人（(battle_id, user_id) 唯一）；
  发起人建战即写入一行（与 battle.join_count=1 对齐），重复加入/退出以此表为准。

背景：本表被生产代码（create_battle / join_battle / quit_battle / list_battles）、
ORM 模型（backend/app/models/__init__.py 的 BattleParticipant）与
data/sql/001_schema.sql 使用，但 0011 迁移此前从未入库——链上 head 停在 0010，
任何走 `alembic upgrade head` 的存量部署都不会创建该表，上线后约战四个接口
全部 UndefinedTable 500（测试库由 001_schema.sql 直接建表，故全量用例仍绿）。

只加表/索引（additive-only），downgrade 可逆；与 data/sql/001_schema.sql 同源
（约束名 uq_battle_participant 与 ORM UniqueConstraint 同名，
on_conflict_do_nothing(constraint=...) 依赖它命中）。
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# 与 data/sql/001_schema.sql 中 battle_participant 定义逐字同源。
# 幂等（IF NOT EXISTS）：测试库/部署库可能已由 001_schema.sql 建过同名同构表。
UPGRADE_SQL = r"""
-- =============================================================================
-- 11. 约战成员表（0011 迁移，additive-only；与 001_schema.sql 同源）
-- =============================================================================

-- 约战成员（一人一位：重复加入/退出以此表为准；发起人建战即写一行）
CREATE TABLE IF NOT EXISTS battle_participant (
    id         BIGSERIAL PRIMARY KEY,
    battle_id  BIGINT NOT NULL REFERENCES battle(id),
    user_id    BIGINT NOT NULL REFERENCES "user"(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_battle_participant UNIQUE (battle_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_battle_participant_user ON battle_participant(user_id);
COMMENT ON TABLE battle_participant IS '约战成员：一人一位，防重复加入/支持退出（0011）';
"""

DOWNGRADE_SQL = r"""
DROP INDEX IF EXISTS idx_battle_participant_user;
DROP TABLE IF EXISTS battle_participant;
"""


def upgrade() -> None:
    """建约战成员表与其唯一约束/索引（additive）。"""
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    """删除 battle_participant 表与索引，恢复到 0010 状态。"""
    op.execute(DOWNGRADE_SQL)
