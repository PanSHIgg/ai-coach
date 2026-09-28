-- =============================================================================
-- AI 饮食管控教练 · P0-c 初始建表 SQL（PostgreSQL 16）
-- 真源：docs/split/04-后端技术架构与数据库.md 第七部分（§7.1 表清单 + §7.2 建表 SQL）
-- 原则：只加列（additive-only），保证 Alembic 迁移可回滚；P1 预留字段一律不建
-- 约定（docs/split/10 零提问默认决策规则 §13.1）：
--   金额=元 NUMERIC(10,2)；克重 NUMERIC(7,1)；热量 NUMERIC(8,1)；
--   时间 TIMESTAMPTZ；多状态用 SMALLINT；动态结构用 JSONB
-- 默认决策：
--   1.【假设】不启用 PostGIS，商家经纬度存 lat/lng NUMERIC（§7.2 注释允许）
--   2.【假设】ai_knowledge.embedding 用 JSONB 占位（plan.md 决策 3：首期不引 pgvector），
--     另加全文检索列 search_vec 兜底
--   3.【假设】§7.1 列出但 §7.2 未给 DDL 的 user_auth/coupon_pool/order_item/review，
--     以及任务指定的 订阅/社区评论/点赞/热量控制榜/埋点事件，按最简结构补齐
--   4.【假设】tsvector 用 GENERATED ALWAYS ... STORED 生成列（§7.2 原文写法），
--     updated_at 用触发器自动维护
-- =============================================================================

-- 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- updated_at 自动维护函数
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- 1. 用户域
-- -----------------------------------------------------------------------------

-- 用户
CREATE TABLE "user" (
    id          BIGSERIAL PRIMARY KEY,
    openid      VARCHAR(64) UNIQUE,
    unionid     VARCHAR(64),
    phone_hash  VARCHAR(128),                     -- 手机号哈希（隐私：不存原文）
    nickname    VARCHAR(64),
    avatar_url  TEXT,
    gender      SMALLINT DEFAULT 0,               -- 0未知 1男 2女
    status      SMALLINT DEFAULT 1,               -- 1正常 0禁用
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    CHECK (gender IN (0, 1, 2)),
    CHECK (status IN (0, 1))
);
CREATE INDEX idx_user_created ON "user"(created_at);
COMMENT ON TABLE "user" IS '用户主表：openid 唯一，手机号只存哈希（§7.2）';
COMMENT ON COLUMN "user".gender IS '性别：0未知 1男 2女';
COMMENT ON COLUMN "user".status IS '账号状态：1正常 0禁用';

-- 第三方登录身份（§7.1 清单列出，按最简结构补齐【假设】）
CREATE TABLE user_auth (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    provider   VARCHAR(32) NOT NULL,              -- wechat_mp / wechat_h5 / phone
    openid     VARCHAR(64) NOT NULL,
    unionid    VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (provider, openid)
);
CREATE INDEX idx_auth_user ON user_auth(user_id);
COMMENT ON TABLE user_auth IS '第三方登录身份：一个用户可绑定多个 provider，(provider, openid) 唯一';
COMMENT ON COLUMN user_auth.provider IS '登录渠道：wechat_mp 小程序 / wechat_h5 网页 / phone 手机号';

-- 用户权益（§7.2）
CREATE TABLE user_benefit (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT UNIQUE REFERENCES "user"(id),
    tier              SMALLINT DEFAULT 0,         -- 0基础 1进阶 2高级 3终身
    ai_times_left     INTEGER DEFAULT 10,         -- AI 对话剩余次数
    ai_times_reset_at TIMESTAMPTZ,                -- 次数重置时间
    valid_from        TIMESTAMPTZ,
    valid_to          TIMESTAMPTZ,
    invite_count      INTEGER DEFAULT 0,          -- 有效邀请数
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    CHECK (ai_times_left >= 0)
);
COMMENT ON TABLE user_benefit IS '用户权益：AI 次数、权益档位、邀请数（一人一条）';
COMMENT ON COLUMN user_benefit.tier IS '权益档位：0基础 1进阶 2高级 3终身';
COMMENT ON COLUMN user_benefit.ai_times_left IS 'AI 对话剩余次数，用尽提示邀请好友解锁（BE4b）';

