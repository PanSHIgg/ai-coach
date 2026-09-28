# contracts · API 契约与 Mock（P0-d）

34 个接口的冻结契约（来源 `docs/split/05-API接口文档.md` §8.3），前后端并行的唯一真源。

## 文件结构

```
contracts/
├── openapi.yaml        # OpenAPI 3.1 契约（32 路径 / 34 操作；统一 envelope + 错误码 + Bearer JWT）
├── gen-ts.sh           # TS 类型生成：优先 npx openapi-typescript，失败回落手写 api.d.ts
├── ts/
│   └── api.d.ts        # 手写 TS 类型（与 openapi.yaml 对齐；离线兜底/前端直接 import）
├── mock/
│   ├── routes.mjs      # 方法+路径 → canned envelope（覆盖全部 34 接口；宽松匹配 /api 前缀与 {param}）
│   └── server.mjs      # 零依赖 Node http 服务（PORT 默认 9000，CORS、50-150ms 延迟、404 envelope）
└── README.md
```

## 启动 Mock Server（零依赖）

```bash
node mock/server.mjs                # 默认 :9000
PORT=8000 node mock/server.mjs      # 覆盖端口
curl -s localhost:9000/api/auth/me  # {"code":0,"message":"ok","data":{...}}
```

路由匹配宽松：`/api` 前缀可有可无、结尾斜杠忽略、`{param}` 匹配任意单段（如 `/api/merchant/88`）。
未匹配路径返回 HTTP 404 + `{"code":3001,"message":"资源不存在",...}`。

## 生成 TS 类型

```bash
bash gen-ts.sh
# 成功 → ts/openapi.gen.ts（npx openapi-typescript，自动生成勿手改）
# 失败（离线）→ 提示使用手写 ts/api.d.ts
```

## 契约变更纪律

1. **先改 `openapi.yaml`**（接口唯一真源），注明变更原因与影响方；
2. 重新生成/同步 TS：`bash gen-ts.sh`，并手工对齐 `ts/api.d.ts`；
3. 同步 pydantic：`code/backend/app/schemas/`（字段与 openapi 一一对应）；
4. **通知对端**（前端/QA/后端）再合并；Mock 的 canned data 同步更新。

## 错误码约定（05 文档 §8.2）

`0` 成功 / `1001` 未登录 / `1002` 无权限 / `2001` 参数校验失败 / `3001` 资源不存在 /
`4001` 次数不足 / `5001` 商家停业 / `5002` 券不可用 / `5003` 订单已超时 / `5004` 核销码已使用 /
`6001` AI 暂不可用 / `7001` 邀请已达上限。HTTP 映射：422/401/403/404/409/429/500。

## 【假设】（默认决策记录）

- 限流(429)与服务错(500)的业务 code 复用 HTTP 状态码（05 文档错误码表未定义）。
- `/api/ai/chat` 首期统一返回 JSON，SSE 流式由 `Accept` 头预留。
- 埋点 tag 为预留分组，34 接口清单暂无埋点上报接口。
- 列表默认 `created_at DESC`、每页 20、`page_size` 上限 100；金额单位元（2 位小数）、重量 g、热量 kcal。
- 账户趋势缺省返回最近 7 天；`/api/order/{id}/pay` 返回微信拉起支付参数透传对象。
- 微信支付回调 `/api/order/notify` 按内部 envelope 应答，微信协议转换在网关层处理。
