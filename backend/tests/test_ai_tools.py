"""AI 工具调用工作流测试（agentic chat）：工具执行回填、上下文注入、降级路径。

为何单开文件：现有 test_ai_chat.py 覆盖单轮对话/配额/RAG，本文件覆盖「工具循环」
新行为族（food_info_query 查库 / get_user_status / 多轮回填 / 无凭据与厂商报错降级），
无重复可合并之处。LLM 传输层一律打桩（不联网）。
"""

import json

from app.ai import tools as ai_tools
from app.ai.prompts import AI_DISCLAIMER
from app.models import BodyProfile, Food
from tests.conftest import make_settings


def _seed_food(db_session, name: str, kcal: float) -> None:
    db_session.add(
        Food(name=name, category="水产", calories_100g=kcal, is_standard=True, status=1)
    )
    db_session.commit()


async def test_food_info_query_tool_returns_db_rows(db_session):
    """food_info_query：按关键词命中食物库真实行，输出 JSON；未命中如实带 note。"""
    _seed_food(db_session, "清蒸鲈鱼", 105.0)

    out = json.loads(await ai_tools._tool_food_info_query(db_session, {"keyword": "鲈鱼"}))
    assert out["hits"], "应命中食物库"
    assert "鲈鱼" in out["hits"][0]["name"]
    assert out["hits"][0]["kcal_100g"] == 105.0

    miss = json.loads(
        await ai_tools._tool_food_info_query(db_session, {"keyword": "不存在的菜"})
    )
    assert miss["hits"] == [] and "查不到" in miss["note"]


async def test_run_chat_workflow_executes_tool_and_answers(
    db_session, authed, monkeypatch
):
    """两轮工作流：首轮 LLM 请求查工具 → 后端执行回填 → 次轮给出最终回答。"""
    _seed_food(db_session, "清蒸鲈鱼", 105.0)
    db_session.add(
        BodyProfile(
            user_id=int(authed["user_id"]),
            gender=1,
            height_cm=175.0,
            current_weight=70.0,
            target_weight=65.0,
        )
    )
    await db_session.commit()

    scripted = _ScriptedTransport(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "food_info_query",
                            "arguments": json.dumps(
                                {"keyword": "清蒸鲈鱼"}, ensure_ascii=False
                            ),
                        },
                    }
                ],
            },
            {"role": "assistant", "content": "清蒸鲈鱼约 105kcal/100g，减脂期可以吃。"},
        ]
    )
    monkeypatch.setattr(ai_tools, "_openai_chat_with_tools", scripted)

    reply = await ai_tools.run_chat_workflow(
        db_session,
        int(authed["user_id"]),
        text="清蒸鲈鱼热量高吗？我今天还能吃多少？",
        docs=[],
        settings=make_settings(),
        llm_client=_FakeCompatClient(),
    )
    assert reply.startswith("清蒸鲈鱼约 105kcal/100g") and reply.endswith(AI_DISCLAIMER)
    assert len(scripted.calls) == 2

    # system prompt 注入了用户上下文（DB 真实数据）
    system = scripted.calls[0][0]["content"]
    assert "当前用户上下文" in system and "目标体重 65.0kg" in system

    # 第二轮对话里能看到 role=tool 的查询结果（食物真实行被回填）
    tool_msgs = [m for m in scripted.calls[1] if m.get("role") == "tool"]
    assert tool_msgs and "清蒸鲈鱼" in tool_msgs[0]["content"]


async def test_run_chat_workflow_returns_none_without_credentials(db_session):
    """LLM 客户端不是 OpenAI 兼容（无 base_url/api_key）→ 返回 None，走原单轮链路。"""

    class _Mock:
        model = "mock"

    reply = await ai_tools.run_chat_workflow(
        db_session, 1, text="你好", docs=[], settings=make_settings(), llm_client=_Mock()
    )
    assert reply is None


async def test_run_chat_workflow_provider_error_returns_none(
    db_session, monkeypatch
):
    """厂商不支持 tools / HTTP 报错 → None（调用方走原单轮链路），绝不抛异常。"""
    _seed_food(db_session, "清蒸鲈鱼", 105.0)

    def _boom(*_a, **_k):
        raise RuntimeError("tools unsupported")

    monkeypatch.setattr(ai_tools, "_openai_chat_with_tools", _boom)

    reply = await ai_tools.run_chat_workflow(
        db_session,
        2,
        text="清蒸鲈鱼热量高吗",
        docs=[],
        settings=make_settings(),
        llm_client=_FakeCompatClient(),
    )
    assert reply is None


class _FakeCompatClient:
    """带 OpenAI 兼容三件套属性的假客户端（工作流凭它判定可走工具流）。"""

    base_url = "http://fake"
    api_key = "fake-key"
    model = "fake-model"


class _ScriptedTransport:
    """按脚本逐次返回 message，并记录每次收到的完整 messages（供断言回填结果）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def __call__(self, base_url, api_key, model, messages, tools, *, timeout):  # noqa: ANN001
        self.calls.append(json.loads(json.dumps(messages)))
        return self.responses.pop(0)
