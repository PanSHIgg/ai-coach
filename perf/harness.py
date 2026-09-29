"""F5 性能压测器：httpx.AsyncClient + asyncio 并发施压。

统计 QPS / P50 / P95 / P99 / 错误率，对真跑在 8003 的 uvicorn 施压。
并发/时长由参数指定（本机 4GiB / 3 核 → 低并发串行）。

鉴权：直接签发 C 端 JWT（与 uvicorn 同一 JWT_SECRET）；用户/商家/SKU/食物
id 由 perf/seed_ids.json 提供（由 seed_bulk.py 生成）。

用法：
  PY=/workspace/.venv312/bin/python
  $PY perf/harness.py --scenario account_today --concurrency 20 --duration 15
  $PY perf/harness.py --scenario order_create --jwt-secret perf-secret
  $PY perf/harness.py --scenario meal_page --page 5000 --page-size 100
注意：被测服务需禁用限流（RATE_LIMIT_ENABLED=false），否则全局 100/min/IP
会先触发 429。
"""

import argparse
import asyncio
import json
import os
import statistics
import time

import httpx
import jwt

DEFAULT_BASE_URL = "http://127.0.0.1:8003"
DEFAULT_SECRET = "change-me-to-a-random-secret"
DEFAULT_IDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_ids.json")

SCENARIOS = (
    "account_today",
    "food_search",
    "order_create",
    "order_list",
    "meal_page",
    "meal_write",
)


def _load_ids(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _make_token(user_id: int, secret: str, alg: str = "HS256") -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "typ": "access", "iat": now, "exp": now + 7200}
    return jwt.encode(payload, secret, algorithm=alg)


def _build_request(scenario: str, ids: dict, page: int, page_size: int) -> tuple:
    if scenario == "account_today":
        return "GET", "/api/account/today", {}
    if scenario == "food_search":
        return "POST", "/api/food/search", {"json": {"keyword": "鸡胸", "limit": 20}}
    if scenario == "order_create":
        body = {
            "merchant_id": ids["merchant_id"],
            "items": [{"sku_id": ids["sku_id"], "qty": 1}],
        }
        return "POST", "/api/order", {"json": body}
    if scenario == "order_list":
        params = {"page": page, "page_size": page_size}
        return "GET", "/api/order/list", {"params": params}
    if scenario == "meal_page":
        params = {"page": page, "page_size": page_size}
        return "GET", "/api/meal/list", {"params": params}
    if scenario == "meal_write":
        body = {
            "meal_type": 2,
            "food_id": ids["food_id"],
            "amount_g": 1.0,
            "source": 3,
        }
        return "POST", "/api/meal", {"json": body}
    raise SystemExit(f"未知场景: {scenario}（可选 {SCENARIOS}）")


def _percentile(sorted_ms: list, p: float) -> float:
    if not sorted_ms:
        return 0.0
    k = (len(sorted_ms) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_ms) - 1)
    return sorted_ms[lo] + (sorted_ms[hi] - sorted_ms[lo]) * (k - lo)


async def _run(args) -> dict:
    ids = _load_ids(args.ids)
    token = _make_token(ids["user_id"], args.jwt_secret)
    headers = {"Authorization": f"Bearer {token}"}
    method, path, kwargs = _build_request(args.scenario, ids, args.page, args.page_size)

    latencies: list = []
    ok = [0]
    err = [0]
    err_samples: list = []

    limits = httpx.Limits(
        max_connections=args.concurrency + 10,
        max_keepalive_connections=args.concurrency + 10,
    )
    timeout = httpx.Timeout(args.timeout)

    async with httpx.AsyncClient(
        base_url=args.base_url, headers=headers, limits=limits, timeout=timeout
    ) as client:
        for _ in range(3):  # 预热（不计入统计）
            try:
                await client.request(method, path, **kwargs)
            except httpx.HTTPError:
                pass

        deadline = time.perf_counter() + args.duration

        async def worker() -> None:
            while time.perf_counter() < deadline:
                t0 = time.perf_counter()
                try:
                    resp = await client.request(method, path, **kwargs)
                    latencies.append((time.perf_counter() - t0) * 1000.0)
                    body = resp.json()
                    if resp.status_code < 400 and body.get("code") == 0:
                        ok[0] += 1
                    else:
                        err[0] += 1
                        if len(err_samples) < 5:
                            err_samples.append(f"{resp.status_code}/{body.get('code')}")
                except Exception as exc:  # noqa: BLE001 - 压测统计全部失败
                    latencies.append((time.perf_counter() - t0) * 1000.0)
                    err[0] += 1
                    if len(err_samples) < 5:
                        err_samples.append(type(exc).__name__)

        start = time.perf_counter()
        await asyncio.gather(*[worker() for _ in range(args.concurrency)])
        elapsed = time.perf_counter() - start

    total = ok[0] + err[0]
    lat_sorted = sorted(latencies)
    return {
        "scenario": args.scenario,
        "base_url": args.base_url,
        "request": f"{method} {path}",
        "params": kwargs,
        "concurrency": args.concurrency,
        "duration_s": round(elapsed, 2),
        "total": total,
        "ok": ok[0],
        "error": err[0],
        "error_rate_pct": round(err[0] / total * 100, 3) if total else 0.0,
        "qps": round(total / elapsed, 1) if elapsed else 0.0,
        "p50_ms": round(_percentile(lat_sorted, 0.50), 1),
        "p95_ms": round(_percentile(lat_sorted, 0.95), 1),
        "p99_ms": round(_percentile(lat_sorted, 0.99), 1),
        "min_ms": round(lat_sorted[0], 1) if lat_sorted else 0.0,
        "max_ms": round(lat_sorted[-1], 1) if lat_sorted else 0.0,
        "avg_ms": round(statistics.fmean(lat_sorted), 1) if lat_sorted else 0.0,
        "error_samples": err_samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="F5 HTTP 压测器")
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--ids", default=DEFAULT_IDS)
    parser.add_argument("--jwt-secret", default=DEFAULT_SECRET)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--out", default=None, help="结果 JSON 输出路径（可选）")
    args = parser.parse_args()

    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()