#!/usr/bin/env python3
"""init_admin.py — 管理后台初始超管账号的幂等初始化（ADM1）。

为什么需要：`.env` 的 ADMIN_INIT_USERNAME / ADMIN_INIT_PASSWORD 此前只被
`app/core/config.py` 声明、被 `app/main.py` 的生产密钥守卫读取（即"是否还是默认值"），
**没有任何代码用它们建账号**——超管实际来自 `data/sql/003_phase3_admin_seed.sql`
的硬编码密码哈希。改 .env 不会影响登录，属于配置与实现脱节。本脚本把 .env
变成账号的唯一真源。

行为（幂等，可反复执行）：
- 账号不存在        → 创建，role=1（超管），id 交给 BIGSERIAL 分配
- 账号存在且密码匹配 → **不动**（不重算哈希，省掉 600k 迭代的 PBKDF2 开销）
- 账号存在且密码不匹配 → 更新哈希，并校正 role=1 / merchant_id=NULL
                       （若原账号不是超管，打印显式警告——这会把一个已有账号提升为超管）

弱口令拒绝：占位串（.env.example 的值、`change-me` 前缀）、仓库内公开口令黑名单
（`_KNOWN_PUBLIC_PASSWORDS`）、后端默认口令、长度 < 12 的值一律拒绝建号/改密并返回非 0
——`.env.example` 的占位串不等于 Settings 默认值，`app/main.py` 的生产守卫放行它，
若脚本照建就等于把公开口令变成可用超管凭据。该检查只在"需要建号或需要改密"时**拒绝**；
账号已存在且密码一致时只**告警**（不拒绝、不改密），避免把"运维忘了换 .env"这种
正常启动卡死——但告警会写 stderr，让 CI/运维看见弱口令仍在生效。

只管 role=1 的初始超管；其余角色（运营/商家/教练）由超管登录后在后台创建，
不再由种子文件预置（data/sql/003_phase3_admin_seed.sql 已删除 admin 行）。

用法（compose 的 migrate 服务调用；也可手工执行）：
    python backend/scripts/init_admin.py --dsn "postgresql://user:pw@host:5432/db"
凭据默认取环境变量 ADMIN_INIT_USERNAME / ADMIN_INIT_PASSWORD（.env 经 env_file 注入）。

--optional（compose 的 migrate 走这个模式）：凭据缺失时不报错、跳过建号、返回 0，
让"没有根 .env 的新机器"仍能起栈（migrate 失败会因 service_completed_successfully
拖死 api/worker/nginx）。但若凭据**存在**却是占位串/弱值，仍按上文拒绝并失败
（那是"运维以为配好了"，不能静默放过）。不带该开关时缺凭据直接报错，便于手工发现。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

# 复用后端密码原语，保证与登录侧 verify_password 完全同一套格式与迭代次数。
# 口令策略（长度/黑名单/占位串拒绝）也统一收口在 app.core.security.reject_weak_password，
# 账号管理接口（POST /api/admin/accounts）与初始化脚本共用同一套规则。
from app.core.security import (  # noqa: E402
    MIN_ADMIN_PASSWORD_LENGTH,
    hash_password,
    reject_weak_password,
    verify_password,
)

# admin_user.role：1 超管 2 运营 3 商家 4 教练（data/sql/001_schema.sql 的 CHECK 约束）。
ROLE_SUPER_ADMIN = 1

# 退出码：2 = 缺凭据/缺 DSN（未带 --optional）；3 = 凭据存在但不合格；1 = 数据库操作失败。
EXIT_CREDENTIALS_MISSING = 2
EXIT_WEAK_CREDENTIALS = 3
EXIT_DB_ERROR = 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="初始化管理后台超管账号（幂等）")
    p.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL", ""),
        help="PostgreSQL DSN，默认读环境变量 DATABASE_URL（注意用 psycopg2 同步 DSN）",
    )
    p.add_argument(
        "--username",
        default=os.environ.get("ADMIN_INIT_USERNAME", ""),
        help="超管账号名，默认读环境变量 ADMIN_INIT_USERNAME",
    )
    p.add_argument(
        "--password",
        default=os.environ.get("ADMIN_INIT_PASSWORD", ""),
        help="超管密码，默认读环境变量 ADMIN_INIT_PASSWORD",
    )
    p.add_argument(
        "--optional",
        action="store_true",
        help="凭据缺失时跳过建号并返回 0（compose 的 migrate 用，避免拖死整栈）；"
        "凭据存在但为占位串/弱口令时仍然失败",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.dsn:
        print("错误：未提供 --dsn，且环境变量 DATABASE_URL 为空", file=sys.stderr)
        return EXIT_CREDENTIALS_MISSING
    # 不静默用空密码建号：空密码会让超管成为无凭据入口，比建不出账号更危险。
    if not args.username or not args.password:
        if args.optional:
            print(
                "未配置 ADMIN_INIT_USERNAME / ADMIN_INIT_PASSWORD，"
                "跳过超管账号初始化（--optional）。请人工创建超管后登录管理后台。"
            )
            return 0
        print(
            "错误：ADMIN_INIT_USERNAME / ADMIN_INIT_PASSWORD 不能为空（拒绝创建空凭据超管）",
            file=sys.stderr,
        )
        return EXIT_CREDENTIALS_MISSING

    import psycopg2  # 延迟导入：与 load_seeds.py 同风格

    # connect 也在 try 内：连不上库时 psycopg2 的异常原文含 DSN（可能内嵌口令）
    # 与主机/库名，不能让它裸奔到日志里。
    conn = None
    try:
        conn = psycopg2.connect(args.dsn)
        with conn, conn.cursor() as cur:
            # 串行化同一账号名的并发初始化：SELECT ... FOR UPDATE 在零行命中时**不持任何锁**
            # （锁的是已存在的行），所以两个 compose 同时起时双方都会判定"不存在"并各自 INSERT，
            # 输的一方撞 username 唯一约束 → UniqueViolation → migrate 非 0 退出 →
            # api/worker（依赖 service_completed_successfully）不启动。实测 6 并发有 1 个失败。
            # 事务级 advisory lock 按 username 串行：后到者等到前者提交后再读，
            # 就会走"已存在 → 校验口令"分支。锁在事务结束时自动释放。
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (args.username,))
            cur.execute(
                "SELECT id, role, password_hash FROM admin_user WHERE username = %s FOR UPDATE",
                (args.username,),
            )
            row = cur.fetchone()

            if row is None:
                reason = reject_weak_password(args.password)
                if reason:
                    print(
                        f"错误：拒绝创建超管账号——密码{reason}。"
                        "请在 .env 配置真实强口令（长度 ≥ "
                        f"{MIN_ADMIN_PASSWORD_LENGTH}）后重试。",
                        file=sys.stderr,
                    )
                    return EXIT_WEAK_CREDENTIALS
                # id 交给 admin_user.id 的 BIGSERIAL 分配：不硬编码，避免改了
                # ADMIN_INIT_USERNAME 就撞主键（确定性失败、连跑两次不自愈）。
                cur.execute(
                    "INSERT INTO admin_user (username, password_hash, role, merchant_id) "
                    "VALUES (%s, %s, %s, NULL)",
                    (args.username, hash_password(args.password), ROLE_SUPER_ADMIN),
                )
            elif verify_password(args.password, row[2]):
                # 密码已匹配 → 不动。这是常用路径，跳过重算哈希。
                # 不在此分支拒绝（拒绝会把"运维忘了换 .env"的正常启动卡死，
                # 且 migrate 非 0 退出会拖死 api/worker/nginx），但必须告警：
                # 库里这个口令当初可能是靠占位串建进来的，脚本"不动它"就等于
                # 让弱口令永久有效，与文件头"弱口令一律拒绝"的声明矛盾。
                warning = reject_weak_password(args.password)
                if warning:
                    print(
                        f"警告：当前超管口令仍是弱口令/占位串（{warning}），"
                        "请立即修改 .env 中的 ADMIN_INIT_PASSWORD",
                        file=sys.stderr,
                    )
            else:
                reason = reject_weak_password(args.password)
                if reason:
                    print(
                        f"错误：拒绝更新超管密码——密码{reason}。"
                        "请在 .env 配置真实强口令（长度 ≥ "
                        f"{MIN_ADMIN_PASSWORD_LENGTH}）后重试。",
                        file=sys.stderr,
                    )
                    return EXIT_WEAK_CREDENTIALS
                if row[1] != ROLE_SUPER_ADMIN:
                    # 该文件的定位是"超管账号真源"：撞到已有非超管账号时必须校正 role，
                    # 否则 exit=0 会让运维误以为超管已就绪。
                    print(
                        f"警告：账号 {args.username} 已存在但 role={row[1]}（非超管），"
                        "本次已将其提升为超管（role=1, merchant_id=NULL）。"
                        "若非预期，请改 .env 的 ADMIN_INIT_USERNAME 后重跑。",
                        file=sys.stderr,
                    )
                cur.execute(
                    "UPDATE admin_user SET password_hash = %s, role = %s, merchant_id = NULL "
                    "WHERE id = %s",
                    (hash_password(args.password), ROLE_SUPER_ADMIN, row[0]),
                )
            # 成功路径单一口径：不给运维"账号是否存在/是否改过密码"的 oracle。
            print(f"超管账号已同步：{args.username}")
    except Exception as e:  # noqa: BLE001
        if conn is not None:
            conn.rollback()
        # 只回显异常类型，不回显底层 DB 错误原文（会把 admin_user_pkey 等约束名、
        # DSN 与 SQL 细节带进运维日志）。
        print(
            f"初始化超管失败，已回滚（{type(e).__name__}）。"
            "请检查数据库连通性、admin_user 表结构与迁移版本。",
            file=sys.stderr,
        )
        return EXIT_DB_ERROR
    finally:
        if conn is not None:
            conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())