-- 邀请关系（§7.2）
CREATE TABLE invite (
    id             BIGSERIAL PRIMARY KEY,
    inviter_id     BIGINT REFERENCES "user"(id),
    invitee_id     BIGINT UNIQUE REFERENCES "user"(id),
    status         SMALLINT DEFAULT 0,            -- 0注册 1已建档(有效) 2无效
    reward_granted BOOLEAN DEFAULT FALSE,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    CHECK (inviter_id <> invitee_id)
);
CREATE INDEX idx_invite_inviter ON invite(inviter_id);
COMMENT ON TABLE invite IS '邀请关系：invitee_id 唯一，一人只能被邀请一次（§7.3）';
COMMENT ON COLUMN invite.status IS '0注册 1已建档有效（被邀请人完成1次拍照记录） 2无效（同设备/自邀）';

-- -----------------------------------------------------------------------------
-- 2. 身体档案与记录域
-- -----------------------------------------------------------------------------

-- 身体档案（§7.2）
CREATE TABLE body_profile (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT UNIQUE REFERENCES "user"(id) ON DELETE CASCADE,
    gender         SMALLINT NOT NULL,             -- 1男 2女
    height_cm      NUMERIC(5,1) NOT NULL,         -- 身高
    birth_year     SMALLINT,
    age            SMALLINT,
    current_weight NUMERIC(5,1),                  -- 当前体重 kg
    target_weight  NUMERIC(5,1),                  -- 目标体重 kg
    target_type    SMALLINT DEFAULT 1,            -- 1减脂 2增肌 3维持
    activity_level SMALLINT DEFAULT 2,            -- 1卧床 2久坐 3轻度 4中度 5高度
    bmr            NUMERIC(7,1),                  -- 基础代谢
    target_calories INTEGER,                      -- 每日热量预算
    goal_pace      SMALLINT DEFAULT 1,            -- 每周目标 kg
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    CHECK (gender IN (1, 2)),
    CHECK (height_cm > 0),
    CHECK (target_type IN (1, 2, 3)),
    CHECK (activity_level BETWEEN 1 AND 5)
);
CREATE INDEX idx_body_user ON body_profile(user_id);
COMMENT ON TABLE body_profile IS '身体档案：一人一条，建档后首页热量账户以 BMR×PAL 为预算（BE1/BE2）';
COMMENT ON COLUMN body_profile.activity_level IS '活动水平：1卧床 2久坐(默认,PAL1.4) 3轻度 4中度 5高度';
COMMENT ON COLUMN body_profile.target_type IS '目标：1减脂(默认) 2增肌 3维持';
COMMENT ON COLUMN body_profile.bmr IS '基础代谢 Mifflin-St Jeor，服务端计算写入';

-- 体重记录（§7.2）
CREATE TABLE weight_record (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    weight     NUMERIC(5,1) NOT NULL,
    record_at  DATE NOT NULL,
    source     SMALLINT DEFAULT 1,                -- 1手动 2智能秤
    note       TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (weight > 0)
);
CREATE INDEX idx_weight_user_date ON weight_record(user_id, record_at DESC);
COMMENT ON TABLE weight_record IS '体重记录：趋势图数据源（BE-w）';

-- 食物库（§7.2）
CREATE TABLE food (
    id            BIGSERIAL PRIMARY KEY,
    name          VARCHAR(128) NOT NULL,
    category      VARCHAR(64),
    calories_100g NUMERIC(7,1) NOT NULL,          -- 每100g热量 kcal
    protein_100g  NUMERIC(6,2),
    fat_100g      NUMERIC(6,2),
    carb_100g     NUMERIC(6,2),
    gi            SMALLINT,                       -- 血糖生成指数
    is_standard   BOOLEAN DEFAULT FALSE,          -- 是否标准减脂餐
    status        SMALLINT DEFAULT 1,             -- 1启用 0停用
    search_vec    tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(name, ''))) STORED,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    CHECK (calories_100g >= 0),
    CHECK (gi IS NULL OR (gi BETWEEN 0 AND 100)),
    CHECK (status IN (0, 1))
);
CREATE INDEX idx_food_name ON food USING gin(search_vec);
CREATE INDEX idx_food_category ON food(category);
COMMENT ON TABLE food IS '食物库：正式数据 DATA1（W3 交付，1700+ 条）；搜索走 tsvector + food_alias';
COMMENT ON COLUMN food.search_vec IS '全文检索列：to_tsvector(simple, name)，生成列自动维护';

-- 食物别名（§7.2）
CREATE TABLE food_alias (
    id      BIGSERIAL PRIMARY KEY,
    food_id BIGINT REFERENCES food(id) ON DELETE CASCADE,
    alias   VARCHAR(128) NOT NULL UNIQUE
);
COMMENT ON TABLE food_alias IS '食物别名：提升拍照识别与搜索匹配率';

