# contracts · API 契约（P0-d）

前后端并行的唯一真源（接口清单来源 `docs/split/05-API接口文档.md` §8.3）。
当前冻结基线：**112 条路径 / 122 个 operation**（GET 55 · POST 57 · PUT 5 · DELETE 5）。

## 文件结构

```
contracts/
├── openapi.yaml        # OpenAPI 3.1 契约（112 路径 / 122 操作；统一 envelope + 错误码 + Bearer JWT）
├── gen-ts.sh           # TS 类型生成：优先 npx openapi-typescript，失败回落手写 api.d.ts
├── ts/
│   └── api.d.ts        # 手写 TS 类型真源（与 miniapp 侧副本逐字一致；离线兜底/前端直接 import）
└── README.md
```

> **Mock Server 已移除**（`contracts/mock/`，含 `server.mjs` / `routes.mjs`）。
> 真实后端（`deploy/` compose + nginx 反代 `http://localhost/api`）是唯一联调面，
> 前端不再对罐头数据开发；因此「mock 是否覆盖全部接口」这条门禁随之作废，
> 由下述三方一致门禁替代（不再依赖 node 可执行）。

## 契约一致性门禁（三方）

用例文件：`backend/tests/test_contract_consistency.py`（纯 Python，不启服务、不连库、不依赖 node）。

| 断言 | 口径 |
| --- | --- |
| 后端 ↔ 契约（双向） | 遍历 FastAPI **实际注册的路由树**（含嵌套 `include_router`）取 `/api` 前缀下的 `METHOD path`，与 `openapi.yaml` 的 `paths` 双向 diff：契约声明而后端未实现 → 报「后端未实现」；后端已注册而契约没有（含被 `include_in_schema=False` 隐藏的业务路由）→ 报「契约中缺失」。逐路径参数化，失败信息直接点名到具体 operation。 |
| 冻结基线计数 | 契约侧与后端侧同时钉在 112 路径 / 122 ops，防止接口增删未走变更纪律，也防止路由遍历实现失效（如 FastAPI 升级改结构后返回空集）退化为假门禁。 |
| TS ↔ TS（双副本） | `contracts/ts/api.d.ts` 与 `miniapp/src/types/api.d.ts` **字节一致**（真源为前者，由主 Agent 单点同步）。 |
| 契约自检 | `#/components/**` 全部 `$ref` 目标存在，防悬空引用。 |

运维端点（`/healthz`、`/metrics`、`/docs`、`/openapi.json`）不挂 `/api` 前缀、不进契约，
故不在门禁比对范围内。

## 生成 TS 类型

```bash
bash gen-ts.sh
# 成功 → ts/openapi.gen.ts（npx openapi-typescript，自动生成勿手改）
# 失败（离线）→ 提示使用手写 ts/api.d.ts
```

> `ts/openapi.gen.ts` 为**生成产物，不入库**：勿手改、勿提交（仓库中不存在该文件）。
> 入库的类型真源是手写 `ts/api.d.ts`（及其 miniapp 侧副本）。

## 契约变更纪律

1. **先改 `openapi.yaml`**（接口唯一真源），注明变更原因与影响方；契约由主 Agent 单点修改并冻结；
2. 重新生成/同步 TS：`bash gen-ts.sh`，并手工对齐 `ts/api.d.ts` → 复制到 `miniapp/src/types/api.d.ts`
   （两份必须逐字一致）；
3. 同步 pydantic：`backend/app/schemas/`（字段与 openapi 一一对应）；
4. 同步后端实现路由（新增/删除 endpoint），必要时更新用例内的 `FROZEN_PATH_COUNT` /
   `FROZEN_OP_COUNT`；
5. **通知对端**（前端/QA/后端）再合并，并跑
   `cd backend && pytest -q tests/test_contract_consistency.py` 确认三方一致。

## 错误码约定（05 文档 §8.2）

`0` 成功 / `1001` 未登录 / `1002` 无权限 / `2001` 参数校验失败 / `3001` 资源不存在 /
`4001` 次数不足 / `5001` 商家停业 / `5002` 券不可用 / `5003` 订单已超时 / `5004` 核销码已使用 /
`6001` AI 暂不可用 / `7001` 邀请已达上限。HTTP 映射：422/401/403/404/409/429/500。

## 【假设】（默认决策记录）

- 限流(429)与服务错(500)的业务 code 复用 HTTP 状态码（05 文档错误码表未定义）。
- `/api/ai/chat` 首期统一返回 JSON，SSE 流式由 `Accept` 头预留。
- 埋点 tag 为预留分组，契约清单暂无埋点上报接口。
- 列表默认 `created_at DESC`、每页 20、`page_size` 上限 100；金额单位元（2 位小数）、重量 g、热量 kcal。
- 账户趋势缺省返回最近 7 天；`/api/order/{id}/pay` 返回微信拉起支付参数透传对象。
- 微信支付回调 `/api/order/notify` 按内部 envelope 应答，微信协议转换在网关层处理。
