"""拍照识别测试（Phase 2 BE4a）。

独立成文理由：`/api/meal/recognize` 是 BE4a 新增行为，现有 `test_meal.py` 只覆盖 Phase 1 的
饮食记录 CRUD，混写会稀释该文件主题；`test_food_search.py` 覆盖的是搜索列表，与识别无关。

分层（禁止真实联网，VLM 一律本地 mock）：
- 纯逻辑：食物表命中/未命中的热量来源、need_confirm 判定、候选归一化与条数上限——不连库不联网；
- 接口行为：multipart 上传结构、入参 422、AI 异常降级 6001——走 db_client + authed。
  （401 鉴权与其它本波端点合并为 `test_ai_chat.py::test_ai_endpoints_require_auth`，见 §2.9）
"""

import json

import httpx
import pytest

from app.models import Food, FoodAlias
from app.services import recognize_service as rs


def _patch_vlm(monkeypatch, items: list[dict] | None = None, error: Exception | None = None):
    """mock VLM：patch 同步 httpx.Client.post → OpenAI 兼容响应（content 为识别 JSON 文本）。

    强制走真实 `_OpenAICompatVLM` 路径（monkeypatch `vision_client_for`），不联网；
    只 patch 同步 `httpx.Client`，不影响测试栈自身的 `httpx.AsyncClient`（db_client）。
    """

    def fake_post(self, url, *, headers=None, data=None, **kwargs):
        if error is not None:
            raise error
        content = json.dumps({"items": items or []}, ensure_ascii=False)
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": content}}]},
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    client = rs._OpenAICompatVLM("http://vlm.test/v1", "test-key", "test-vlm", timeout=5.0)
    monkeypatch.setattr(rs, "vision_client_for", lambda settings: client)


async def _seed_food(db_session, name: str, kcal_100g: float) -> Food:
    food = Food(name=name, calories_100g=kcal_100g, status=1)
    db_session.add(food)
    await db_session.commit()
    return food


def _upload(filename: str = "meal.jpg", size: int = 1024) -> dict:
    return {"image": (filename, b"x" * size, "image/jpeg")}


# 纯逻辑


@pytest.mark.parametrize(
    "matched,expect",
    [
        (rs.MatchedFood(id=208, name="清蒸鱼", calories_100g=120.0), (208, "清蒸鱼", 180.0)),
        (None, (rs.UNMATCHED_FOOD_ID, "清蒸鱼", 300.0)),
    ],
    ids=["matched", "unmatched"],
)
def test_build_item_calorie_source(matched, expect):
    candidate = rs.Candidate(name="清蒸鱼", confidence=0.92, portion_g=150.0, kcal_100g=200.0)
    item = rs.build_item(candidate, matched)
    assert (item.food_id, item.name, item.calories) == expect


@pytest.mark.parametrize(
    "items,expect",
    [
        ([rs.Candidate("红烧肉", 0.61, 100.0, 480.0)], True),  # 置信度低于 0.7
        ([rs.Candidate("清蒸鱼", 0.92, 150.0, 120.0)], False),  # 命中且置信度达标
        ([rs.Candidate("米饭", 0.95, 100.0, 116.0)], True),  # 高置信但未命中 food 表
    ],
    ids=["low_confidence", "confirmed", "unmatched"],
)
def test_resolve_need_confirm(items, expect):
    built = [
        rs.build_item(c, None if c.name == "米饭" else rs.MatchedFood(1, c.name, 120.0))
        for c in items
    ]
    assert rs.resolve_need_confirm(built, 0.7) is expect


def test_normalize_candidates_caps_and_converts_calorie_estimate():
    # Mock 客户端形态（只有总 kcal）+ 超过 5 条 → 截断；份量缺失 → 默认 150g
    raw = [{"name": f"菜{i}", "confidence": 0.9, "calorie_estimate": 300} for i in range(6)]
    items = rs.normalize_candidates(raw)
    assert len(items) == rs.MAX_ITEMS
    assert items[0] == rs.Candidate(name="菜0", confidence=0.9, portion_g=150.0, kcal_100g=200.0)


# 接口行为


async def test_recognize_matches_food_table(db_client, db_session, authed, monkeypatch):
    fish = await _seed_food(db_session, "清蒸鱼", 120.0)
    rice = await _seed_food(db_session, "米饭", 116.0)
    _patch_vlm(
        monkeypatch,
        items=[
            {"name": "清蒸鱼", "confidence": 0.92, "portion_g": 150, "kcal_100g": 999},
            {"name": "米饭", "confidence": 0.75, "portion_g": 100, "kcal_100g": 999},
        ],
    )
    resp = await db_client.post("/api/meal/recognize", headers=authed["headers"], files=_upload())
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    data = body["data"]
    assert data["request_id"] == body["request_id"] != ""
    # 命中 food 表：热量按表里的 calories_100g 算，而非模型给的 999
    assert [(i["food_id"], i["name"], i["calories"]) for i in data["items"]] == [
        (fish.id, "清蒸鱼", 180.0),
        (rice.id, "米饭", 116.0),
    ]
    assert data["need_confirm"] is False
    # 契约口径：已自动命中的条目 candidates 恒为空数组（内部召回行只用于判并列，不外泄）
    assert [(i["ambiguous"], i["candidates"]) for i in data["items"]] == [(False, [])] * 2