-- 饮食记录（§7.2）
CREATE TABLE meal_record (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    record_date        DATE NOT NULL,
    meal_type          SMALLINT NOT NULL,         -- 1早餐 2午餐 3晚餐 4加餐
    food_id            BIGINT REFERENCES food(id),
    food_name_snapshot VARCHAR(128),              -- 快照，防食物库变更
    amount_g           NUMERIC(7,1) NOT NULL,     -- 分量克
    calories           NUMERIC(8,1) NOT NULL,     -- 热量快照 kcal
    protein            NUMERIC(7,2),
    fat                NUMERIC(7,2),
    carb               NUMERIC(7,2),
    confidence         NUMERIC(4,2),              -- 识别置信度
    source             SMALLINT DEFAULT 1,        -- 1拍照 2语音 3手动 4AI推荐
    image_url          TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    CHECK (meal_type IN (1, 2, 3, 4)),
    CHECK (amount_g > 0),
    CHECK (calories >= 0),
    CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    CHECK (source IN (1, 2, 3, 4))
);
CREATE INDEX idx_meal_user_date ON meal_record(user_id, record_date DESC, meal_type);
CREATE INDEX idx_meal_food ON meal_record(food_id);
COMMENT ON TABLE meal_record IS '饮食记录：一行一个食物条目，含营养快照；写后触发当日摄入重算（BE2/BE3）';
COMMENT ON COLUMN meal_record.confidence IS 'AI 识别置信度：<0.7 必须用户确认（§13.3）';

-- 运动记录（§7.2）
CREATE TABLE sport_record (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    sport_name   VARCHAR(128),
    met          NUMERIC(4,2),
    duration_min INTEGER NOT NULL,
    calories     NUMERIC(8,1) NOT NULL,
    source       SMALLINT DEFAULT 1,              -- 1手动 2手环 3标准项目
    record_at    TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    CHECK (duration_min > 0),
    CHECK (calories >= 0)
);
CREATE INDEX idx_sport_user ON sport_record(user_id, record_at DESC);
COMMENT ON TABLE sport_record IS '运动记录：EAT 数据源，写入后重算当日消耗';

-- 步数记录（§7.2）
CREATE TABLE step_record (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    record_date    DATE NOT NULL,
    steps          INTEGER NOT NULL,
    source         SMALLINT DEFAULT 1,            -- 1微信 2手环
    hourly_json    JSONB DEFAULT '{}'::jsonb,     -- 逐时步数，用于 NEAT 校准
    calibrated_met NUMERIC(4,2),                  -- 校准后 MET
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, record_date),
    CHECK (steps >= 0)
);
CREATE INDEX idx_step_user_date ON step_record(user_id, record_date DESC);
COMMENT ON TABLE step_record IS '步数记录：逐时步数 JSONB 供校准（步数0走 PAL 估算，>0 走校准 §13.3）';

-- 每日热量快照（§7.2）
CREATE TABLE daily_snapshot (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    snapshot_date    DATE NOT NULL,
    bmr              NUMERIC(7,1),
    pal              NUMERIC(3,2),
    neat             NUMERIC(7,1),
    eat              NUMERIC(7,1),
    tef              NUMERIC(7,1),
    tee              NUMERIC(7,1),
    intake           NUMERIC(7,1) DEFAULT 0,
    deficit          NUMERIC(8,1) DEFAULT 0,
    steps            INTEGER DEFAULT 0,
    calories_burnt   NUMERIC(8,1) DEFAULT 0,
    calibration_used BOOLEAN DEFAULT FALSE,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, snapshot_date)
);
CREATE INDEX idx_snap_user_date ON daily_snapshot(user_id, snapshot_date DESC);
COMMENT ON TABLE daily_snapshot IS '每日热量快照：(user_id, snapshot_date) 唯一，0 点生成+幂等写入（BE2）';
COMMENT ON COLUMN daily_snapshot.deficit IS '缺口 = 摄入 - TEE，负值为热量缺口（有利减重）';

