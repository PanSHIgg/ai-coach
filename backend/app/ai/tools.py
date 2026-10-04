"""AI 工具调用工作流（agentic chat）——「问教练」从单轮问答升级为可查库的工具循环。

流程（MAX_TOOL_ROUNDS 轮内）：
1. system prompt 注入**用户上下文**（档案 + 今日热量账户，全部来自 DB，非 LLM 编造）；
2. LLM 可调用工具：
   - food_info_query(keyword)：查食物库营养信息（热量/蛋白/脂肪/碳水/GI）；
   - get_user_status()：查当前用户今日摄入 / TEE / 还能吃多少 / 步数；
   后端执行工具并把 JSON 结果以 role=tool 回填对话；
3. LLM 给出最终回答 → 返回文本；轮次用尽 / 厂商不支持 tools / 超时 / 结构坏 → 返回 None，
   调用方（ai_service.chat）走原单轮链路（行为与旧版完全一致）。

设计原则（为什么不把数字交给 LLM）：
- 数字可信：热量 / 摄入 / 额度一律来自 DB 重算，LLM 只负责解释与建议；
- 防幻觉：食物查询只回 DB 真实行，查不到就如实说查不到；
- 可降级：工具流是增强而非依赖，关闭后行为与旧版完全一致。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts import AI_COACH_SYSTEM_PROMPT, AI_DISCLAIMER
from app.core.config import Settings
from app.core.errors import AppException
from app.models import BodyProfile, Food, FoodAlias
from app.services import account

MAX_TOOL_ROUNDS = 3  # 一次提问内 LLM 最多发起的工具调用轮数（防死循环打爆费用）
MAX_FOOD_HITS = 5
MAX_GRAMS = 400  # 与推荐侧克数上界一致

FOOD_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "food_info_query",
            "description": (
                "按关键词查询食物库的营养信息（热量/蛋白/脂肪/碳水/GI），"
                "适合回答「这个菜热量高吗」「XX 能吃吗」「帮我查一下 XX」类问题"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "食物关键词，如 鲈鱼 / 红烧肉 / 燕麦"},
                    "limit": {"type": "integer", "description": "返回条数上限，默认 5"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_status",
            "description": "查询当前用户今日热量账户（已摄入 / 总消耗 TEE / 还能吃多少 / 步数）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ---------- 用户上下文（system prompt 注入，全部来自 DB） ----------


async def _user_context(session: AsyncSession, user_id: int) -> str:
    parts: list[str] = []
    profile = (
        await session.execute(
            select(BodyProfile).where(BodyProfile.user_id == user_id).limit(1)
        )
    ).scalar_one_or_none()
    if profile is not None:
        parts.append(f"身高 {float(profile.height_cm):.0f}cm")
        if profile.current_weight:
            parts.append(f"当前体重 {float(profile.current_weight):.1f}kg")
        if profile.target_weight:
            parts.append(f"目标体重 {float(profile.target_weight):.1f}kg")
        if profile.birth_year:
            parts.append(f"{datetime.now().year - int(profile.birth_year)} 岁")
        parts.append({1: "男", 2: "女"}.get(int(profile.gender), ""))
    else:
        parts.append("未建档（无身高体重信息，涉及热量计算时提示用户先建档）")
    try:
        result = await account.compute_result(session, user_id, datetime.now(account.TZ).date())
        parts.append(f"今日已摄入 {float(result.intake):.0f} kcal")
        parts.append(f"今日总消耗 TEE {float(result.tee):.0f} kcal")
        parts.append(f"今天还能吃 {float(result.today_left):.0f} kcal")
        parts.append(f"今日步数 {result.steps}")
    except AppException:
        parts.append("今日热量账户不可用（未建档）")
    return "\n".join(f"- {p}" for p in parts if p)


def _system_prompt(user_context: str) -> str:
    return (
        f"{AI_COACH_SYSTEM_PROMPT}\n\n"
        "# 当前用户上下文（来自数据库的真实数据，回答时直接引用，禁止编造）\n"
        f"{user_context}\n\n"
        "# 工具使用说明\n"
        "- 涉及具体食物的热量 / 营养成分时，先调用 food_info_query 查库，不要凭记忆报数\n"
        "- 涉及「我今天吃了多少 / 还能吃多少」时，先调用 get_user_status\n"
        "- 上下文里已有的信息直接引用，不必重复查询\n"
        "- 查不到的食物如实说明，不要编造营养数据\n"
    )


# ---------- 工具实现（只读，全部返回 JSON 字符串） ----------


def _food_rows(rows: list[Food]) -> list[dict[str, Any]]:
    return [
        {
            "name": f.name,
            "category": f.category or "",
            "kcal_100g": round(float(f.calories_100g), 1),
            "protein_100g": round(float(f.protein_100g or 0), 1),
            "fat_100g": round(float(f.fat_100g or 0), 1),
            "carb_100g": round(float(f.carb_100g or 0), 1),
            "gi": f.gi,
        }
        for f in rows
    ]


async def _tool_food_info_query(session: AsyncSession, args: dict[str, Any]) -> str:
    keyword = str(args.get("keyword", "")).strip()[:64]
    try:
        limit = min(max(int(args.get("limit") or MAX_FOOD_HITS), 1), 10)
    except (TypeError, ValueError):
        limit = MAX_FOOD_HITS
    if not keyword:
        return json.dumps({"hits": [], "note": "关键词为空"}, ensure_ascii=False)
    stmt = (
        select(Food)
        .outerjoin(FoodAlias, FoodAlias.food_id == Food.id)
        .where(
            Food.status == 1,
            or_(Food.name.ilike(f"%{keyword}%"), FoodAlias.alias.ilike(f"%{keyword}%")),
        )
        .order_by(Food.is_standard.desc(), Food.id)
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    payload = {"hits": _food_rows(rows)}
    if not rows:
        payload["note"] = "食物库中没有匹配项，请如实告知用户查不到"  # type: ignore[assignment]
    return json.dumps(payload, ensure_ascii=False)


async def _tool_get_user_status(session: AsyncSession, user_id: int) -> str:
    try:
        result = await account.compute_result(session, user_id, datetime.now(account.TZ).date())
    except AppException:
        return json.dumps({"profile": "未建档，无热量账户"}, ensure_ascii=False)
    return json.dumps(
        {
            "intake_kcal": round(float(result.intake), 1),
            "tee_kcal": round(float(result.tee), 1),
            "today_left_kcal": round(float(result.today_left), 1),
            "steps": result.steps,
        },
        ensure_ascii=False,
    )


async def _execute_tool(
    session: AsyncSession, user_id: int, name: str, args: dict[str, Any], settings: Settings
) -> str:
    """工具分发：任何工具内部异常都转成 JSON error 回给 LLM（让它向用户解释），不中断循环。"""
    try:
        if name == "food_info_query":
            return await _tool_food_info_query(session, args)
        if name == "get_user_status":
            return await _tool_get_user_status(session, user_id)
        return json.dumps({"error": f"unknown tool {name}"}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 - 工具失败以 error 结果回填，由 LLM 决定如何回应
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


# ---------- OpenAI 兼容 tools 调用（与 ai_service._openai_compatible_chat 同构，多 tools/回填） ----------


def _openai_chat_with_tools(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    timeout: float,
) -> dict[str, Any]:
    """同步 httpx（调用方放线程池）：返回 choices[0].message（含 content 与/或 tool_calls）。"""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "temperature": 0.5,
        "max_tokens": 1024,
        "enable_thinking": False,
    }
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=3.0)) as client:
        resp = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]


# ---------- 工作流主入口 ----------


async def run_chat_workflow(
    session: AsyncSession,
    user_id: int,
    *,
    text: str,
    docs: list[Any],
    settings: Settings,
    llm_client: Any,
) -> str | None:
    """工具调用工作流：成功返回最终回答；不可用（无 OpenAI 兼容端点 / 不支持 tools /
    超时 / 结构坏 / 轮次用尽）返回 None，调用方走原单轮链路。本函数不抛异常。"""
    base_url = str(getattr(llm_client, "base_url", "") or "")
    api_key = str(getattr(llm_client, "api_key", "") or "")
    model = str(getattr(llm_client, "model", "") or "")
    if not (base_url and api_key and model):
        return None  # Mock / 非兼容客户端：工具流不可用

    try:
        user_context = await _user_context(session, user_id)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _system_prompt(user_context)},
        ]
        if docs:
            knowledge = "\n".join(
                f"- [{getattr(d, 'id', '')}] "
                f"{(getattr(d, 'title', None) or '')} {(getattr(d, 'content', None) or '')}"[:300]
                for d in docs
            )
            messages.append({"role": "system", "content": f"# 知识库检索结果\n{knowledge}"})
        messages.append({"role": "user", "content": text})

        for _ in range(MAX_TOOL_ROUNDS):
            try:
                message = await asyncio.to_thread(
                    _openai_chat_with_tools,
                    base_url,
                    api_key,
                    model,
                    messages,
                    FOOD_TOOLS,
                    timeout=settings.AI_TIMEOUT,
                )
            except Exception:
                return None  # 厂商不支持 tools / 超时 / HTTP 错误 → 原单轮链路
            tool_calls = message.get("tool_calls")
            if not tool_calls:
                content = (message.get("content") or "").strip()
                if not content:
                    return None
                # §6：所有 AI 输出必须带免责声明（与单轮 generate_reply 同口径）
                if AI_DISCLAIMER not in content:
                    content = f"{content}{AI_DISCLAIMER}"
                return content
            messages.append(
                {"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls}
            )
            for tc in tool_calls:
                fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                result = await _execute_tool(
                    session, user_id, str(fn.get("name") or ""), args, settings
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tc.get("id") or "", "content": result}
                )
        return None  # 轮次用尽仍未给最终答复
    except Exception:  # noqa: BLE001 - 工作流任何意外都退回单轮链路，绝不阻断对话
        return None
