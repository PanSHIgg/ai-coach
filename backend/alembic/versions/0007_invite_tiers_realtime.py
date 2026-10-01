"""邀请规则新口径（docs/changes/2026-10-01-邀请规则变更记录.md）：invite/user_benefit 列变更。

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-01

口径：注册即有效、实时生效、无期限。本迁移可回滚：
- invite：删 reward_granted（废除发券链路）、加 device_id VARCHAR(64)（同设备
  防刷，nullable + 索引）；status 改为 DEFAULT 1（恒为 1，保留为扩展位）。
  UNIQUE(invitee_id) 与 CHECK(inviter_id <> invitee_id) 已在 0001 建立，
  此处用 DO 块幂等补齐 CHECK（防手工建库缺约束）。
- user_benefit：删 valid_from/valid_to（权益无期限、不回收；coupon/merchant
  等其他表的 valid_from/valid_to 与此无关，不动）。
与 data/sql/001_schema.sql 同源更新。
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
DROP INDEX IF EXISTS idx_invite_device;
ALTER TABLE invite DROP COLUMN IF EXISTS device_id;
ALTER TABLE invite DROP COLUMN IF EXISTS reward_granted;
ALTER TABLE invite ALTER COLUMN status SET DEFAULT 1;
COMMENT ON COLUMN invite.status IS '恒为 1（注册即有效，docs/changes/2026-10-01）；保留为扩展位';
ALTER TABLE invite ADD COLUMN IF NOT EXISTS device_id VARCHAR(64);
CREATE INDEX idx_invite_device ON invite(device_id);
COMMENT ON COLUMN invite.device_id IS '同设备防刷标识：同设备只计 1 次，重复绑定返回 4102';
-- 防自邀请 CHECK（0001 已建，幂等补齐）
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'invite_inviter_id_invitee_id_check'
    ) THEN
        ALTER TABLE invite ADD CONSTRAINT invite_inviter_id_invitee_id_check
        CHECK (inviter_id <> invitee_id);
    END IF;
END $$;
ALTER TABLE user_benefit DROP COLUMN IF EXISTS valid_to;
ALTER TABLE user_benefit DROP COLUMN IF EXISTS valid_from;
COMMENT ON TABLE user_benefit IS '用户权益：AI 次数、权益档位、邀请数（一人一条）；权益无期限不回收';
"""

DOWNGRADE_SQL = r"""
DROP INDEX IF EXISTS idx_invite_device;
ALTER TABLE invite DROP COLUMN IF EXISTS device_id;
ALTER TABLE invite ALTER COLUMN status SET DEFAULT 0;
COMMENT ON COLUMN invite.status IS '0注册 1已建档有效（被邀请人完成1次拍照记录） 2无效（同设备/自邀）';
ALTER TABLE invite ADD COLUMN IF NOT EXISTS reward_granted BOOLEAN DEFAULT FALSE;
ALTER TABLE user_benefit ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;
ALTER TABLE user_benefit ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;
COMMENT ON TABLE user_benefit IS '用户权益：AI 次数、权益档位、邀请数（一人一条）';
"""


def upgrade() -> None:
    """invite 删 reward_granted/加 device_id + CHECK、user_benefit 删有效期列。"""
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    """恢复旧口径列（reward_granted/valid_from/valid_to），device_id 回滚删列。"""
    op.execute(DOWNGRADE_SQL)