-- 提醒订阅（§7.1 清单未列，按最简结构补齐【假设】）
CREATE TABLE subscription (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    template_type     SMALLINT NOT NULL,          -- 1午餐提醒 2晚餐提醒 3深夜防崩塌 4称重提醒
    status            SMALLINT DEFAULT 1,         -- 1已订阅 0已退订
    subscribe_count   INTEGER DEFAULT 0,          -- 累计订阅次数（微信一次性订阅需累计）
    last_subscribe_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, template_type),
    CHECK (template_type IN (1, 2, 3, 4)),
    CHECK (status IN (0, 1))
);
COMMENT ON TABLE subscription IS '订阅消息设置：餐前 11:00/17:00、深夜防崩塌、称重提醒（BE-n）';
COMMENT ON COLUMN subscription.template_type IS '1午餐提醒 2晚餐提醒 3深夜防崩塌 4称重提醒';

-- -----------------------------------------------------------------------------
-- 3. AI 域
-- -----------------------------------------------------------------------------

-- AI 对话（§7.2）
CREATE TABLE ai_dialog (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT REFERENCES "user"(id),
    session_id UUID DEFAULT uuid_generate_v4(),
    role       VARCHAR(16) NOT NULL,              -- user / assistant
    content    TEXT NOT NULL,
    intent     VARCHAR(64),
    tokens     INTEGER,
    model      VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (role IN ('user', 'assistant'))
);
CREATE INDEX idx_ai_session ON ai_dialog(session_id, created_at);
CREATE INDEX idx_ai_dialog_user ON ai_dialog(user_id, created_at DESC);
COMMENT ON TABLE ai_dialog IS 'AI 对话流水：按 session_id 串会话；超2年按月归档（§7.4）';

-- AI 知识库 RAG（§7.2）
CREATE TABLE ai_knowledge (
    id         BIGSERIAL PRIMARY KEY,
    category   VARCHAR(64),
    title      VARCHAR(256),
    content    TEXT NOT NULL,
    embedding  JSONB,   -- 【假设】向量占位：首期不装 pgvector（plan.md 决策3），结构 {"model":..,"vector":[..]}
    source     VARCHAR(256),
    search_vec tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))) STORED,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_knowledge_vec ON ai_knowledge USING gin(search_vec);
CREATE INDEX idx_knowledge_cat ON ai_knowledge(category);
COMMENT ON TABLE ai_knowledge IS 'RAG 知识库：正式语料 DATA3（W5 交付）；embedding JSONB 占位 + 全文检索兜底';
COMMENT ON COLUMN ai_knowledge.embedding IS '向量占位 JSONB（首期），后续可换 pgvector 向量列';

-- -----------------------------------------------------------------------------
-- 4. 商家与交易域
-- -----------------------------------------------------------------------------

-- 商家（§7.2，去掉 PostGIS 依赖【假设1】）
CREATE TABLE merchant (
    id           BIGSERIAL PRIMARY KEY,
    name         VARCHAR(128) NOT NULL,
    category     VARCHAR(64) NOT NULL,            -- 轻食店/便利店/健身房/场馆等
    address      TEXT,
    lat          NUMERIC(10,7),                   -- 纬度
    lng          NUMERIC(10,7),                   -- 经度
    phone        VARCHAR(32),
    rating       NUMERIC(3,1) DEFAULT 5.0,
    status       SMALLINT DEFAULT 1,              -- 1营业 0停业
    audit_status SMALLINT DEFAULT 0,              -- 0待审 1通过 2驳回
    owner_user_id BIGINT REFERENCES "user"(id),
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    CHECK (rating >= 0 AND rating <= 5),
    CHECK (audit_status IN (0, 1, 2))
);
CREATE INDEX idx_merchant_geo ON merchant(lat, lng);
CREATE INDEX idx_merchant_category ON merchant(category);
COMMENT ON TABLE merchant IS '商家：LBS 用 lat/lng（【假设】不装 PostGIS）；入驻走审核（ADM3/审核队列）';

-- 标准目录（§7.2）
CREATE TABLE sku_catalog (
    id            BIGSERIAL PRIMARY KEY,
    code          VARCHAR(32) UNIQUE NOT NULL,    -- FD-001 等
    name          VARCHAR(128) NOT NULL,
    category      VARCHAR(64),
    calories_low  INTEGER,
    calories_high INTEGER,
    base_price    NUMERIC(8,2) NOT NULL,
    min_price     NUMERIC(8,2) NOT NULL,          -- 价格区间下限（越界后端 400）
    max_price     NUMERIC(8,2) NOT NULL,          -- 价格区间上限
    unit          VARCHAR(32),
    status        SMALLINT DEFAULT 1,             -- 1上架 0下架
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    CHECK (min_price >= 0),
    CHECK (max_price >= min_price)
);
COMMENT ON TABLE sku_catalog IS '标准 SKU 目录：平台运营维护（DATA2 W7 交付）；商家只选不建（§6.3.4）';
COMMENT ON COLUMN sku_catalog.min_price IS '价格区间下限：后端校验 price BETWEEN min AND max，越界 400';

