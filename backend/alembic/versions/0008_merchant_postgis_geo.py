"""merchant 位置字段 PostGIS GEOMETRY 化（N-7/D-06，docs/changes/2026-10-01 决策记录 §二）。

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01

口径：§7.2 DDL `geo GEOMETRY(Point,4326)` 主口径，配套 GIST(geo) 空间索引；
API 契约（入参/出参 lat/lng 数值）不变，仅存储层改造。本迁移可回滚：
- up：启用 postgis → 加 geo 列 → 旧数据 ST_MakePoint(lng,lat) 回填 →
  删旧索引 idx_merchant_geo(lat,lng) 与 lat/lng 列 → 建 GIST(geo)。
- down：反向（加回 lat/lng、从 geo 反解回填、删 geo 与 GIST、重建旧索引）。
与 data/sql/001_schema.sql 同源更新。
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
CREATE EXTENSION IF NOT EXISTS postgis;
ALTER TABLE merchant ADD COLUMN geo geometry(Point, 4326);
-- 旧数据回填：注意 ST_MakePoint 参数顺序为 (lng, lat)
UPDATE merchant SET geo = ST_SetSRID(ST_MakePoint(lng, lat), 4326)
WHERE lng IS NOT NULL AND lat IS NOT NULL;
DROP INDEX IF EXISTS idx_merchant_geo;
ALTER TABLE merchant DROP COLUMN lng;
ALTER TABLE merchant DROP COLUMN lat;
CREATE INDEX idx_merchant_geo ON merchant USING GIST(geo);
COMMENT ON TABLE merchant IS '商家：LBS 用 PostGIS geo（GEOMETRY(Point,4326)+GIST，§7.2 主口径）；API 出入参仍 lat/lng；入驻走审核（ADM3/审核队列）';
"""

DOWNGRADE_SQL = r"""
DROP INDEX IF EXISTS idx_merchant_geo;
ALTER TABLE merchant ADD COLUMN lat NUMERIC(10, 7);
ALTER TABLE merchant ADD COLUMN lng NUMERIC(10, 7);
-- 反向回填：ST_Y=纬度 / ST_X=经度
UPDATE merchant SET lat = ST_Y(geo)::NUMERIC(10, 7), lng = ST_X(geo)::NUMERIC(10, 7)
WHERE geo IS NOT NULL;
ALTER TABLE merchant DROP COLUMN geo;
CREATE INDEX idx_merchant_geo ON merchant(lat, lng);
COMMENT ON TABLE merchant IS '商家：LBS 用 lat/lng（【假设】不装 PostGIS）；入驻走审核（ADM3/审核队列）';
"""


def upgrade() -> None:
    """merchant lat/lng → geo GEOMETRY(Point,4326) + GIST，启用 postgis 扩展。"""
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    """geo → lat/lng 反解回填，删空间列与 GIST，恢复旧索引。"""
    op.execute(DOWNGRADE_SQL)
