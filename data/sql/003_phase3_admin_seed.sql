-- 003_phase3_admin_seed.sql — Phase 3 管理后台种子账号（幂等，可重复执行）。
-- 账号：admin/Admin@123456（超管 role=1）、ops/Admin@123456（运营 role=2）、
--       merchant1/Merchant@123（商家 role=3；merchant_id 默认 NULL，
--       主库执行 004_phase3_demo.sql 时会将其绑定到演示商家 9901）。
-- 密码哈希格式与 app.core.security.hash_password 一致（pbkdf2_sha256，600k iters，固定盐仅限本地种子）。

INSERT INTO admin_user (id, username, password_hash, role, merchant_id) VALUES
  (99001, 'admin',     'pbkdf2_sha256$600000$a11c0ffee0000001$c1cb77eb34f6b6ef11b931695d8ede027a5cb1f5468b1ae3dc77846b904b76ff', 1, NULL),
  (99002, 'ops',       'pbkdf2_sha256$600000$a11c0ffee0000002$1822f079f84805e7cc33f10c274fd13667aa01ac151123bdbd797f5aae84690d', 2, NULL),
  (99003, 'merchant1', 'pbkdf2_sha256$600000$a11c0ffee0000003$0aadea68d5c85141b7307c5855153a4e500cc4614b7ab6b4369ae56099516158', 3, NULL)
ON CONFLICT (username) DO UPDATE
  SET password_hash = EXCLUDED.password_hash,
      role = EXCLUDED.role,
      merchant_id = EXCLUDED.merchant_id;

SELECT setval('admin_user_id_seq', GREATEST((SELECT max(id) FROM admin_user), 1));