-- 商家 SKU（§7.2）
CREATE TABLE merchant_sku (
    id          BIGSERIAL PRIMARY KEY,
    merchant_id BIGINT REFERENCES merchant(id) ON DELETE CASCADE,
    catalog_id  BIGINT REFERENCES sku_catalog(id),
    price       NUMERIC(8,2) NOT NULL,            -- 必须落在目录价格区间内（服务层校验）
    stock       INTEGER DEFAULT -1,               -- -1无限
    status      SMALLINT DEFAULT 1,               -- 1上架 0下架
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    CHECK (price >= 0),
    CHECK (stock >= -1),
    CHECK (status IN (0, 1))
);
CREATE INDEX idx_ms_merchant ON merchant_sku(merchant_id);
CREATE UNIQUE INDEX uk_ms ON merchant_sku(merchant_id, catalog_id);
COMMENT ON TABLE merchant_sku IS '商家 SKU：商家从标准目录选品定价，(merchant_id, catalog_id) 唯一';

-- 券池（§6.3.5：券统一入券池，用户只能从邀请任务/平台补贴获得，不外发）
CREATE TABLE coupon_pool (
    id            BIGSERIAL PRIMARY KEY,
    name          VARCHAR(128) NOT NULL,
    type          SMALLINT NOT NULL,              -- 1满减 2折扣 3免费 4体验
    scope         SMALLINT NOT NULL,              -- 1吃 2动 3异业 4通用
    amount        NUMERIC(8,2) DEFAULT 0,         -- 减免金额
    discount_rate NUMERIC(4,2),                   -- 折扣
    min_spend     NUMERIC(8,2) DEFAULT 0,         -- 使用门槛
    merchant_id   BIGINT REFERENCES merchant(id), -- 空=平台通用券
    sponsor       SMALLINT DEFAULT 1,             -- 1商家 2平台
    total_count   INTEGER DEFAULT 0,              -- 发放总量，-1不限
    granted_count INTEGER DEFAULT 0,              -- 已发放量
    valid_from    TIMESTAMPTZ,
    valid_to      TIMESTAMPTZ,
    status        SMALLINT DEFAULT 1,             -- 1上架 0下架
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    CHECK (type IN (1, 2, 3, 4)),
    CHECK (scope IN (1, 2, 3, 4)),
    CHECK (total_count >= -1),
    CHECK (granted_count >= 0),
    CHECK (amount >= 0),
    CHECK (min_spend >= 0)
);
CREATE INDEX idx_pool_merchant ON coupon_pool(merchant_id);
COMMENT ON TABLE coupon_pool IS '券池：平台/商家发放源头，发放时生成用户券 coupon（§6.3.5）';
COMMENT ON COLUMN coupon_pool.scope IS '适用范围：1吃 2动 3异业 4通用';
COMMENT ON COLUMN coupon_pool.total_count IS '发放总量：-1 表示不限量';

-- 用户券（§7.2，补 pool_id 关联券池【假设】）
CREATE TABLE coupon (
    id            BIGSERIAL PRIMARY KEY,
    pool_id       BIGINT REFERENCES coupon_pool(id),
    code          VARCHAR(64) UNIQUE NOT NULL,    -- 核销码 UUID（§6.3.5 唯一索引）
    type          SMALLINT NOT NULL,              -- 1满减 2折扣 3免费 4体验
    scope         SMALLINT NOT NULL,              -- 1吃 2动 3异业 4通用
    amount        NUMERIC(8,2) DEFAULT 0,
    discount_rate NUMERIC(4,2),
    min_spend     NUMERIC(8,2) DEFAULT 0,
    merchant_id   BIGINT REFERENCES merchant(id),
    sponsor       SMALLINT DEFAULT 1,             -- 1商家 2平台
    obtain_way    SMALLINT DEFAULT 1,             -- 1邀请 2任务 3平台补贴 4注册礼
    obtain_user_id BIGINT REFERENCES "user"(id),
    status        SMALLINT DEFAULT 1,             -- 1未用 2已用 3过期 4作废
    valid_from    TIMESTAMPTZ,
    valid_to      TIMESTAMPTZ,
    used_at       TIMESTAMPTZ,
    order_id      BIGINT,                         -- 冲销用到的订单（无 FK，避免循环引用）
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    CHECK (type IN (1, 2, 3, 4)),
    CHECK (scope IN (1, 2, 3, 4)),
    CHECK (status IN (1, 2, 3, 4)),
    CHECK (amount >= 0),
    CHECK (min_spend >= 0)
);
CREATE INDEX idx_coupon_user ON coupon(obtain_user_id, status);
CREATE INDEX idx_coupon_merchant ON coupon(merchant_id);
COMMENT ON TABLE coupon IS '用户券：code 为核销码 UUID，唯一索引防重复核销（§7.3）';
COMMENT ON COLUMN coupon.status IS '1未用 2已用 3过期 4作废';
COMMENT ON COLUMN coupon.obtain_way IS '获得途径：1邀请 2任务 3平台补贴 4注册礼（不外发 §6.3.5）';

