"""契约一致性门禁（Phase 5 · F2「接口冻结」，plan.md §11 F2）。

**为何单开文件**（AGENTS §2.9）：`contracts/` 由主 Agent 单点冻结，此前**没有任何自动化
门禁**阻止「后端实现 ↔ `contracts/openapi.yaml` ↔ TS 双副本 ↔ Mock」四处漂移；本文件把
四处一致性收敛为同一「契约一致性」行为族的一组门禁用例，现有测试文件无一覆盖契约层，
不存在可容纳它的既有文件，也无重复可合并之处。

覆盖四类断言：
1) 后端 `app.openapi()` ↔ `contracts/openapi.yaml`：路径集合与每路径 method 集合双向一致
   （当前冻结基线 109 路径 / 118 ops）；
2) 两份 TS 副本 `contracts/ts/api.d.ts` 与 `miniapp/src/types/api.d.ts` 逐字一致；
3) `contracts/mock/routes.mjs` 覆盖契约全部 method+path（node 解析，缺失时回退正则）；
4) 契约内 `$ref`（`#/components/**`）目标存在，防悬空引用。
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "contracts" / "openapi.yaml"
TS_PRIMARY = REPO_ROOT / "contracts" / "ts" / "api.d.ts"
TS_COPY = REPO_ROOT / "miniapp" / "src" / "types" / "api.d.ts"
MOCK_ROUTES = REPO_ROOT / "contracts" / "mock" / "routes.mjs"

# 冻结基线（Phase 5 F2；变更契约须由主 Agent 显式更新此值并同步三处）
# F-05：新增 POST /api/admin/sku-catalog 与 PUT /api/admin/sku-catalog/{id} -> 路径 73 / ops 80
# F-02：新增 POST /api/food/custom -> 路径 74 / ops 81
# F-01：新增 POST /api/account/today-status -> 路径 75 / ops 82
# G1/G2：真人教练工单 + 平台自营订阅付费 -> 路径 89 / ops 96
# Wave A 地基：任务/积分 · 隐私 · 报告 · 语音 · 商家比价/自助（+18 路径 / +20 ops）
#   -> 路径 107 / ops 116
# COS 集成：POST /api/upload/credential（STS 直传凭证）+ POST /api/user/avatar（更新头像）
#   -> 路径 109 / ops 118
FROZEN_PATH_COUNT = 109
FROZEN_OP_COUNT = 118

_METHODS = ("get", "post", "put", "delete", "patch", "options", "head")


def _load_contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _backend_methods_by_path() -> dict[str, set[str]]:
    """从后端 FastAPI 应用导出 openapi()，取「路径 -> HTTP method 集合」。"""
    from app.main import create_app
    from tests.conftest import make_settings

    spec = create_app(make_settings()).openapi()
    return {path: {m for m in ops if m in _METHODS} for path, ops in spec["paths"].items()}


def _contract_methods_by_path() -> dict[str, set[str]]:
    return {
        path: {m for m in ops if m in _METHODS} for path, ops in _load_contract()["paths"].items()
    }


_BACKEND = _backend_methods_by_path()
_CONTRACT = _contract_methods_by_path()
_ALL_PATHS = sorted(set(_BACKEND) | set(_CONTRACT))


# ---------------------------------------------------------------------------
# 1) 后端实现 ↔ 契约：路径集合 + method 集合（双向）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _ALL_PATHS, ids=_ALL_PATHS)
def test_backend_and_contract_methods_match(path: str):
    """逐路径核对：该路径在两端的 method 集合完全一致（含「仅在一端存在」的情况）。"""
    contract = _CONTRACT.get(path)
    backend = _BACKEND.get(path)
    assert contract == backend, (
        f"路径 {path} method 集合不一致：契约={sorted(contract or [])} 后端={sorted(backend or [])}"
        + ("（契约中缺失）" if contract is None else "")
        + ("（后端未实现）" if backend is None else "")
    )


def test_contract_freeze_baseline_counts():
    """冻结基线：契约路径数 107、ops 数 116（漂移即失败，迫使显式更新）。"""
    assert len(_CONTRACT) == FROZEN_PATH_COUNT, (
        f"契约路径数 {len(_CONTRACT)} != 冻结基线 {FROZEN_PATH_COUNT}"
    )
    op_count = sum(len(v) for v in _CONTRACT.values())
    assert op_count == FROZEN_OP_COUNT, f"契约 ops 数 {op_count} != 冻结基线 {FROZEN_OP_COUNT}"


# ---------------------------------------------------------------------------
# 2) TS 双副本逐字一致
# ---------------------------------------------------------------------------


def test_ts_copies_are_byte_identical():
    primary = TS_PRIMARY.read_bytes()
    copy = TS_COPY.read_bytes()
    assert primary == copy, (
        "两份 TS 契约副本不一致："
        f"{TS_PRIMARY.relative_to(REPO_ROOT)} vs {TS_COPY.relative_to(REPO_ROOT)}"
    )


# ---------------------------------------------------------------------------
# 3) Mock 覆盖全部 method+path
# ---------------------------------------------------------------------------


def _mock_method_path_pairs() -> set[tuple[str, str]]:
    """优先用 node 解析 routes.mjs 的导出（真实求值）；无 node 时回退正则提取。"""
    node = shutil.which("node")
    if node:
        script = (
            f"import {{routes}} from {json.dumps(str(MOCK_ROUTES))};"
            "console.log(JSON.stringify(routes.map(r => [r.m.toUpperCase(), r.p])))"
        )
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return {(m, p) for m, p in json.loads(proc.stdout)}
    text = MOCK_ROUTES.read_text(encoding="utf-8")
    return {(m.upper(), p) for m, p in re.findall(r"m:\s*'([A-Z]+)',\s*p:\s*'([^']+)'", text)}


def test_mock_covers_all_contract_operations():
    contract_ops = {(m.upper(), p) for p, methods in _CONTRACT.items() for m in methods}
    mock_ops = _mock_method_path_pairs()
    missing = sorted(contract_ops - mock_ops)
    extra = sorted(mock_ops - contract_ops)
    assert not missing, f"Mock 未覆盖的接口: {missing}"
    assert not extra, f"Mock 多出的接口（契约中不存在）: {extra}"


# ---------------------------------------------------------------------------
# 4) $ref 悬空检查
# ---------------------------------------------------------------------------


def _iter_refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _iter_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_refs(item)


def _resolve_pointer(doc, ref: str):
    node = doc
    for raw in ref.lstrip("#/").split("/"):
        seg = raw.replace("~1", "/").replace("~0", "~")
        node = node[int(seg)] if isinstance(node, list) else node[seg]
    return node


def _dangling_refs(prefix: str) -> list[str]:
    doc = _load_contract()
    refs = sorted({r for r in _iter_refs(doc) if r.startswith(prefix)})
    dangling = []
    for ref in refs:
        try:
            _resolve_pointer(doc, ref)
        except (KeyError, IndexError, TypeError, ValueError):
            dangling.append(ref)
    return dangling


def test_schema_refs_resolve():
    """契约内 `#/components/schemas/*` 的 $ref 目标必须存在（防悬空引用，F2 门禁）。"""
    doc = _load_contract()
    schema_refs = sorted({r for r in _iter_refs(doc) if r.startswith("#/components/schemas/")})
    assert schema_refs, "契约内未发现任何 #/components/schemas/** $ref（结构异常）"
    dangling = _dangling_refs("#/components/schemas/")
    assert not dangling, f"悬空 schema $ref（components.schemas 中不存在目标）: {dangling}"


def test_all_component_refs_resolve():
    """更宽口径：`#/components/**`（含 responses/parameters）全部 $ref 目标存在。

    此前 `contracts/openapi.yaml` 有 4 处 `$ref:'#/components/responses/NotFound'` 悬空
    （components.responses 仅有 `NotFound404`），已由主 Agent 修为 `NotFound404`；
    缺口消除，本用例转为**真门禁**（不再 xfail）。
    """
    assert not _dangling_refs("#/components/"), "存在悬空 $ref"
