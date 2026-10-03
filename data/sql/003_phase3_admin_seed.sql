-- 003_phase3_admin_seed.sql — Phase 3 管理后台种子账号（幂等，可重复执行）。
-- 账号：ops/Admin@123456（运营 role=2）、merchant1/Merchant@123（商家 role=3；
--       merchant_id 默认 NULL，主库执行 004_phase3_demo.sql 时会将其绑定到演示商家 9901）。
-- 密码哈希格式与 app.core.security.hash_password 一致（pbkdf2_sha256，600k iters，固定盐仅限本地种子）。
--
-- 【超管不在本文件内】超管（role=1）账号的真源是根 .env 的 ADMIN_INIT_USERNAME /
-- ADMIN_INIT_PASSWORD，由 backend/scripts/init_admin.py 幂等创建/同步（compose 的
-- migrate 服务调用它）。2026-10-03 起本文件不再创建 admin 行，原因：本文件的
-- `ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash` 是
-- **无条件覆盖**——只要重跑本文件就会把超管口令改回下面这类写死在仓库里的公开哈希，
-- 使 .env 里配置的真实口令失效。scripts/h5-compat-check.sh 与 CI workflow 都会执行本文件，
-- 删行是唯一能保住 .env 真源的做法。
--
-- ⚠️ 已知遗留（不在本轮范围）：ops / merchant1 的密码仍会被每次重跑本文件覆盖回上面的
-- 公开值。这两个账号是演示/联调用途，不承载生产凭据；如需让它们也免于覆盖，需要另行改造。

INSERT INTO admin_user (id, username, password_hash, role, merchant_id) VALUES
  (99002, 'ops',       'pbkdf2_sha256$600000$a11c0ffee0000002$1822f079f84805e7cc33f10c274fd13667aa01ac151123bdbd797f5aae84690d', 2, NULL),
  (99003, 'merchant1', 'pbkdf2_sha256$600000$a11c0ffee0000003$0aadea68d5c85141b7307c5855153a4e500cc4614b7ab6b4369ae56099516158', 3, NULL)
ON CONFLICT (username) DO UPDATE
  SET password_hash = EXCLUDED.password_hash,
      role = EXCLUDED.role,
      merchant_id = EXCLUDED.merchant_id;

SELECT setval('admin_user_id_seq', GREATEST((SELECT max(id) FROM admin_user), 1));