-- 订单（§7.2）
CREATE TABLE "order" (
    id              BIGSERIAL PRIMARY KEY,
    order_no        VARCHAR(64) UNIQUE NOT NULL,
    user_id         BIGINT REFERENCES "user"(id),
    merchant_id     BIGINT REFERENCES merchant(id),
    total_amount    NUMERIC(10,2) NOT NULL,
    discount_amount NUMERIC(10,2) DEFAULT 0,
    pay_amount      NUMERIC(10,2) NOT NULL,       -- 服务端重算 = total - discount，不信前端
    coupon_id       BIGINT REFERENCES coupon(id),
    status          SMALLINT DEFAULT 1,           -- 1待支付 2已支付待核销 3已完成 4已取消 5已退款
    pay_at          TIMESTAMPTZ,
    expire_at       TIMESTAMPTZ,                  -- 15分钟超时取消
    redeem_code     VARCHAR(64) UNIQUE,           -- 核销码，唯一约束防重复核销
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CHECK (status IN (1, 2, 3, 4, 5)),
    CHECK (pay_amount = total_amount - discount_amount),
    CHECK (total_amount >= 0),
    CHECK (discount_amount >= 0)
);
CREATE INDEX idx_order_user ON "order"(user_id, created_at DESC);
CREATE INDEX idx_order_merchant ON "order"(merchant_id, status);
COMMENT ON TABLE "order" IS '订单：核销码唯一；金额一致性服务端重算（§7.3）；15分钟超时取消释放券';
COMMENT ON COLUMN "order".status IS '1待支付 2已支付待核销 3已完成 4已取消 5已退款';
COMMENT ON COLUMN "order".pay_amount IS '实付金额 = total_amount - discount_amount，CHECK 强制一致';

-- 订单项（§7.1 清单列出，按最简结构补齐【假设】）
CREATE TABLE order_item (
    id                BIGSERIAL PRIMARY KEY,
    order_id          BIGINT NOT NULL REFERENCES "order"(id) ON DELETE CASCADE,
    sku_id            BIGINT REFERENCES merchant_sku(id),
    sku_name_snapshot VARCHAR(128) NOT NULL,      -- 快照防目录变更
    unit_price        NUMERIC(10,2) NOT NULL,
    quantity          INTEGER NOT NULL,
    subtotal          NUMERIC(10,2) NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    CHECK (quantity > 0),
    CHECK (unit_price >= 0),
    CHECK (subtotal >= 0)
);
CREATE INDEX idx_order_item_order ON order_item(order_id);
COMMENT ON TABLE order_item IS '订单项：含 SKU 名称/单价快照，金额一致性由服务层重算';

-- 核销日志（§7.2）
CREATE TABLE redeem_log (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT REFERENCES "order"(id),
    merchant_id     BIGINT REFERENCES merchant(id),
    operator_user_id BIGINT,                      -- 核销操作员
    result          SMALLINT DEFAULT 1,           -- 1成功 2失败
    fail_reason     VARCHAR(256),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CHECK (result IN (1, 2))
);
COMMENT ON TABLE redeem_log IS '核销日志：核销成功/失败全留痕，失败原因可追溯';

-- -----------------------------------------------------------------------------
-- 5. 社区与社交域
-- -----------------------------------------------------------------------------

