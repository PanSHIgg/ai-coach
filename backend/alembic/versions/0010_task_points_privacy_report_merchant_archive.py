"""我的页 5 模块 + 商家自助后台 + 记录按月归档 + 中文检索。

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-02

补齐我的页/商家后台/归档/中文检索的数据地基（业务逻辑由后续 agent 填充）：
- G3 我的页 5 模块：user_points / points_log / daily_checkin / user_task /
  user_privacy / exclusive_offer（专属优惠·异业联盟券目录）/ report_export；
- G11 商家自助后台：merchant_account；
- G8 记录按月分区归档（文档 §7.4「2 年记录按月分区归档」）：为既有记录表各建
  一张归档表（列与源表逐列对应，去除主键序列，新增 archived_at），
  PARTITION BY RANGE (created_at) 并预建 2024-01~2024-06 示例月分区；
- G10 中文检索：pg_trgm 扩展 + food.name / food_alias.alias 的 GIN 三元组索引。

只加表/索引/扩展（additive-only），downgrade 可逆；与 data/sql/001_schema.sql 同源。
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# G8 归档表：源表 -> 归档表名。列与源表逐列对应（去主键序列，加 archived_at）。
# 说明：actual 源表名为 step_record（非 steps_record），track_event 表名与实际一致。
_ARCHIVE_TABLES = (
    "meal_record_archive",
    "sport_record_archive",
    "weight_record_archive",
    "step_record_archive",
    "daily_snapshot_archive",
    "track_event_archive",
    "ai_dialog_archive",
)

# 示例月分区（证明按月分区可建）
_ARCHIVE_MONTHS = ("2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06")


def _partition_sql(table: str) -> str:
    """为归档父表生成示例月分区 DDL（左闭右开）。"""
    lines = []
    for m in _ARCHIVE_MONTHS:
        y, mo = m.split("-")
        start = f"{m}-01"
        if mo == "12":
            end = f"{int(y) + 1:04d}-01-01"
        else:
            end = f"{y}-{int(mo) + 1:02d}-01"
        part = f"{table}_{y}_{mo}"
        lines.append(
            f"CREATE TABLE IF NOT EXISTS {part} PARTITION OF {table} "
            f"FOR VALUES FROM ('{start}') TO ('{end}');"
        )
    return "\n".join(lines)


UPGRADE_SQL = r"""
-- =============================================================================
-- 10. 缺口数据地基（0010 迁移，additive-only）
-- =============================================================================

-- G10 中文检索：三元组模糊匹配（与 0001 / 001_schema.sql 幂等）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- 10.1 G3 我的页 5 模块
-- -----------------------------------------------------------------------------

-- 用户积分账户（一人一条）
CREATE TABLE IF NOT EXISTS user_points (
    user_id      BIGINT PRIMARY KEY REFERENCES "user"(id) ON DELETE CASCADE,
    balance      INTEGER NOT NULL DEFAULT 0,
    total_earned INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE user_points IS '用户积分账户：余额 + 累计获得（我的页 G3，一人一条）';
COMMENT ON COLUMN user_points.balance IS '当前可用积分余额';
COMMENT ON COLUMN user_points.total_earned IS '累计获得积分（只增不减口径）';

-- 积分流水
CREATE TABLE IF NOT EXISTS points_log (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    change     INTEGER NOT NULL,
    reason     VARCHAR(64) NOT NULL,
    ref        VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_points_log_user ON points_log(user_id, created_at DESC);
COMMENT ON TABLE points_log IS '积分流水：change 正负皆可，reason 变更原因，ref 关联业务单号';
COMMENT ON COLUMN points_log.change IS '积分变动值（正为获得，负为消耗）';

-- 每日签到
CREATE TABLE IF NOT EXISTS daily_checkin (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    checkin_date DATE NOT NULL,
    points       INTEGER NOT NULL DEFAULT 5,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, checkin_date)
);
COMMENT ON TABLE daily_checkin IS '每日签到：(user_id, checkin_date) 唯一，一人一天一次';

-- 用户任务进度
CREATE TABLE IF NOT EXISTS user_task (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    task_code     VARCHAR(32) NOT NULL,
    status        SMALLINT NOT NULL DEFAULT 0,
    progress      INTEGER NOT NULL DEFAULT 0,
    reward_points INTEGER NOT NULL DEFAULT 0,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, task_code)
);
COMMENT ON TABLE user_task IS '用户任务进度：(user_id, task_code) 唯一';
COMMENT ON COLUMN user_task.status IS '状态：0未完成 1已完成 2已领奖';

