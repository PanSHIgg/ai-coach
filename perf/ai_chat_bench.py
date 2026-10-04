"""AI 对话压测：50 次调用，每次间隔 2s（串行）。

对照 docs/AI饮食管控教练_全栈开发交付文档.md 9.4「AI 对话 P95 < 3s」。
串行而非并发：AI 是外部 API，串行才能反映单次真实延迟（并发会互相排队）。
"""
import json
import pathlib
import statistics
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8003"
JWT_SECRET = "perf-secret-hs256-key-0123456789"
HERE = pathlib.Path(__file__).resolve().parent
TOTAL = 50
INTERVAL = 2.0
# 同一 session 串 50 轮：贴近真实用户连续追问，也顺带验证多轮上下文拼接
SESSION_ID = str(uuid.uuid4())

# 真实用户视角的提问，覆盖不同类型（避免全是同一句导致缓存/偏置）
QUESTIONS = [
    "我今天早餐吃了两个包子，热量大概多少？",
    "晚上吃火锅会不会太胖？",
    "减脂期能喝奶茶吗？",
    "我最近体重一直不降，是不是平台期了？",
    "鸡胸肉和牛肉哪个更适合减脂？",
    "每天要喝多少水才够？",
    "我饿了想吃零食，有什么低卡选择？",
    "运动后应该马上吃东西吗？",
    "我今天走了 8000 步，还需要额外运动吗？",
    "外卖怎么点比较健康？",
]

import jwt  # noqa: E402

now = int(time.time())
token = jwt.encode(
    {"sub": str(1), "typ": "access", "iat": now, "exp": now + 7200},
    JWT_SECRET, algorithm="HS256",
)
HEADERS = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def pct(sorted_ms, p):
    if not sorted_ms:
        return 0.0
    k = (len(sorted_ms) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_ms) - 1)
    return sorted_ms[lo] + (sorted_ms[hi] - sorted_ms[lo]) * (k - lo)


def one_call(client, idx, question):
    # session_id 必填（uuid），ai_service 用它串联多轮上下文
    body = {"session_id": SESSION_ID, "message": question}
    t0 = time.perf_counter()
    try:
        r = client.post(f"{BASE}/api/ai/chat", json=body, headers=HEADERS, timeout=60.0)
        dt = (time.perf_counter() - t0) * 1000
        payload = r.json()
        code = payload.get("code")
        data = payload.get("data") or {}
        # 判定是否走了降级：6001 = AI 不可用/超时降级
        degraded = (code == 6001)
        reply = (data.get("reply") or data.get("content") or "")
        return {
            "idx": idx, "ok": r.status_code == 200 and code == 0,
            "http": r.status_code, "code": code, "ms": dt,
            "degraded": degraded, "reply_len": len(reply),
            "reply_head": reply[:60].replace("\n", " "),
            "times_left": data.get("ai_times_left"),
        }
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000
        return {
            "idx": idx, "ok": False, "http": None, "code": None, "ms": dt,
            "degraded": None, "reply_len": 0,
            "reply_head": f"{type(e).__name__}: {str(e)[:70]}",
            "times_left": None,
        }


def main():
    print(f"=== AI 对话压测：{TOTAL} 次，每次间隔 {INTERVAL}s（串行）===")
    print(f"endpoint: {BASE}/api/ai/chat")
    print(f"启动时刻: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    results = []
    with httpx.Client() as client:
        # 预热：不计入统计（首次调用含连接建立 + RAG 检索初始化）
        print("预热一次（不计入统计）...")
        w = one_call(client, 0, "你好")
        print(f"  预热结果: http={w['http']} code={w['code']} {w['ms']:.0f}ms "
              f"degraded={w['degraded']} reply='{w['reply_head']}'")
        if w["degraded"]:
            print("  ⚠️ 预热即降级（code 6001）—— AI 链路不可用，后续数据无参考价值")
        print()

        print(f"{'#':>3} {'http':>5} {'code':>5} {'ms':>9}  {'降级':>4}  {'配额':>4}  reply")
        print("-" * 100)
        for i in range(1, TOTAL + 1):
            q = QUESTIONS[(i - 1) % len(QUESTIONS)]
            res = one_call(client, i, q)
            results.append(res)
            print(f"{res['idx']:>3} {str(res['http']):>5} {str(res['code']):>5} "
                  f"{res['ms']:>9.0f}  {str(res['degraded']):>4}  "
                  f"{str(res['times_left']):>4}  {res['reply_head'][:44]}")
            if i < TOTAL:
                time.sleep(INTERVAL)

    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    degraded = [r for r in results if r.get("degraded")]
    lat = sorted(r["ms"] for r in ok) or [0.0]
    all_lat = sorted(r["ms"] for r in results)

    print()
    print("=" * 70)
    print("汇总")
    print("=" * 70)
    print(f"总调用      : {len(results)}")
    print(f"成功(code=0): {len(ok)}")
    print(f"失败        : {len(bad)}")
    print(f"降级(6001)  : {len(degraded)}")
    print(f"错误率      : {len(bad)/len(results)*100:.1f}%")
    print()
    print("--- 延迟（仅成功调用）---")
    print(f"  min  : {min(lat):.0f}ms")
    print(f"  P50  : {pct(lat, 0.50):.0f}ms")
    print(f"  P95  : {pct(lat, 0.95):.0f}ms")
    print(f"  P99  : {pct(lat, 0.99):.0f}ms")
    print(f"  max  : {max(lat):.0f}ms")
    print(f"  avg  : {statistics.mean(lat):.0f}ms")
    print()
    print("--- 对照文档 9.4「AI 对话 P95 < 3s」---")
    p95 = pct(lat, 0.95)
    print(f"  实测 P95 = {p95:.0f}ms   阈值 = 3000ms   "
          f"{'PASS' if p95 < 3000 else 'FAIL'}")
    print(f"  (AI_TIMEOUT 配置上限 5s，超时应降级返回 6001)")

    if bad:
        print("\n--- 失败样本 ---")
        for r in bad[:5]:
            print(f"  #{r['idx']}: http={r['http']} code={r['code']} {r['reply_head']}")
    if degraded:
        print("\n--- 降级样本（说明走了兜底，非真实模型）---")
        for r in degraded[:3]:
            print(f"  #{r['idx']}: {r['ms']:.0f}ms {r['reply_head']}")

    out = HERE / "ai_chat_result.json"
    out.write_text(json.dumps({
        "total": len(results), "ok": len(ok), "bad": len(bad),
        "degraded": len(degraded), "interval_s": INTERVAL,
        "p50_ms": round(pct(lat, 0.5), 1), "p95_ms": round(p95, 1),
        "p99_ms": round(pct(lat, 0.99), 1), "max_ms": round(max(lat), 1),
        "avg_ms": round(statistics.mean(lat), 1),
        "spec_p95_under_3000": p95 < 3000,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
