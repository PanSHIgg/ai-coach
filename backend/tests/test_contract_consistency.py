"""契约一致性门禁（Phase 5 · F2「接口冻结」，plan.md §11 F2）。

**为何单开文件**（AGENTS §2.9）：`contracts/` 由主 Agent 单点冻结，此前**没有任何自动化
门禁**阻止「后端实现 ↔ `contracts/openapi.yaml` ↔ TS 双副本」漂移；本文件把三处一致性
收敛为同一「契约一致性」行为族的一组门禁用例，现有测试文件无一覆盖契约层，
不存在可容纳它的既有文件，也无重复可合并之处。

覆盖四类断言：
1) 后端 **FastAPI 实际注册的路由** ↔ `contracts/openapi.yaml`：路径集合与每路径 method
   集合双向一致（缺失/多余都要点名到具体 `METHOD path`）；
2) 冻结基线计数：契约与后端两侧同时钉在 110 路径 / 119 ops；
3) 两份 TS 副本 `contracts/ts/api.d.ts` 与 `miniapp/src/types/api.d.ts` 逐字一致；
4) 契约内 `$ref`（`#/components/**`）目标存在，防悬空引用。

数据源说明（Mock 移除后的替代门禁）：后端侧**不再**取 `app.openapi()`（生成态 schema），
而是遍历真实注册的路由树——`include_in_schema=False` 的 `/api/*` 业务路由在生成态里
不可见，此前可绕过门禁，现会被判为「后端有、契约没有」。求值全程纯 Python：
不启服务、不连库、不依赖 node（原 `contracts/mock/routes.mjs` 覆盖断言随 mock 目录删除，
其对 node 的依赖与 Windows 下 ESM 路径转义导致的偶发 fail 一并消除）。
"""

from pathlib import Path

import pytest
import yaml
from fastapi.routing import APIRoute

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "contracts" / "openapi.yaml"
TS_PRIMARY = REPO_ROOT / "contracts" / "ts" / "api.d.ts"
TS_COPY = REPO_ROOT / "miniapp" / "src" / "types" / "api.d.ts"

# 冻结基线（Phase 5 F2；变更契约须由主 Agent 显式更新此值并同步三处）
# F-05：新增 POST /api/admin/sku-catalog 与 PUT /api/admin/sku-catalog/{id} -> 路径 73 / ops 80
# F-02：新增 POST /api/food/custom -> 路径 74 / ops 81
# F-01：新增 POST /api/account/today-status -> 路径 75 / ops 82
# G1/G2：真人教练工单 + 平台自营订阅付费 -> 路径 89 / ops 96
# Wave A 地基：任务/积分 · 隐私 · 报告 · 语音 · 商家比价/自助（+18 路径 / +20 ops）
#   -> 路径 107 / ops 116
# COS 集成：POST /api/upload/credential（STS 直传凭证）+ POST /api/user/avatar（更新头像）
#   -> 路径 109 / ops 118
# 微信运动历史曲线：GET /api/steps/trend（直读 step_record，供前端拼步数柱状图）
#   -> 路径 110 / ops 119（GET 54）
# 账号管理：GET+POST /api/admin/accounts、PUT /api/admin/accounts/{id}/password
#   -> 路径 112 / ops 122（GET 55 / POST 57 / PUT 5）
FROZEN_PATH_COUNT = 112
FROZEN_OP_COUNT = 122

_METHODS = ("get", "post", "put", "delete", "patch", "options", "head")