-- 社区动态（§7.2）
CREATE TABLE community_post (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT REFERENCES "user"(id),
    title         VARCHAR(256),
    content       TEXT,
    images        JSONB DEFAULT '[]'::jsonb,
    post_type     SMALLINT DEFAULT 1,             -- 1普通 2经验 3打卡
    like_count    INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    anonymous     BOOLEAN DEFAULT FALSE,
    audit_status  SMALLINT DEFAULT 1,             -- 0待审 1通过 2驳回
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    CHECK (post_type IN (1, 2, 3)),
    CHECK (audit_status IN (0, 1, 2))
);
CREATE INDEX idx_post_created ON community_post(created_at DESC);
COMMENT ON TABLE community_post IS '社区动态：发帖/晒图/点赞/评论；违规内容进审核队列不直接展示（BE7c）';

-- 社区评论（任务指定，按最简结构补齐【假设】）
CREATE TABLE community_comment (
    id           BIGSERIAL PRIMARY KEY,
    post_id      BIGINT NOT NULL REFERENCES community_post(id) ON DELETE CASCADE,
    user_id      BIGINT REFERENCES "user"(id),
    content      TEXT NOT NULL,
    anonymous    BOOLEAN DEFAULT FALSE,
    audit_status SMALLINT DEFAULT 1,              -- 0待审 1通过 2驳回
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    CHECK (audit_status IN (0, 1, 2))
);
CREATE INDEX idx_comment_post ON community_comment(post_id, created_at);
COMMENT ON TABLE community_comment IS '社区评论：违规内容走审核（msgSecCheck）';

-- 社区点赞（任务指定，按最简结构补齐【假设】）
CREATE TABLE community_like (
    id         BIGSERIAL PRIMARY KEY,
    post_id    BIGINT NOT NULL REFERENCES community_post(id) ON DELETE CASCADE,
    user_id    BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (post_id, user_id)
);
COMMENT ON TABLE community_like IS '社区点赞：(post_id, user_id) 唯一，一人一赞';

-- 兴趣社群（§7.2）
CREATE TABLE community_group (
    id           BIGSERIAL PRIMARY KEY,
    name         VARCHAR(128) NOT NULL,
    category     VARCHAR(64),
    member_count INTEGER DEFAULT 0,
    city         VARCHAR(64),
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_group_cat ON community_group(category);
COMMENT ON TABLE community_group IS '兴趣社群：长期打卡/活动（BE7b）';

-- 监督关系（§7.2）
CREATE TABLE supervise (
    id         BIGSERIAL PRIMARY KEY,
    user_a     BIGINT REFERENCES "user"(id),
    user_b     BIGINT REFERENCES "user"(id),
    status     SMALLINT DEFAULT 1,                -- 1生效 0解除
    days       INTEGER DEFAULT 0,                 -- 互相监督天数
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_a, user_b),
    CHECK (user_a <> user_b)
);
COMMENT ON TABLE supervise IS '监督社交：互看记录/提醒打卡（BE7b），一人一对唯一';

-- 约战（§7.2）
CREATE TABLE battle (
    id         BIGSERIAL PRIMARY KEY,
    title      VARCHAR(256),
    sport_type VARCHAR(64),
    merchant_id BIGINT REFERENCES merchant(id),
    city       VARCHAR(64),
    meet_at    TIMESTAMPTZ,
    need_count INTEGER DEFAULT 2,
    join_count INTEGER DEFAULT 1,
    creator_id BIGINT REFERENCES "user"(id),
    status     SMALLINT DEFAULT 1,                -- 1招募中 2满员 3进行中 4结束
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (status IN (1, 2, 3, 4))
);
CREATE INDEX idx_battle_city ON battle(city, meet_at);
COMMENT ON TABLE battle IS '约战：LBS 匹配/加入/关联场馆券（BE7b）';

-- 挑战赛（§7.2）
CREATE TABLE challenge (
    id         BIGSERIAL PRIMARY KEY,
    title      VARCHAR(256) NOT NULL,
    start_at   TIMESTAMPTZ,
    end_at     TIMESTAMPTZ,
    badge_image TEXT,
    join_count INTEGER DEFAULT 0,
    status     SMALLINT DEFAULT 1,                -- 1进行中 2结束
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (end_at IS NULL OR start_at IS NULL OR end_at > start_at)
);
COMMENT ON TABLE challenge IS '限时挑战赛：进度/排行榜/徽章（BE7b）';

-- 挑战报名（§7.2）
CREATE TABLE challenge_join (
    id           BIGSERIAL PRIMARY KEY,
    challenge_id BIGINT REFERENCES challenge(id),
    user_id      BIGINT REFERENCES "user"(id),
    rank         INTEGER,                         -- 名次
    score        NUMERIC(8,1),
    joined_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (challenge_id, user_id)
);
COMMENT ON TABLE challenge_join IS '挑战赛参与：(challenge_id, user_id) 唯一，一人一赛一次';