-- 用户隐私设置（一人一条）
CREATE TABLE IF NOT EXISTS user_privacy (
    user_id              BIGINT PRIMARY KEY REFERENCES "user"(id) ON DELETE CASCADE,
    anonymous            BOOLEAN NOT NULL DEFAULT TRUE,
    mask_share           BOOLEAN NOT NULL DEFAULT TRUE,
    visibility_leaderboard SMALLINT NOT NULL DEFAULT 1,
    visibility_community   SMALLINT NOT NULL DEFAULT 1,
    allow_data_export      BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE user_privacy IS '用户隐私设置：匿名/脱敏分享/榜单与社区可见性/数据导出（G3，一人一条）';
COMMENT ON COLUMN user_privacy.visibility_leaderboard IS '榜单可见性：1公开 0隐藏';
COMMENT ON COLUMN user_privacy.visibility_community IS '社区可见性：1公开 0隐藏';

-- 专属优惠（异业联盟券目录）
CREATE TABLE IF NOT EXISTS exclusive_offer (
    id            BIGSERIAL PRIMARY KEY,
    title         VARCHAR(128) NOT NULL,
    category      VARCHAR(32),
    partner       VARCHAR(64),
    description   TEXT,
    coupon_amount NUMERIC(10, 2) NOT NULL DEFAULT 0,
    stock         INTEGER NOT NULL DEFAULT 0,
    status        SMALLINT NOT NULL DEFAULT 1,
    valid_to      TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE exclusive_offer IS '专属优惠·异业联盟券目录（G3）：平台维护的合作方券';
COMMENT ON COLUMN exclusive_offer.status IS '1上架 0下架';

-- 报告导出记录
CREATE TABLE IF NOT EXISTS report_export (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    report_type VARCHAR(16) NOT NULL,
    format      VARCHAR(8) NOT NULL,
    filename    VARCHAR(128) NOT NULL,
    content     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_report_export_user ON report_export(user_id, created_at DESC);
COMMENT ON TABLE report_export IS '报告导出记录（G3）：生成的文件可下载，含过期时间';

-- -----------------------------------------------------------------------------
-- 10.2 G11 商家自助后台账号
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS merchant_account (
    id            BIGSERIAL PRIMARY KEY,
    merchant_id   BIGINT NOT NULL REFERENCES merchant(id) ON DELETE CASCADE,
    username      VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(128) NOT NULL,
    phone         VARCHAR(32),
    status        SMALLINT NOT NULL DEFAULT 1,
    last_login_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_merchant_account_merchant ON merchant_account(merchant_id);
COMMENT ON TABLE merchant_account IS '商家自助后台账号（G11）：商家自助管理，username 唯一';
COMMENT ON COLUMN merchant_account.status IS '1启用 0停用';

-- -----------------------------------------------------------------------------
-- 10.3 G8 记录按月分区归档（文档 §7.4：2 年记录按月分区归档）
--   归档表列与源表逐列对应：去除主键序列/默认，created_at 提为 NOT NULL（分区键，入 PK），
--   追加 archived_at；主键 = (id, created_at)（分区表主键必须含分区键）。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meal_record_archive (
    id                 BIGINT NOT NULL,
    user_id            BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    record_date        DATE NOT NULL,
    meal_type          SMALLINT NOT NULL,
    food_id            BIGINT REFERENCES food(id),
    food_name_snapshot VARCHAR(128),
    amount_g           NUMERIC(7, 1) NOT NULL,
    calories           NUMERIC(8, 1) NOT NULL,
    protein            NUMERIC(7, 2),
    fat                NUMERIC(7, 2),
    carb               NUMERIC(7, 2),
    confidence         NUMERIC(4, 2),
    source             SMALLINT DEFAULT 1,
    image_url          TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at        TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE meal_record_archive IS '饮食记录归档（G8）：源 meal_record，按月分区，超 2 年冷数据';
COMMENT ON COLUMN meal_record_archive.archived_at IS '归档写入时间';

CREATE TABLE IF NOT EXISTS sport_record_archive (
    id           BIGINT NOT NULL,
    user_id      BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    sport_name   VARCHAR(128),
    met          NUMERIC(4, 2),
    duration_min INTEGER NOT NULL,
    calories     NUMERIC(8, 1) NOT NULL,
    source       SMALLINT DEFAULT 1,
    record_at    TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE sport_record_archive IS '运动记录归档（G8）：源 sport_record，按月分区';

CREATE TABLE IF NOT EXISTS weight_record_archive (
    id          BIGINT NOT NULL,
    user_id     BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    weight      NUMERIC(5, 1) NOT NULL,
    record_at   DATE NOT NULL,
    source      SMALLINT DEFAULT 1,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE weight_record_archive IS '体重记录归档（G8）：源 weight_record，按月分区';

CREATE TABLE IF NOT EXISTS step_record_archive (
    id             BIGINT NOT NULL,
    user_id        BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    record_date    DATE NOT NULL,
    steps          INTEGER NOT NULL,
    source         SMALLINT DEFAULT 1,
    hourly_json    JSONB DEFAULT '{}'::jsonb,
    calibrated_met NUMERIC(4, 2),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE step_record_archive IS '步数记录归档（G8）：源 step_record（源表实际名为 step_record，非 steps_record），按月分区';

CREATE TABLE IF NOT EXISTS daily_snapshot_archive (
    id               BIGINT NOT NULL,
    user_id          BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    snapshot_date    DATE NOT NULL,
    bmr              NUMERIC(7, 1),
    pal              NUMERIC(3, 2),
    neat             NUMERIC(7, 1),
    eat              NUMERIC(7, 1),
    tef              NUMERIC(7, 1),
    tee              NUMERIC(7, 1),
    intake           NUMERIC(7, 1) DEFAULT 0,
    deficit          NUMERIC(8, 1) DEFAULT 0,
    steps            INTEGER DEFAULT 0,
    calories_burnt   NUMERIC(8, 1) DEFAULT 0,
    calibration_used BOOLEAN DEFAULT FALSE,
    activity_level   SMALLINT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE daily_snapshot_archive IS '每日热量快照归档（G8）：源 daily_snapshot，按月分区';

CREATE TABLE IF NOT EXISTS track_event_archive (
    id          BIGINT NOT NULL,
    event       VARCHAR(64) NOT NULL,
    user_id     BIGINT,
    device_id   VARCHAR(64),
    platform    SMALLINT DEFAULT 1,
    properties  JSONB DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE track_event_archive IS '埋点事件归档（G8）：源 track_event，按月分区';

CREATE TABLE IF NOT EXISTS ai_dialog_archive (
    id          BIGINT NOT NULL,
    user_id     BIGINT REFERENCES "user"(id),
    session_id  UUID DEFAULT uuid_generate_v4(),
    role        VARCHAR(16) NOT NULL,
    content     TEXT NOT NULL,
    intent      VARCHAR(64),
    tokens      INTEGER,
    model       VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE ai_dialog_archive IS 'AI 对话流水归档（G8）：源 ai_dialog，按月分区（§7.4 超 2 年归档）';

-- 示例月分区（2024-01 ~ 2024-06）
__ARCHIVE_PARTITIONS__

-- -----------------------------------------------------------------------------
-- 10.4 G10 中文检索：GIN 三元组索引（food.name / food_alias.alias）
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_food_name_trgm ON food USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_food_alias_trgm ON food_alias USING gin (alias gin_trgm_ops);
COMMENT ON INDEX idx_food_name_trgm IS '中文模糊检索：food.name 三元组 GIN（G10）';
COMMENT ON INDEX idx_food_alias_trgm IS '中文模糊检索：food_alias.alias 三元组 GIN（G10）';

-- updated_at 自动维护（函数由 0001 迁移/001_schema.sql 建立，此处幂等重建）
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_user_points_updated_at ON user_points;
CREATE TRIGGER trg_user_points_updated_at BEFORE UPDATE ON user_points
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_user_privacy_updated_at ON user_privacy;
CREATE TRIGGER trg_user_privacy_updated_at BEFORE UPDATE ON user_privacy
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
"""

# 拼接示例月分区 DDL
UPGRADE_SQL = UPGRADE_SQL.replace(
    "__ARCHIVE_PARTITIONS__",
    "\n".join(_partition_sql(t) for t in _ARCHIVE_TABLES),
)

DOWNGRADE_SQL = r"""
-- 10.4 中文检索索引（pg_trgm 扩展保留：0001 已建，非本迁移引入）
DROP INDEX IF EXISTS idx_food_alias_trgm;
DROP INDEX IF EXISTS idx_food_name_trgm;

-- 10.3 归档表（DROP 父表自动级联删除各分区）
DROP TABLE IF EXISTS ai_dialog_archive CASCADE;
DROP TABLE IF EXISTS track_event_archive CASCADE;
DROP TABLE IF EXISTS daily_snapshot_archive CASCADE;
DROP TABLE IF EXISTS step_record_archive CASCADE;
DROP TABLE IF EXISTS weight_record_archive CASCADE;
DROP TABLE IF EXISTS sport_record_archive CASCADE;
DROP TABLE IF EXISTS meal_record_archive CASCADE;

-- 10.1/10.2 新增业务表
DROP TRIGGER IF EXISTS trg_user_privacy_updated_at ON user_privacy;
DROP TRIGGER IF EXISTS trg_user_points_updated_at ON user_points;
DROP INDEX IF EXISTS idx_merchant_account_merchant;
DROP TABLE IF EXISTS merchant_account;
DROP INDEX IF EXISTS idx_report_export_user;
DROP TABLE IF EXISTS report_export;
DROP TABLE IF EXISTS exclusive_offer;
DROP TABLE IF EXISTS user_privacy;
DROP TABLE IF EXISTS user_task;
DROP TABLE IF EXISTS daily_checkin;
DROP INDEX IF EXISTS idx_points_log_user;
DROP TABLE IF EXISTS points_log;
DROP TABLE IF EXISTS user_points;
"""


def upgrade() -> None:
    """建 G3/G8/G10/G11 数据表、归档分区表与 GIN 三元组索引（additive）。"""
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    """删除本迁移新增的表/索引/触发器，恢复到 0009 状态。"""
    op.execute(DOWNGRADE_SQL)