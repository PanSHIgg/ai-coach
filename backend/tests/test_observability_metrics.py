"""Prometheus 指标埋点测试（F9 / docs/split/08 §10.7）：只测本项目导出的指标面，不联网。

单独成文件的理由：断言对象是 `/metrics` 导出文本（Grafana 面板实际读的口径），
与 `test_ai_provider.py`（协议请求/响应）、`test_account_api.py`（接口返回值）不是一个面。

覆盖：① 厂商成功 → token 三类 + 按牌价折算的成本；② 请求失败 → 只记 degraded 次数、
不产生成本；③ 视觉路径落在 `task="vision"`（`ai_task()` 声明的标签要能穿过线程池到出口）；
④ 两个厂商出口（单轮 `_openai_compatible_chat` 与工具循环 `tools._openai_chat_with_tools`）
同口径记账——chat 走后者，曾经整条 chat 无指标；⑤ 热量直方图只在 `compute_result`
的真实计算上计数；⑥ 装配时预置 AI 子序列（不预置会把首次抓取前的增量当成基线丢掉）。
"""

import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from prometheus_client import REGISTRY, generate_latest

from app.observability import metrics
from app.services import account, ai_service
from tests.conftest import make_settings
from tests.test_account_api import _make_profile

TZ = timezone(timedelta(hours=8))

# 牌价（美元/百万 token）：input 0.2 / cached 0.02 / output 1.1
PRICES = dict(
    AI_PRICE_INPUT_USD_PER_MTOKEN=0.2,
    AI_PRICE_CACHED_INPUT_USD_PER_MTOKEN=0.02,
    AI_PRICE_OUTPUT_USD_PER_MTOKEN=1.1,
)


def _value(name: str, **labels) -> float | None:
    """取导出文本里 `name{...labels...}` 的当前值；序列不存在返回 None（看板侧即 No data）。"""
    for line in generate_latest(REGISTRY).decode().splitlines():
        if line.startswith("#"):
            continue
        head, _, tail = line.rpartition(" ")
        prefix, _, label_text = head.partition("{")
        if prefix != name:
            continue
        got = dict(re.findall(r'(\w+)="([^"]*)"', label_text))
        if labels.items() <= got.items():
            return float(tail)
    return None


def _patch_post(monkeypatch, body: dict) -> None:
    """mock 同步 httpx.Client.post 返回给定 JSON（只 patch 同步 Client，不碰 db_client）。"""

    def fake_post(self, url, **kwargs):
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)


def _chat_body(usage: dict | None, content: str = "先喝水。") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        **({"usage": usage} if usage is not None else {}),
    }


def _call_llm() -> str:
    return ai_service._openai_compatible_chat(
        "http://llm.test/v1",
        "k",
        "deepseek-chat",
        [{"role": "user", "content": "饿了"}],
        timeout=5.0,
    )


def test_successful_call_records_tokens_and_cost(monkeypatch):
    """usage 三类 token 各自计数；成本 = [(1000−200)×0.2 + 200×0.02 + 500×1.1] / 1e6。"""
    monkeypatch.setattr(metrics, "get_settings", lambda: make_settings(**PRICES))
    _patch_post(
        monkeypatch,
        _chat_body(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "prompt_tokens_details": {"cached_tokens": 200},
            }
        ),
    )
    cost_before = _value("ai_cost_usd_total", task="chat") or 0.0
    tokens_before = {
        t: _value("ai_tokens_total", task="chat", type=t) or 0.0
        for t in ("input", "output", "cached")
    }

    _call_llm()

    assert _value("ai_tokens_total", task="chat", type="input") - tokens_before["input"] == 1000
    assert _value("ai_tokens_total", task="chat", type="output") - tokens_before["output"] == 500
    assert _value("ai_tokens_total", task="chat", type="cached") - tokens_before["cached"] == 200
    assert _value("ai_cost_usd_total", task="chat") - cost_before == pytest.approx(714 / 1_000_000)