-- 热量控制榜（任务指定，按最简结构补齐【假设】）
CREATE TABLE leaderboard (
    id          BIGSERIAL PRIMARY KEY,
    period_type SMALLINT NOT NULL,                -- 1日榜 2周榜 3月榜
    period_key  VARCHAR(16) NOT NULL,             -- 期号：2026-09-28 / 2026-W40 / 2026-09
    user_id     BIGINT REFERENCES "user"(id) ON DELETE CASCADE,
    score       NUMERIC(10,1) DEFAULT 0,          -- 控制榜得分（口径服务层定，如热量缺口）
    rank        INTEGER,                          -- 名次
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (period_type, period_key, user_id),
    CHECK (period_type IN (1, 2, 3))
);
CREATE INDEX idx_leaderboard_rank ON leaderboard(period_type, period_key, rank);
COMMENT ON TABLE leaderboard IS '热量控制榜：按期（日/周/月）预聚合名次，避免实时全表排序';

-- -----------------------------------------------------------------------------
-- 6. 运营与系统域
-- -----------------------------------------------------------------------------

-- 审核队列（§7.1 review；任务指定，按最简结构补齐【假设】）
CREATE TABLE review (
    id               BIGSERIAL PRIMARY KEY,
    target_type      SMALLINT NOT NULL,           -- 1动态 2评论 3图片 4商家入驻
    target_id        BIGINT NOT NULL,
    user_id          BIGINT REFERENCES "user"(id), -- 内容提交者
    content_snapshot TEXT,                        -- 送审内容快照
    sec_check_result SMALLINT,                    -- 1通过 2可疑 3不通过（微信安全接口）
    status           SMALLINT DEFAULT 0,          -- 0待审 1通过 2驳回
    reject_reason    VARCHAR(256),
    reviewer_id      BIGINT,                      -- 处理人 admin_user.id
    reviewed_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    CHECK (target_type IN (1, 2, 3, 4)),
    CHECK (status IN (0, 1, 2))
);
CREATE INDEX idx_review_status ON review(status, created_at);
CREATE INDEX idx_review_target ON review(target_type, target_id);
COMMENT ON TABLE review IS '审核队列：msgSecCheck/imgSecCheck 违规内容与商家入驻审核（BE7c/ADM3）';
COMMENT ON COLUMN review.target_type IS '审核对象：1动态 2评论 3图片 4商家入驻';

-- 运营账号（§7.2）
CREATE TABLE admin_user (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    role          SMALLINT DEFAULT 2,             -- 1超管 2运营 3商家
    merchant_id   BIGINT REFERENCES merchant(id),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    CHECK (role IN (1, 2, 3))
);
COMMENT ON TABLE admin_user IS '管理后台账号（ADM1）：账号密码登录';

-- 全局配置（§7.2）
CREATE TABLE config (
    key        VARCHAR(128) PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE config IS '全局配置：key-value，JSONB 动态结构';

-- 埋点事件（任务指定，按最简结构补齐【假设】）
CREATE TABLE track_event (
    id          BIGSERIAL PRIMARY KEY,
    event       VARCHAR(64) NOT NULL,             -- 事件名：login/meal_photo/ai_chat/order_pay...
    user_id     BIGINT,                           -- 可空（匿名/登录前），高频写入不建 FK【假设】
    device_id   VARCHAR(64),
    platform    SMALLINT DEFAULT 1,               -- 1小程序 2H5 3admin后台
    properties  JSONB DEFAULT '{}'::jsonb,        -- 事件属性
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    CHECK (platform IN (1, 2, 3))
);
CREATE INDEX idx_track_event_name ON track_event(event, occurred_at DESC);
CREATE INDEX idx_track_event_user ON track_event(user_id);
COMMENT ON TABLE track_event IS '埋点事件：6 项核心指标数据源（留存/K因子/扫码转化/识别成功率/AI满意度/获客成本）';

-- -----------------------------------------------------------------------------
-- updated_at 自动维护触发器
-- -----------------------------------------------------------------------------
CREATE TRIGGER trg_user_updated_at BEFORE UPDATE ON "user"
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_body_profile_updated_at BEFORE UPDATE ON body_profile
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_subscription_updated_at BEFORE UPDATE ON subscription
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_order_updated_at BEFORE UPDATE ON "order"
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_config_updated_at BEFORE UPDATE ON config
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
