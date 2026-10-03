"""拍照识别「食物匹配」专项测试（F1b：泛化菜名匹配不到食物库 → 摄入被系统性低估）。

覆盖三层，都不过 HTTP（识别链路的 HTTP 契约在 `test_recognize.py`，此处不重复）：
1. `decide_match` 纯决策：阈值 / 并列差距 / 名称精确优先——缺陷的直接成因；
2. `recall_terms` 召回词：整条候选名 + 2 字滑窗（旧实现只按整条名做子串，泛化名必然 0 召回）；
3. 真实种子库上的端到端匹配 + 种子别名文件可解析性（数据半边的修复）。

为何单开文件（AGENTS §2.9）：`test_recognize.py` 的食物用例只播 1–2 行最小数据，
而本 P0 的复现**必须**有完整种子库——「清蒸姜 0.3333 / 清蒸葱 0.3333」这类抢答行正是缺陷本体，
缺了它们任何阈值断言都测不出东西；两种数据前提写进同一文件，只让同一行为在两个层次各测一遍。
种子文件解析断言也放这里：`load_seeds.load_alias` 对不存在的 food_name 是**静默跳过**（只打 warn），
写错食物名不会报错、只会静默丢别名——不测就等于没修。
"""

import csv
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Food
from app.services import recognize_service as rs
from app.services.recognize_service import RecallRow
from tests.test_search_cn import _load_real_food_library

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seeds"

# F1b 补的泛化别名：语义成立（同一道菜的别名）才进库——VLM 泛化菜名 → 种子库真实行。
GENERIC_ALIASES = {
    "白饭": "白米饭",
    "清蒸鱼": "清蒸鲈鱼",
    "蒸鱼": "清蒸鲈鱼",
    "红烧肉": "红烧猪五花",
    "红烧猪肉": "红烧猪五花",
}

# 上一波同批加入、但**不成立**的别名（已撤销）：把不同的菜映射到别的食物的热量上
# （番茄炒蛋→鸡蛋 88kcal 丢了油糖、鱼香肉丝→清炒猪里脊 丢了笋木耳糖醋汁、
#  土豆炖牛肉→清炒牛里脊 143kcal 丢了土豆、宫保鸡丁→酱爆鸡胸肉丝、糖醋里脊→油炸猪里脊）。
# 那是"用错数据掩盖算法问题"：摄入被系统性低估且无从察觉。撤销后这些名字落到
# ambiguous=true + candidates，由用户从候选里确认（§6.3.2 口径）。
WITHDRAWN_ALIASES = frozenset(
    {
        "宫保鸡丁",
        "宫爆鸡丁",
        "鱼香肉丝",
        "番茄炒蛋",
        "西红柿炒鸡蛋",
        "土豆炖牛肉",
        "土豆烧牛肉",
        "糖醋里脊",
    }
)


def _rows(*specs: tuple[int, str, float, bool]) -> list[RecallRow]:
    """(id, name, score, exact) → 候选列表（已按 SQL 的 exact desc, score desc 排好）。"""
    return [
        RecallRow(id=i, name=n, calories_100g=100.0, score=s, exact=e)
        for i, n, s, e in specs
    ]


# 1. 纯决策：阈值与并列


@pytest.mark.parametrize(
    "rows,expect_id,expect_ambiguous",
    [
        ([], None, False),  # 库里确实没有 → 未命中（非"不确定"）
        (_rows((597, "清蒸鲈鱼", 1.0, True)), 597, False),  # 名称逐字相等：无条件采纳
        # 名称精确行优先于同分的别名行（name 非唯一约束，多行同名不猜）
        (_rows((10, "红烧肉", 1.0, True), (11, "红烧肉", 1.0, True)), None, True),
        # 别名精确（score 1.0）压倒一切近似行：这就是补种子后的采纳路径
        (_rows((597, "清蒸鲈鱼", 1.0, False), (1272, "清蒸姜", 0.3333, False)), 597, False),
        # 旧实现的翻车现场：无别名时"清蒸鱼"的最相似行是 41kcal 的清蒸姜，必须拒绝自动采纳
        (_rows((1272, "清蒸姜", 0.3333, False), (597, "清蒸鲈鱼", 0.2857, False)), None, True),
        # 同分并列（清蒸姜 / 清蒸葱 都是 0.3333）：即使阈值放到 0.3 也仍是猜，一并挡掉
        (_rows((1272, "清蒸姜", 0.3333, False), (1286, "清蒸葱", 0.3333, False)), None, True),
        # 过阈值但领先不足 AUTO_ACCEPT_MARGIN(0.05) → 不确定
        (_rows((1, "土豆炖牛腩", 0.5, False), (2, "土豆炖牛肉丸", 0.48, False)), None, True),
        # 过阈值且明显领先 → 采纳（同族菜名，如 土豆炖牛肉 ↔ 土豆炖牛腩 = 0.5）
        (_rows((1, "土豆炖牛腩", 0.5, False), (2, "土豆炖牛肉丸", 0.44, False)), 1, False),
    ],
    ids=[
        "empty",
        "name_exact",
        "two_name_exact_tie",
        "alias_exact_beats_near",
        "all_below_threshold",
        "tied_below_threshold",
        "above_threshold_no_margin",
        "above_threshold_with_margin",
    ],
)
def test_decide_match_acceptance_rules(rows, expect_id, expect_ambiguous):
    # 标定常量判据（任务书硬要求）：清蒸姜/清蒸葱 的 0.3333 必须落在阈值之下，
    # 否则上面 all_below_threshold / tied_below_threshold 两组反例用例失去意义。
    assert rs.AUTO_ACCEPT_SIMILARITY > 0.3334
    outcome = rs.decide_match(rows)
    got_id = outcome.matched.id if outcome.matched else None
    assert (got_id, outcome.ambiguous) == (expect_id, expect_ambiguous)
    # 带回的候选永不含"已采纳"之外的排序变化（前端确认列表要能看到全部召回）
    assert outcome.candidates == rows[: rs.MAX_MATCH_CANDIDATES]


