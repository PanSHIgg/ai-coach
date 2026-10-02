"""F6 安全测试：SQL 注入防护。

覆盖注入入口：登录 code、食物搜索 keyword、分页参数(page/page_size)、
筛选类 query 参数(status/post_type/date)、路径参数 id。
统一断言：非 500、不泄露 SQL 错误、关键表仍存在且行数不变、返回正常 4xx/空结果。

同类 payload 用 parametrize 合并（AGENTS §2.9）；不重复既有越权/支付篡改用例。
"""

import pytest
from sqlalchemy import text

# 经典注入 payload（含 DROP/UNION/堆叠睡眠/URL 编码引号/超长串）
SQLI_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE \"user\"; --",
    "1 UNION SELECT id, nickname, NULL FROM \"user\" --",
    "%27",
    "admin'--",
    "1; SELECT pg_sleep(2); --",
    "x' OR 1=1 --",
    "a" * 4096,
]
SQLI_IDS = [
    "or_true",
    "drop_user",
    "union_select",
    "urlencoded_quote",
    "comment",
    "stacked_sleep",
    "or_true_variant",
    "long_string",
]

# 注入请求后须行数不变的业务表（引号包裹保留字）
_BIZ_TABLES = ("food", "meal_record", "sport_record", '"order"', "coupon")
# 注入后须仍存在（防 DROP）的关键表
_REQUIRED_TABLES = {
    "user",
    "order",
    "meal_record",
    "food",
    "coupon",
    "community_post",
    "merchant",
}
# 疑似 SQL 错误/驱动栈泄露的标记
_LEAK_MARKERS = (
    "syntax error",
    "psycopg",
    "asyncpg",
    "sqlalchemy.exc",
    "traceback",
    "internalerror",
    "programmingerror",
)


async def _existing_tables(db_session) -> set[str]:
    rows = await db_session.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    return {r[0] for r in rows}


async def _row_counts(db_session, tables: tuple[str, ...]) -> dict[str, int]:
    return {t: int(await db_session.scalar(text(f"SELECT count(*) FROM {t}"))) for t in tables}


def _assert_no_500_nor_leak(resp) -> None:
    assert resp.status_code != 500, resp.text
    body = resp.json()
    assert body["code"] != 500, resp.text
    low = resp.text.lower()
    for marker in _LEAK_MARKERS:
        assert marker not in low, f"疑似 SQL 错误泄露: {resp.text[:200]}"


async def _assert_db_intact(db_session, before: dict[str, int]) -> None:
    present = await _existing_tables(db_session)
    assert _REQUIRED_TABLES <= present, f"关键表缺失: {_REQUIRED_TABLES - present}"
    after = await _row_counts(db_session, tuple(before))
    assert after == before, f"关键表行数变化: {before} -> {after}"


# ---------------------------------------------------------------------------
# 登录 code（字符串入参，code2session 由 conftest 打桩）——注入不得改库/报错
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", SQLI_PAYLOADS, ids=SQLI_IDS)
async def test_login_code_injection_safe(db_client, db_session, payload):
    before = await _row_counts(db_session, _BIZ_TABLES)
    resp = await db_client.post("/api/auth/login", json={"code": payload})
    _assert_no_500_nor_leak(resp)
    # 注入串仅当作不透明 code，正常签发 token
    assert resp.json()["code"] == 0
    await _assert_db_intact(db_session, before)


# ---------------------------------------------------------------------------
# 食物搜索 keyword（tsvector + ILIKE 参数化）——空结果、无泄露
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", SQLI_PAYLOADS, ids=SQLI_IDS)
async def test_food_search_keyword_injection_safe(db_client, db_session, authed, payload):
    before = await _row_counts(db_session, _BIZ_TABLES)
    resp = await db_client.post(
        "/api/food/search", headers=authed["headers"], json={"keyword": payload, "limit": 20}
    )
    _assert_no_500_nor_leak(resp)
    body = resp.json()
    assert body["code"] == 0
    # 库内无匹配项（conftest 已清空 food），注入不产生额外行
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0
    await _assert_db_intact(db_session, before)


# ---------------------------------------------------------------------------
# 分页参数 page/page_size（整型，非法 → 422/2001）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", SQLI_PAYLOADS, ids=SQLI_IDS)
async def test_pagination_param_injection_rejected(db_client, db_session, authed, payload):
    before = await _row_counts(db_session, _BIZ_TABLES)
    resp = await db_client.get(
        "/api/meal/list",
        headers=authed["headers"],
        params={"page": payload, "page_size": payload},
    )
    _assert_no_500_nor_leak(resp)
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001
    await _assert_db_intact(db_session, before)


# ---------------------------------------------------------------------------
# 筛选类 query 参数：整型枚举（status/post_type）→ 422；日期 date → 422
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", SQLI_PAYLOADS, ids=SQLI_IDS)
async def test_enum_filter_injection_rejected(db_client, db_session, authed, payload):
    before = await _row_counts(db_session, _BIZ_TABLES)
    r1 = await db_client.get(
        "/api/order/list", headers=authed["headers"], params={"status": payload}
    )
    assert r1.status_code == 422 and r1.json()["code"] == 2001
    _assert_no_500_nor_leak(r1)
    r2 = await db_client.get(
        "/api/community/post/list", headers=authed["headers"], params={"post_type": payload}
    )
    assert r2.status_code == 422 and r2.json()["code"] == 2001
    _assert_no_500_nor_leak(r2)
    await _assert_db_intact(db_session, before)


@pytest.mark.parametrize("payload", SQLI_PAYLOADS, ids=SQLI_IDS)
async def test_date_filter_injection_rejected(db_client, db_session, authed, payload):
    before = await _row_counts(db_session, _BIZ_TABLES)
    resp = await db_client.get(
        "/api/meal/list", headers=authed["headers"], params={"date": payload}
    )
    _assert_no_500_nor_leak(resp)
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001
    await _assert_db_intact(db_session, before)


# ---------------------------------------------------------------------------
# 字符串筛选参数（city，ORM 参数化比较）——正常空结果，无泄露
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", SQLI_PAYLOADS, ids=SQLI_IDS)
async def test_string_filter_injection_safe(db_client, db_session, authed, payload):
    before = await _row_counts(db_session, _BIZ_TABLES)
    resp = await db_client.get(
        "/api/community/battle/list", headers=authed["headers"], params={"city": payload}
    )
    _assert_no_500_nor_leak(resp)
    assert resp.json()["code"] == 0
    await _assert_db_intact(db_session, before)


# ---------------------------------------------------------------------------
# 路径参数 id（整型，非法 → 422/2001）
# ---------------------------------------------------------------------------

_PATH_INJECTION_ROUTES = [
    ("get", "/api/community/post/{p}"),
    ("post", "/api/order/{p}/pay"),
    ("delete", "/api/meal/{p}"),
]
_PATH_INJECTION_IDS = [f"{m}_{p}" for m, p in _PATH_INJECTION_ROUTES]


@pytest.mark.parametrize("payload", SQLI_PAYLOADS, ids=SQLI_IDS)
@pytest.mark.parametrize(
    "method,route", _PATH_INJECTION_ROUTES, ids=_PATH_INJECTION_IDS
)
async def test_path_param_id_injection_rejected(
    db_client, db_session, authed, payload, method, route
):
    before = await _row_counts(db_session, _BIZ_TABLES)
    url = route.format(p=payload)
    resp = await getattr(db_client, method)(url, headers=authed["headers"])
    _assert_no_500_nor_leak(resp)
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001
    await _assert_db_intact(db_session, before)
