-- 004_phase3_demo.sql — Phase 3 演示数据（幂等，仅灌主库 ai_coach，供浏览器验收/联调用）。
-- 固定 ID 9901+ 段，与测试数据隔离；执行前先清理旧演示数据。

BEGIN;

-- 演示 ID 段：merchant/coupon_pool=9901-9999，merchant_sku/coupon=99001-99999。
-- 券先于池删除（coupon.pool_id FK）：含 admin grant 产生的非固定 ID 券。
DELETE FROM coupon        WHERE id BETWEEN 99001 AND 99999;
DELETE FROM coupon        WHERE pool_id IN (SELECT id FROM coupon_pool WHERE id BETWEEN 9901 AND 9999);
DELETE FROM coupon_pool   WHERE id BETWEEN 9901 AND 9999;
DELETE FROM merchant_sku  WHERE id BETWEEN 99001 AND 99999;
-- admin_user.merchant_id FK 指向演示商家，先解绑再删商家（末尾会重新绑定）
UPDATE admin_user SET merchant_id = NULL WHERE merchant_id BETWEEN 9901 AND 9999;
DELETE FROM merchant      WHERE id BETWEEN 9901 AND 9999;

-- 演示商家（上海人民广场一带坐标）
INSERT INTO merchant (id, name, category, address, lat, lng, phone, rating, status, audit_status, created_at) VALUES
  (9901, '轻食巴士·人民广场店', '轻食',   '上海市黄浦区南京西路100号', 31.2304000, 121.4737000, '021-63000001', 4.8, 1, 1, now()),
  (9902, '活力健身·私教工作室', '健身房', '上海市黄浦区西藏中路50号',   31.2350000, 121.4790000, '021-63000002', 4.6, 1, 1, now());

-- 商家选品定价（区间内）
INSERT INTO merchant_sku (id, merchant_id, catalog_id, price, stock, status)
SELECT 99011, 9901, c.id, 25.00, 99, 1 FROM sku_catalog c WHERE c.code = 'FD-001'
UNION ALL
SELECT 99012, 9901, c.id, 32.00, 50, 1 FROM sku_catalog c WHERE c.code = 'FD-002'
UNION ALL
SELECT 99013, 9901, c.id, 99.00, 20, 1 FROM sku_catalog c WHERE c.code = 'SP-001'
UNION ALL
SELECT 99021, 9902, c.id, 30.00, -1, 1 FROM sku_catalog c WHERE c.code = 'SP-002'
UNION ALL
SELECT 99022, 9902, c.id, 28.00, 30, 1 FROM sku_catalog c WHERE c.code = 'FD-003';

-- 券池：满减券（吃）、体验券（通用）
INSERT INTO coupon_pool (id, name, type, scope, amount, min_spend, total_count, granted_count, valid_from, valid_to, status) VALUES
  (9901, '新客满10减5券',   1, 1, 5.00,  10.00, 100, 0, now() - interval '1 day', now() + interval '90 day', 1),
  (9902, '体验课免费券',     3, 4, 99.00, 0.00,  50,  0, now() - interval '1 day', now() + interval '90 day', 1);

-- 绑定商家角色账号 merchant1 → 演示商家 9901
UPDATE admin_user SET merchant_id = 9901 WHERE username = 'merchant1';

COMMIT;