def test_failed_call_records_degraded_without_cost(monkeypatch):
    """请求侧失败（HTTP 500）：记一次 degraded=true，不动 token 与成本（没花钱的调用）。"""

    def fake_post(self, url, **kwargs):
        return httpx.Response(500, json={"error": "boom"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    degraded_before = _value("ai_calls_total", task="chat", degraded="true") or 0.0
    cost_before = _value("ai_cost_usd_total", task="chat") or 0.0

    with pytest.raises(httpx.HTTPStatusError):
        _call_llm()

    assert _value("ai_calls_total", task="chat", degraded="true") - degraded_before == 1
    assert _value("ai_cost_usd_total", task="chat") == cost_before


def test_vision_path_is_labelled_vision(monkeypatch):
    """VLM 客户端自带 task=vision 作用域（拍照识别与对话图片描述共用该出口）。"""
    _patch_post(
        monkeypatch,
        _chat_body({"prompt_tokens": 7, "completion_tokens": 3}, content='{"items": []}'),
    )
    before = _value("ai_calls_total", task="vision", degraded="false") or 0.0
    client = ai_service._OpenAICompatVLM("http://vlm.test/v1", "k", "v-1", timeout=5.0)

    client.recognize_food(b"fake-image")

    assert _value("ai_calls_total", task="vision", degraded="false") - before == 1
    assert _value("ai_tokens_total", task="vision", type="input") is not None


def test_tools_loop_exit_records_under_declared_task(monkeypatch):
    """工具循环出口（`app/ai/tools.py`）与单轮出口同口径：漏记的那个洞就是 chat 无数据。"""
    from app.ai import tools

    _patch_post(
        monkeypatch,
        _chat_body({"prompt_tokens": 40, "completion_tokens": 8}, content="先喝水。"),
    )
    calls_before = _value("ai_calls_total", task="chat", degraded="false") or 0.0
    tokens_before = _value("ai_tokens_total", task="chat", type="input") or 0.0

    with metrics.ai_task("chat"):
        tools._openai_chat_with_tools(
            "http://llm.test/v1", "k", "m", [], [], timeout=5.0
        )

    assert _value("ai_calls_total", task="chat", degraded="false") - calls_before == 1
    assert _value("ai_tokens_total", task="chat", type="input") - tokens_before == 40


def test_prime_ai_counters_makes_children_exist_before_any_call():
    """装配即预置：AI 子序列必须已经导出（哪怕一次调用都没发生）。

    不预置会丢数据——Prometheus 把「序列首次出现」当基线，首次抓取前发生的增量
    算不出来（实测：一次提问连调 3 次落在同一个 15s 抓取间隙里，`increase` 恒 0）。
    """
    metrics.prime_ai_counters()
    text = generate_latest(REGISTRY).decode()

    for task in metrics.AI_TASKS:
        assert f'ai_calls_total{{degraded="false",task="{task}"}}' in text
        assert f'ai_cost_usd_total{{task="{task}"}}' in text
        for token_type in metrics.AI_TOKEN_TYPES:
            assert f'ai_tokens_total{{task="{task}",type="{token_type}"}}' in text
    # 未被任何用例调用过的任务，预置值必须是 0（有值说明预置把别处的计数覆盖了）
    assert 'ai_calls_total{degraded="false",task="weekly_comment"} 0' in text


async def test_compute_result_observes_calorie_histogram(db_session, authed):
    """热量直方图在 account.compute_result 的真实调用上计数（埋点不含取数的 DB 等待）。"""
    uid = authed["user_id"]
    await _make_profile(db_session, uid)
    count_before = _value("calorie_calc_seconds_count") or 0.0

    await account.compute_result(db_session, uid, datetime.now(TZ).date())

    assert (_value("calorie_calc_seconds_count") or 0.0) > count_before