async def test_recognize_matches_food_alias(db_client, db_session, authed, monkeypatch):
    """兜底路径：视觉给的是别名，须经 food_alias 命中到同一条食物。"""
    food = await _seed_food(db_session, "番茄炒蛋", 88.0)
    db_session.add(FoodAlias(food_id=food.id, alias="西红柿炒鸡蛋"))
    await db_session.commit()
    _patch_vlm(
        monkeypatch,
        items=[{"name": "西红柿炒鸡蛋", "confidence": 0.95, "portion_g": 200, "kcal_100g": 0}],
    )
    body = (
        await db_client.post("/api/meal/recognize", headers=authed["headers"], files=_upload())
    ).json()["data"]
    assert body["items"][0]["food_id"] == food.id
    assert body["items"][0]["calories"] == 176.0
    assert body["need_confirm"] is False


async def test_recognize_unmatched_item_needs_confirm(db_client, db_session, authed, monkeypatch):
    _patch_vlm(
        monkeypatch,
        items=[{"name": "招牌外星汉堡", "confidence": 0.95, "portion_g": 100, "kcal_100g": 480}],
    )
    body = (
        await db_client.post("/api/meal/recognize", headers=authed["headers"], files=_upload())
    ).json()["data"]
    item = body["items"][0]
    assert item["food_id"] is None  # 未命中 food 表 → null（契约 nullable）
    assert item["calories"] == 480.0  # 回落模型估算
    assert body["need_confirm"] is True
    # 库里连近似行都没有（本用例不播食物数据）→ 不是"等用户确认"，走 §2.4 手动搜索/自定义食物
    assert item["ambiguous"] is False
    assert item["candidates"] == []


async def test_recognize_ambiguous_item_carries_candidates(
    db_client, db_session, authed, monkeypatch
):
    """召回到近似行但不确定 → `ambiguous=true` + `candidates` 必须进响应体（§6.3.2 让用户选）。

    分层（§2.9）：反例行为本身（清蒸姜/清蒸葱 抢答、阈值 0.5）已在
    `test_recognize_matching.py` 的决策层与 DB 层各测一次，此处只测**响应投影**——
    `MatchOutcome.candidates` → `RecognizedItem.candidates`（`id` 改名 `food_id`）这条新链路，
    别的层次看不到。
    """
    ginger = await _seed_food(db_session, "清蒸姜", 41.0)
    scallion = await _seed_food(db_session, "清蒸葱", 33.0)
    _patch_vlm(
        monkeypatch,
        items=[{"name": "清蒸鱼", "confidence": 0.95, "portion_g": 100, "kcal_100g": 105}],
    )
    body = (
        await db_client.post("/api/meal/recognize", headers=authed["headers"], files=_upload())
    ).json()["data"]
    item = body["items"][0]
    assert item["food_id"] is None
    assert item["ambiguous"] is True
    assert {c["food_id"]: c["name"] for c in item["candidates"]} == {
        ginger.id: "清蒸姜",
        scallion.id: "清蒸葱",
    }
    assert {c["calories_100g"] for c in item["candidates"]} == {41.0, 33.0}
    # 候选分数全部低于自动采纳阈值——否则它们早该被采纳，而不是让用户选
    assert all(0 <= c["score"] < rs.AUTO_ACCEPT_SIMILARITY for c in item["candidates"])
    assert item["calories"] == 105.0  # 未采纳 → 仍按模型估算，need_confirm 为 True
    assert body["need_confirm"] is True


async def test_recognize_ai_unavailable_6001(db_client, db_session, authed, monkeypatch):
    _patch_vlm(monkeypatch, error=httpx.ReadTimeout("AI 超时"))
    resp = await db_client.post("/api/meal/recognize", headers=authed["headers"], files=_upload())
    assert resp.status_code == 409
    assert resp.json()["code"] == 6001
    assert resp.json()["message"] == "没看清，换个角度再拍或手动搜索"


@pytest.mark.parametrize(
    "files",
    [
        {"image": ("empty.jpg", b"", "image/jpeg")},  # 空文件
        {"image": ("note.txt", b"hello", "text/plain")},  # 非图片
        {"image": ("big.jpg", b"x" * (5 * 1024 * 1024 + 1), "image/jpeg")},  # 超 5MB
    ],
    ids=["empty", "not_image", "oversize"],
)
async def test_recognize_rejects_invalid_image(db_client, db_session, authed, files):
    resp = await db_client.post("/api/meal/recognize", headers=authed["headers"], files=files)
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001
