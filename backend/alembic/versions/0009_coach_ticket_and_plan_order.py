"""真人教练工单 + 平台自营付费订阅。

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02

补齐两个 P1 功能缺口的**数据地基**（业务逻辑由后续 agent 填充）：
- G1 真人教练/专家问诊工单：coach / coach_ticket / coach_ticket_message 三张新表；
  行级隔离硬约束落在查询条件 `coach_ticket.coach_id = 当前教练`（越权/未分配 3001），
  教练身份复用 admin_user(role=4) + admin 域 JWT（【假设】首期不做 RBAC，取最简可行）。
- G2 平台自营 AI+真人教练订阅付费：plan_order 新表 + user_benefit 增 valid_to /
  coach_times_left。**不复用 order 表**——order 绑定 merchant_id 与核销语义，平台自营无商家；
  也不复用 /api/subscription 路径（已被「提醒订阅」占用），路径族走 /api/plan。

只加表/加列（additive），downgrade 可逆；与 data/sql/001_schema.sql 同源。
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
-- 0) admin_user.role 放开到 4（教练）：原 CHECK 为 role IN (1,2,3)，会挡住教练账号
ALTER TABLE admin_user DROP CONSTRAINT IF EXISTS admin_user_role_check;
ALTER TABLE admin_user ADD CONSTRAINT admin_user_role_check CHECK (role IN (1, 2, 3, 4));
COMMENT ON TABLE admin_user IS '管理后台账号（ADM1）：账号密码登录；role=4 为真人教练（G1 0009，登录走 /api/coach/login）';

-- 1) user_benefit 增列：付费有效期 + 真人教练次数（G2/G1）
ALTER TABLE user_benefit ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;
ALTER TABLE user_benefit ADD COLUMN IF NOT EXISTS coach_times_left SMALLINT DEFAULT 0;
UPDATE user_benefit SET coach_times_left = 0 WHERE coach_times_left IS NULL;
COMMENT ON COLUMN user_benefit.valid_to IS '付费有效期截止：NULL=不限期/基础档；进阶/高级包月 = paid_at + 30d（G2）';
COMMENT ON COLUMN user_benefit.coach_times_left IS '真人教练剩余次数（提问消耗，G1；耗尽回 4001）';

-- 2) 真人教练名册
CREATE TABLE IF NOT EXISTS coach (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(256),
    name          VARCHAR(64),
    status        SMALLINT DEFAULT 1,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE coach IS '真人健身教练名册（G1）；登录凭据复用 admin_user(role=4)，两者以 username 唯一关联【假设】';
COMMENT ON COLUMN coach.status IS '1在职 0停用';

-- 3) 工单
CREATE TABLE IF NOT EXISTS coach_ticket (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    coach_id   BIGINT REFERENCES coach(id),
    title      VARCHAR(128),
    status     SMALLINT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coach_ticket_user ON coach_ticket(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_coach_ticket_coach ON coach_ticket(coach_id, status);
COMMENT ON TABLE coach_ticket IS '真人教练工单/专家问诊（G1）：coach_id 为空=待分配；教练端查询须带 coach_id 做行级隔离';
COMMENT ON COLUMN coach_ticket.status IS '1待回复 2已回复 3关闭';

-- 4) 工单消息
CREATE TABLE IF NOT EXISTS coach_ticket_message (
    id          BIGSERIAL PRIMARY KEY,
    ticket_id   BIGINT NOT NULL REFERENCES coach_ticket(id) ON DELETE CASCADE,
    sender_role SMALLINT NOT NULL,
    user_id     BIGINT REFERENCES "user"(id),
    coach_id    BIGINT REFERENCES coach(id),
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coach_msg_ticket ON coach_ticket_message(ticket_id, created_at);
COMMENT ON TABLE coach_ticket_message IS '工单对话流水（G1）：sender_role 1用户 2教练';

-- 5) 平台自营会员订阅订单（不复用 order：无 merchant_id/核销语义）
CREATE TABLE IF NOT EXISTS plan_order (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    tier       SMALLINT NOT NULL,
    pay_amount NUMERIC(10, 2) NOT NULL,
    status     SMALLINT DEFAULT 1,
    order_no   VARCHAR(64) UNIQUE NOT NULL,
    expire_at  TIMESTAMPTZ,
    paid_at    TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (pay_amount >= 0)
);
CREATE INDEX IF NOT EXISTS idx_plan_order_user ON plan_order(user_id, created_at DESC);
COMMENT ON TABLE plan_order IS '平台自营会员订阅订单（G2）：金额服务端按 tier 重算，15 分钟未支付过期；付款成功后写 user_benefit';
COMMENT ON COLUMN plan_order.tier IS '档位：1进阶 29 元 2高级 59 元 3终身（价格常量集中管理，见 endpoints/plan.py）';
COMMENT ON COLUMN plan_order.status IS '1待支付 2已支付 3已取消';

-- updated_at 自动维护（函数由 0001 迁移/001_schema.sql 建立，此处幂等重建）
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_coach_ticket_updated_at ON coach_ticket;
CREATE TRIGGER trg_coach_ticket_updated_at BEFORE UPDATE ON coach_ticket
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
"""

DOWNGRADE_SQL = r"""
DROP TRIGGER IF EXISTS trg_coach_ticket_updated_at ON coach_ticket;
DROP INDEX IF EXISTS idx_plan_order_user;
DROP TABLE IF EXISTS plan_order;
DROP INDEX IF EXISTS idx_coach_msg_ticket;
DROP TABLE IF EXISTS coach_ticket_message;
DROP INDEX IF EXISTS idx_coach_ticket_coach;
DROP INDEX IF EXISTS idx_coach_ticket_user;
DROP TABLE IF EXISTS coach_ticket;
DROP TABLE IF EXISTS coach;
ALTER TABLE user_benefit DROP COLUMN IF EXISTS coach_times_left;
ALTER TABLE user_benefit DROP COLUMN IF EXISTS valid_to;
ALTER TABLE admin_user DROP CONSTRAINT IF EXISTS admin_user_role_check;
ALTER TABLE admin_user ADD CONSTRAINT admin_user_role_check CHECK (role IN (1, 2, 3));
COMMENT ON TABLE admin_user IS '管理后台账号（ADM1）：账号密码登录';
"""


def upgrade() -> None:
    """建 G1/G2 数据表 + user_benefit 增列（additive）。"""
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    """删新增四表与新增两列，恢复到 0008 状态。"""
    op.execute(DOWNGRADE_SQL)