def _load_contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _collect_registered_routes(routes, prefix: str) -> dict[str, set[str]]:
    """遍历路由树，取「路由模板 -> HTTP method 集合」（含嵌套 include_router / Mount）。

    兼容 FastAPI 两种 include 形态：旧版 include 时展开为 `APIRoute`（直接带最终路径），
    新版（>=0.142）惰性包装为 `_IncludedRouter`（子路由路径仍是相对的，前缀挂在
    `include_context.prefix` 上）。非 `APIRoute` 且无子路由的端点（Starlette `Route`，
    如 /docs、/openapi.json、/metrics）不属于业务契约面，忽略。
    """
    ops: dict[str, set[str]] = {}
    stack: list[tuple[object, str]] = [(routes, prefix)]
    while stack:
        current, current_prefix = stack.pop()
        for route in list(current):
            if isinstance(route, APIRoute):
                ops.setdefault(current_prefix + route.path_format, set()).update(
                    method.lower() for method in route.methods
                )
                continue
            children = getattr(route, "routes", None)
            if children is not None:  # APIRouter / Mount / 子应用
                stack.append((children, current_prefix + getattr(route, "prefix", "")))
                continue
            included = getattr(route, "original_router", None)
            if included is not None:  # 惰性 include 包装
                stack.append(
                    (included.routes, current_prefix + route.include_context.prefix)
                )
    return ops


def _backend_methods_by_path() -> dict[str, set[str]]:
    """后端 FastAPI 实际注册的业务路由（限定在 `API_PREFIX` 前缀下）。"""
    from app.main import create_app
    from tests.conftest import make_settings

    settings = make_settings()
    registered = _collect_registered_routes(create_app(settings).routes, "")
    return {
        path: methods
        for path, methods in registered.items()
        if path == settings.API_PREFIX or path.startswith(f"{settings.API_PREFIX}/")
    }


def _contract_methods_by_path() -> dict[str, set[str]]:
    return {
        path: {m for m in ops if m in _METHODS} for path, ops in _load_contract()["paths"].items()
    }


_BACKEND = _backend_methods_by_path()
_CONTRACT = _contract_methods_by_path()
_ALL_PATHS = sorted(set(_BACKEND) | set(_CONTRACT))


# ---------------------------------------------------------------------------
# 1) 后端实际注册路由 ↔ 契约：路径集合 + method 集合（双向）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _ALL_PATHS, ids=_ALL_PATHS)
def test_backend_and_contract_operations_match(path: str):
    """逐路径核对：契约声明与后端注册的 operation 集合完全一致。

    双向都抓：契约声明但后端未实现 → 「后端未实现」；后端已注册但契约没有
    （含 `include_in_schema=False` 藏起来的业务路由）→ 「契约中缺失」。
    """
    contract = _CONTRACT.get(path, set())
    backend = _BACKEND.get(path, set())
    only_in_backend = sorted(f"{m.upper()} {path}" for m in backend - contract)
    only_in_contract = sorted(f"{m.upper()} {path}" for m in contract - backend)
    assert not only_in_backend and not only_in_contract, (
        f"路径 {path} 的 operation 不一致："
        + (f"契约中缺失（后端已注册）{only_in_backend}；" if only_in_backend else "")
        + (f"后端未实现（契约已声明）{only_in_contract}；" if only_in_contract else "")
        + "变更须由主 Agent 先改 contracts/openapi.yaml，再同步实现/TS 双副本与冻结基线。"
    )


def test_contract_freeze_baseline_counts():
    """冻结基线：契约与后端实际注册两侧均为 110 路径 / 119 ops（漂移即失败，迫使显式更新）。

    后端侧一并钉住，避免路由树遍历实现失效（如 FastAPI 升级改结构后返回空集）时
    只剩「契约自证」的假门禁。
    """
    assert len(_CONTRACT) == FROZEN_PATH_COUNT, (
        f"契约路径数 {len(_CONTRACT)} != 冻结基线 {FROZEN_PATH_COUNT}"
    )
    contract_ops = sum(len(v) for v in _CONTRACT.values())
    assert contract_ops == FROZEN_OP_COUNT, (
        f"契约 ops 数 {contract_ops} != 冻结基线 {FROZEN_OP_COUNT}"
    )
    assert len(_BACKEND) == FROZEN_PATH_COUNT, (
        f"后端注册路径数 {len(_BACKEND)} != 冻结基线 {FROZEN_PATH_COUNT}"
    )
    backend_ops = sum(len(v) for v in _BACKEND.values())
    assert backend_ops == FROZEN_OP_COUNT, (
        f"后端注册 ops 数 {backend_ops} != 冻结基线 {FROZEN_OP_COUNT}"
    )


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
# 3) $ref 悬空检查
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