# 2. 召回词：整条 + 2 字滑窗（双向子串在 SQL 侧，见 DB 用例）


@pytest.mark.parametrize(
    "kw,expect",
    [
        ("清蒸鱼", ["清蒸鱼", "清蒸", "蒸鱼"]),  # 旧实现只用整条名 → 命中 0 行
        ("土豆炖牛肉", ["土豆炖牛肉", "土豆", "豆炖", "炖牛", "牛肉"]),
        ("鸡胸", ["鸡胸"]),  # ≤2 字不再切窗，避免召回爆炸
        ("  ", []),
    ],
    ids=["three_char", "long_dish", "two_char", "blank"],
)
def test_recall_terms(kw, expect):
    assert rs.recall_terms(kw) == expect


# 3. 种子别名文件：可解析 + 泛化名有归属（数据半边）


def _read_seed_rows(filename: str) -> list[dict[str, str]]:
    with open(SEED_DIR / filename, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_generic_aliases_resolve_in_seed_files():
    """每条别名都要能按 food_name 落到 food_full.csv 的真实行，且 alias 全局唯一。

    `load_seeds.load_alias` 对找不到的 food_name 静默跳过（DB 侧 alias 还有 UNIQUE 约束），
    拼错一个字的别名不会报错、只会消失——本用例把这条静默路径钉住。
    同时钉住"撤销错配别名"：这 8 条一旦回到种子文件，就意味着又有人拿错热量冒充识别结果。
    """
    food_names = {r["name"].strip() for r in _read_seed_rows("food_full.csv")}
    alias_rows = _read_seed_rows("food_alias_full.csv")
    pairs = [(r["food_name"].strip(), r["alias"].strip()) for r in alias_rows]

    assert [n for n, _ in pairs if n not in food_names] == []
    aliases = [a for _, a in pairs]
    assert len(aliases) == len(set(aliases)), "alias 重复会撞 food_alias.alias UNIQUE"
    by_alias = {a: n for n, a in pairs}
    # 泛化菜名 → 具体行（P0 的数据缺口就在这里）
    assert by_alias.items() >= GENERIC_ALIASES.items()
    # 错配别名不得回归（撤销它们才是 §6.3.2 的正解）——**唯一**硬判据是"别名映射不得错配"
    assert set(WITHDRAWN_ALIASES) & set(by_alias) == set()
    # 同名 food 行**允许且更好**：将来给宫保鸡丁/番茄炒蛋这些常见菜补上自己的食物行
    # （合理热量）时，识别走 exact 无条件采纳，是正解而不是违规——故此处不钉"库里不得有同名行"。


# 4. 真实种子库端到端匹配（缺陷复现的正反两面）

# 实测种子库：清蒸鲈鱼 105kcal / 清蒸姜 41kcal / 清蒸葱 33kcal / 红烧猪五花 554kcal
# （清蒸鱼→清蒸鲈鱼 由 test_match_food_outcome_keeps_adversarial_rows_as_candidates 覆盖，
#   它对同一行为还额外断言了候选里的清蒸姜/清蒸葱不得越阈，这里不再重复较弱的版本）
REAL_LIBRARY_EXPECTATIONS = [
    ("红烧肉", "红烧猪五花"),  # 旧实现：food_id=null
    ("白米饭", "白米饭"),  # 精确同名，本来就正常
    ("清炒上海青", "清炒上海青"),
]


async def test_match_food_on_real_seed_library(db_session):
    """语义成立的泛化名（含补的别名）在真实种子库上必须命中最接近的具体食物（P0 复现）。"""
    await _load_real_food_library(db_session)
    for kw, expect_name in REAL_LIBRARY_EXPECTATIONS:
        outcome = await rs.match_food_outcome(db_session, kw)
        matched = outcome.matched
        assert matched is not None, f"{kw} 仍未命中食物库（会被前端静默丢弃）"
        assert matched.name == expect_name, f"{kw} 命中了 {matched.name}"
        assert matched.calories_100g > 0


@pytest.mark.parametrize(
    "kw,expect_ambiguous,expect_candidates",
    [
        # 滑窗词能召回到近似行 → 交用户确认（§6.3.2）
        ("番茄炒蛋", True, True),  # 番茄酱/番茄/鸡蛋族
        ("鱼香肉丝", True, True),  # 鸡胸肉丝族
        ("土豆炖牛肉", True, True),  # 土豆 + 牛肉族
        ("糖醋里脊", True, True),  # 猪/牛里脊族
        # 库里连近似行都没有 → §2.4（回落模型估算 + 手动搜索 / 自定义食物），不是"不确定"
        ("宫保鸡丁", False, False),
    ],
    ids=["番茄炒蛋", "鱼香肉丝", "土豆炖牛肉", "糖醋里脊", "宫保鸡丁"],
)
async def test_withdrawn_aliases_are_asked_not_guessed(
    db_session, kw, expect_ambiguous, expect_candidates
):
    """撤掉错配别名后，这些菜**不得**再被自动采纳成别的热量行（番茄炒蛋≠鸡蛋 144kcal）。

    落点由召回决定，两种都对：召回到近似行 → `ambiguous=true` + 候选给用户选（§6.3.2）；
    整库无近似行 → `ambiguous=false, candidates=[]`，走 §2.4 手动搜索/自定义食物。
    共同硬判据是 `matched is None`——绝不静默写账。
    """
    await _load_real_food_library(db_session)
    outcome = await rs.match_food_outcome(db_session, kw)
    assert outcome.matched is None, f"{kw} 又被自动采纳为 {outcome.matched.name}"
    assert outcome.ambiguous is expect_ambiguous
    assert bool(outcome.candidates) is expect_candidates
    assert all(c.calories_100g > 0 and c.score >= 0 for c in outcome.candidates)


async def test_match_food_outcome_keeps_adversarial_rows_as_candidates(db_session):
    """反例判据：清蒸姜/清蒸葱（相似度 0.3333，比正确的清蒸鲈鱼还高）只作候选，不得被自动选中。"""
    await _load_real_food_library(db_session)
    outcome = await rs.match_food_outcome(db_session, "清蒸鱼")
    assert outcome.matched is not None and outcome.matched.name == "清蒸鲈鱼"
    assert not outcome.ambiguous
    near = {c.name: c.score for c in outcome.candidates if c.name in ("清蒸姜", "清蒸葱")}
    assert near, "清蒸姜/清蒸葱 应仍在召回里（它们确实是近似行，只是不能自动采纳）"
    assert all(s < rs.AUTO_ACCEPT_SIMILARITY for s in near.values())


async def test_match_food_outcome_returns_candidates_when_uncertain(db_session):
    """库内无该泛化名的别名时：不猜、把候选带回、food_id 为 null（need_confirm 由上层判定）。"""
    await _load_real_food_library(db_session)
    # 「招牌外星汉堡」种子库无此菜；滑窗词「汉堡」会召回「米汉堡」家族——只能作为候选
    outcome = await rs.match_food_outcome(db_session, "招牌外星汉堡")
    assert outcome.matched is None
    assert outcome.ambiguous is True
    assert len(outcome.candidates) == rs.MAX_MATCH_CANDIDATES
    assert all("汉堡" in c.name for c in outcome.candidates)
    assert all(c.score < rs.AUTO_ACCEPT_SIMILARITY for c in outcome.candidates)
    # 真·无召回：候选为空，调用方走 §2.4（回落模型估算 + 手动搜索）
    assert await rs.match_food_outcome(db_session, "银河系能量块") == rs.MatchOutcome(
        matched=None, candidates=[], ambiguous=False
    )
    assert (await rs.match_food_outcome(db_session, "")).matched is None


async def test_match_food_ignores_disabled_rows(db_session):
    """status=0 的行不参与匹配（停用食物不得被自动写入用户的账）。"""
    db_session.add(Food(name="清蒸鱼", calories_100g=105.0, status=0))
    db_session.add(Food(name="清蒸鱼", calories_100g=120.0, status=1))
    await db_session.commit()
    disabled_only = (
        await db_session.execute(select(Food.id).where(Food.status == 0))
    ).scalars().first()
    matched = (await rs.match_food_outcome(db_session, "清蒸鱼")).matched
    assert matched is not None and matched.id != disabled_only and matched.calories_100g == 120.0


async def test_match_food_prefers_alias_target_over_reverse_substring(db_session):
    """反向子串（候选名整条包含更短食物名）不得压过别名/精确行。"""
    rice = Food(name="白米饭", calories_100g=116.0, status=1)
    congee = Food(name="米饭", calories_100g=97.0, status=1)  # 更短且逐字相等
    db_session.add_all([rice, congee])
    await db_session.commit()
    matched = (await rs.match_food_outcome(db_session, "米饭")).matched
    assert matched is not None and matched.name == "米饭"  # 名称精确优先于"白米饭"包含
