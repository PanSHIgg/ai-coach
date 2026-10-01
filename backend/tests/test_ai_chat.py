"""AI 对话（BE4b）：次数扣减与 4001、LLM 降级 6001、RAG 引用、剩余次数、鉴权、20/min 限流。

为何单开文件：本文件覆盖 `/api/ai/chat` + `/api/ai/times` 两个端点所属的一组行为
（配额、降级、RAG、限流），现有测试文件均不涉及 AI 域，无重复可合并之处。

【假设】LLM 一律 mock：patch `httpx.Client.post` 返回 OpenAI 兼容响应
（`choices[0].message.content`），客户端走真实 `_OpenAICompatLLM` 路径，测试不联网。
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.ai.prompts import AI_DISCLAIMER, AI_UNAVAILABLE_FAQ
from app.core.errors import AppException
from app.core.rate_limit import _memory_windows
from app.models import AiDialog, AiKnowledge, UserBenefit
from app.services import ai_service
from tests.conftest import make_settings

_KNOWLEDGE_SOURCE = "test-rag"  # 自插知识条目标记，便于用后清理
_NO_TIMES_MESSAGE = "今日对话次数已用完，邀请好友可解锁更多"
_LLM_REPLY = "先喝一杯水，15 分钟还不饱就吃个水煮蛋。"


def _mock_openai_post(monkeypatch, reply: str, *, error: Exception | None = None) -> None:
    """patch 同步 httpx.Client.post → OpenAI 兼容响应（AI 客户端专用）。

    只 patch 同步 `httpx.Client`，不影响测试栈自身的 `httpx.AsyncClient`（db_client）。
    """

    def fake_post(self, url, *, headers=None, json=None, **kwargs):
        if error is not None:
            raise error
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": reply}}]},
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)


@pytest.fixture
def stub_llm(monkeypatch):
    """mock OpenAI 兼容响应并强制 chat 走真实 `_OpenAICompatLLM` 客户端，避免联网。"""

    def _install(reply: str = _LLM_REPLY, *, error: Exception | None = None):
        _mock_openai_post(monkeypatch, reply, error=error)
        client = ai_service._OpenAICompatLLM(
            "http://llm.test/v1", "test-key", "test-model", timeout=5.0
        )
        monkeypatch.setattr(ai_service, "llm_client_for", lambda s: client)
        return client

    return _install


@pytest.fixture
async def clean_ai_knowledge(db_session):
    """清理本文件插入的知识条目（conftest 不 TRUNCATE ai_knowledge）。"""
    yield
    rows = (
        (
            await db_session.execute(
                select(AiKnowledge.id).where(AiKnowledge.source == _KNOWLEDGE_SOURCE)
            )
        )
        .scalars()
        .all()
    )
    if rows:
        await db_session.execute(AiKnowledge.__table__.delete().where(AiKnowledge.id.in_(rows)))
        await db_session.commit()


async def _dialogs(db_session, user_id: int) -> list[AiDialog]:
    return list(
        (
            await db_session.execute(
                select(AiDialog).where(AiDialog.user_id == user_id).order_by(AiDialog.id)
            )
        )
        .scalars()
        .all()
    )


async def _benefit(db_session, user_id: int) -> UserBenefit:
    return await db_session.scalar(select(UserBenefit).where(UserBenefit.user_id == user_id))


async def test_chat_deducts_times_and_logs_dialog(db_client, db_session, authed, stub_llm):
    """一次对话：10→9，ai_dialog 落 user/assistant 两行，回复带免责声明。"""
    stub_llm()
    session_id = str(uuid.uuid4())
    resp = await db_client.post(
        "/api/ai/chat",
        headers=authed["headers"],
        json={"session_id": session_id, "message": "下午饿了能吃什么"},
    )
    body = resp.json()
    assert (resp.status_code, body["code"]) == (200, 0)
    assert body["data"]["times_left"] == 9
    assert body["data"]["intent"] == "hunger_rescue"
    assert body["data"]["reply"].endswith(AI_DISCLAIMER)

    dialogs = await _dialogs(db_session, authed["user_id"])
    assert [d.role for d in dialogs] == ["user", "assistant"]
    assert {str(d.session_id) for d in dialogs} == {session_id}
    assert dialogs[1].intent == "hunger_rescue"
    assert (await _benefit(db_session, authed["user_id"])).ai_times_left == 9


async def test_chat_no_times_returns_4001(db_client, db_session, authed, stub_llm):
    """次数为 0 → 4001，且不扣成负数。"""
    stub_llm()
    benefit = await _benefit(db_session, authed["user_id"])
    benefit.ai_times_left = 0
    benefit.ai_times_reset_at = datetime.now(UTC)
    await db_session.commit()

    resp = await db_client.post(
        "/api/ai/chat",
        headers=authed["headers"],
        json={"session_id": str(uuid.uuid4()), "message": "饿了能吃什么"},
    )
    body = resp.json()
    assert (resp.status_code, body["code"]) == (409, 4001)
    assert body["message"] == _NO_TIMES_MESSAGE
    await db_session.refresh(benefit)
    assert benefit.ai_times_left == 0


async def test_chat_llm_failure_returns_6001(db_client, db_session, authed, stub_llm):
    """LLM 抛异常 → 6001 + 预设 FAQ，且不扣次数、不落库。"""
    stub_llm(error=RuntimeError("LLM unavailable"))
    resp = await db_client.post(
        "/api/ai/chat",
        headers=authed["headers"],
        json={"session_id": str(uuid.uuid4()), "message": "这菜油多吗"},
    )
    body = resp.json()
    assert (resp.status_code, body["code"]) == (409, 6001)
    assert body["message"] == AI_UNAVAILABLE_FAQ
    assert (await _benefit(db_session, authed["user_id"])).ai_times_left == 10
    assert await _dialogs(db_session, authed["user_id"]) == []


async def test_chat_references_knowledge(
    db_client, db_session, authed, stub_llm, clean_ai_knowledge
):
    """RAG 命中 ai_knowledge → references 含 knowledge:{id}。

    【假设】conftest 不 TRUNCATE `ai_knowledge`，库里常驻 50 条正式语料；提问须只命中本用例
    自插条目，故标题/正文/提问统一带唯一标识词「蓝纹奶酪」（已验证 50 条语料零命中）。
    """
    stub_llm()
    knowledge = AiKnowledge(
        category="加餐",
        title="饿了怎么办（蓝纹奶酪）",
        content="饿了可以先喝水；蓝纹奶酪热量高，优先选水煮蛋、黄瓜这类高蛋白低热量食物。",
        source=_KNOWLEDGE_SOURCE,
    )
    db_session.add(knowledge)
    await db_session.commit()

    resp = await db_client.post(
        "/api/ai/chat",
        headers=authed["headers"],
        json={"session_id": str(uuid.uuid4()), "message": "蓝纹奶酪"},
    )
    assert resp.status_code == 200
    assert f"knowledge:{knowledge.id}" in resp.json()["data"]["references"]


async def test_chat_concurrent_calls_never_exceed_quota(db_client, db_session, authed, stub_llm):
    """并发 N > 额度 次对话：成功次数 == 额度，其余 4001，余额归零。

    回归守卫：`ensure_benefit()` 若在「跨日重置」分支提前 commit，会释放 `FOR UPDATE` 行锁，
    并发请求各自读到同一旧余额 → 丢失更新（名额被超用）。故重置须只 flush，与扣减同事务提交。
    """
    stub_llm()
    quota = make_settings().AI_DAILY_TIMES
    calls = quota + 2

    benefit = await _benefit(db_session, authed["user_id"])
    benefit.ai_times_left = 0
    benefit.ai_times_reset_at = datetime.now(UTC) - timedelta(days=1)  # 使重置分支生效
    await db_session.commit()

    async def _chat() -> int:
        resp = await db_client.post(
            "/api/ai/chat",
            headers=authed["headers"],
            json={"session_id": str(uuid.uuid4()), "message": "饿了能吃什么"},
        )
        return resp.json()["code"]

    codes = await asyncio.gather(*(_chat() for _ in range(calls)))
    assert codes.count(0) == quota
    assert codes.count(4001) == calls - quota

    await db_session.refresh(benefit)
    assert benefit.ai_times_left == 0


async def test_get_times_returns_left(db_client, authed):
    """/api/ai/times 返回剩余次数。"""
    resp = await db_client.get("/api/ai/times", headers=authed["headers"])
    body = resp.json()
    assert (resp.status_code, body["code"]) == (200, 0)
    assert body["data"]["times_left"] == 10


async def test_ai_times_reset_at_midnight(db_client, db_session, authed):
    """ai_times_reset_at 为昨天 → 查询时按 AI_DAILY_TIMES 重置。"""
    benefit = await _benefit(db_session, authed["user_id"])
    benefit.ai_times_left = 0
    benefit.ai_times_reset_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()

    resp = await db_client.get("/api/ai/times", headers=authed["headers"])
    assert resp.status_code == 200
    assert resp.json()["data"]["times_left"] == 10


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/ai/times", {}),
        ("post", "/api/ai/chat", {"json": {"session_id": str(uuid.uuid4()), "message": "饿了"}}),
        ("post", "/api/ai/recommend", {"json": {"meal_type": 2}}),
        # 识别端点是 multipart，body 形态不同，故按 kwargs 传而非统一 json
        ("post", "/api/meal/recognize", {"files": {"image": ("m.jpg", b"x", "image/jpeg")}}),
    ],
    ids=["times", "chat", "recommend", "recognize"],
)
async def test_ai_endpoints_require_auth(db_client, method, path, kwargs):
    """本波四个端点「未带 token → 401/1001」合并为一条（§2.9 反重复，各域不再各写一条）。"""
    resp = await getattr(db_client, method)(path, **kwargs)
    body = resp.json()
    assert (resp.status_code, body["code"]) == (401, 1001)


async def test_chat_rate_limit_20_per_min(db_session, authed, stub_llm):
    """AI 对话 20 次/分钟/用户：第 21 次抛 429（次数配额先放大，隔离限流行为）。"""
    stub_llm()
    # conftest 把 REDIS_URL 指向不可达端口 → 计数落在 rate_limit 的进程内字典，
    # 同一 key 会在 60s 窗口内跨用例累积，先清残留以保证本用例独立。
    _memory_windows.pop(f"ai:chat:user:{authed['user_id']}", None)

    benefit = await _benefit(db_session, authed["user_id"])
    benefit.ai_times_left = 50
    benefit.ai_times_reset_at = datetime.now(UTC)
    await db_session.commit()

    settings = make_settings(RATE_LIMIT_ENABLED=True, RATE_LIMIT_AI_PER_MIN=20)
    for _ in range(20):
        await ai_service.chat(
            db_session,
            user_id=authed["user_id"],
            session_id=str(uuid.uuid4()),
            message="饿了能吃什么",
            settings=settings,
        )
    with pytest.raises(AppException) as excinfo:
        await ai_service.chat(
            db_session,
            user_id=authed["user_id"],
            session_id=str(uuid.uuid4()),
            message="饿了能吃什么",
            settings=settings,
        )
    assert excinfo.value.code == 429
