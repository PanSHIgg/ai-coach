# 后端 API 契约 / 鉴权 / 限流 / 幂等 — 代码-文档一致性核对报告

> ⚠️ **已过期归档**（2026-09-30 迁入 `docs_process/archive/`）：本报告为 2026-09-30 分域核对分报告（slot5，后端 API / 鉴权 / 限流 / 幂等，基线 `dbbf198`），结论已并入同日主 Agent 定案汇总。**取代真源：`docs_process/archive/review_20260930_summary.md`**。本文仅留档。

**审查 slot**: 5（只读）  
**分支**: docs/env-check-0930 = origin/develop @ dbbf198  
**日期**: 2026-09-30  
**范围**: A 契约四方对齐 / B 限流实测 / C 幂等实测 / D 错误码 envelope / E 鉴权 / F 契约一致性测试 / G CI

---

## 1. 结论摘要

- **不符项总数**: 12 条（P0×0 / P1×3 / P2×8 / P3×1）
- **整体结论**: **FAIL**（P1 级文档陈旧 + 安全加固缺失）
- **pytest**: 496 passed in 135.58s（ai_coach_s4，2026-09-30 07:40 UTC）
- **ruff**: 274 errors（99 fixable）
- **black**: 39 files would be reformatted（CI 无 black 步骤，静默通过）
- **契约四方对齐**: openapi(72/78) = 后端(72/78) = mock(78 ops) ✅；05 文档仅 32 路径 ❌

---

## 2. 实跑原始摘要（2026-09-30，沙箱实测）

| 命令 | 时刻 | 结果 | 关键输出 |
|---|---|---|---|
| `pytest -q`（ai_coach_s4） | 07:40 | ✅ 496 passed in 135.58s | 含 test_contract_consistency 全绿 |
| `ruff check .` | 07:42 | 274 errors | 99 fixable |
| `black --check .` | 07:42 | ❌ 39 files would be reformatted | CI 无此步骤 |
| `diff contracts/ts/api.d.ts miniapp/src/types/api.d.ts` | 07:35 | ✅ exit=0，空输出 | 两份副本当前一致 |
| 后端启动（port 8005, db5） | 07:35 | ✅ | `curl /openapi.json` → 72 paths / 78 ops |
| Mock 启动（port 9005） | 07:35 | ✅ | `curl /api/track -XPOST` → 200 |
| 限流实测（Redis db5 真实可用） | 07:44 | ✅ | AI 第 21 次 → 429；Redis key `ratelimit:ai:user:<sub>` TTL=60 |
| Admin 登录限流 5/min | 07:46 | ✅ | 第 6 次 → code=429 |
| 幂等实测 | 07:47 | ✅ | 重放 → 409/4002；不同 key → 200；无 key → 200；不同身份同 key → 各自成功（Redis 2 个独立 key） |
| JWT refresh 流程 | 07:48 | ✅ | refresh_token 换 new access+refresh，HS256，access exp-iat=7200s，refresh exp-iat=604800s |
| 错误码 envelope | 07:45 | ✅ | 401→1001 / 404→3001 / 405→2001 / 422→2001 / 429→429；均含 request_id |

---

## 3. 分级问题清单

### P1 真实缺陷

| # | 级别 | 文档出处 | 代码位置 | 问题 | 证据 | 建议修法 |
|---|---|---|---|---|---|---|
| 1 | P1 | docs/split/05-API接口文档.md:29 | docs/split/05-API接口文档.md:29-66 | 05 文档仅列 34 行 / 32 唯一路径，openapi 有 **40 个路径不在 05 文档**（含 /api/admin/login、/api/admin/audit/*、/api/admin/coupon-pools、/api/admin/merchant-skus、/api/track、/api/order/{id}/refund、/api/auth/refresh、/api/weight/*、/api/subscription/* 等 Phase 1-5 新增）。05 文档头部虽注明"契约全集以 openapi.yaml 为准（当前 72 路径 / 78 ops）"，但表格本身严重陈旧 | `comm -23 /tmp/api_paths.txt /tmp/doc05_paths.txt \| wc -l` → 40 | 将 05 文档 §8.3 表格扩展为完整 72 路径，或明确标注"核心子集"并给出完整索引链接 |
| 2 | P1 | .env.example | backend/app/core/config.py:34 | JWT_SECRET 强度矛盾：config.py 默认值 64 字符（48 字节熵，`secrets.token_urlsafe(48)`），.env.example 模板 `change-me-to-a-random-secret` 仅 28 字节。**无启动期强度校验**——若生产部署者复制 .env.example 并忘记改 JWT_SECRET，PyJWT 会用 28 字节密钥签发 token（≥16 字节不报警告，但远低于推荐 32+ 字节） | `python3 -c "len('change-me-to-a-random-secret')"` → 28；`grep -rn 'JWT_SECRET.*len\|validate.*secret' backend/app/` → 无结果 | ① .env.example 改为 64 字符随机示例；② config.py 或 main.py 增加启动校验：`if len(JWT_SECRET) < 32 and ENV == "prod": raise RuntimeError` |
| 3 | P1 | README.md:49 / AGENTS.md §7.3 | .github/workflows/ci.yml | CI **无 black 步骤**：black 当前 39 文件不过，但 CI 完全未运行 black 检查，代码格式漂移完全无门禁。README.md:49 声称"ruff + black"双门禁，AGENTS.md §7.3 声称"ruff + black + pytest + mypy"四重门禁，CI 实际仅 ruff + pytest | `grep -c 'black' .github/workflows/ci.yml` → 0；`grep -c 'mypy' .github/workflows/ci.yml` → 0；`black --check .` → 39 files would be reformatted | CI 增加 `black --check .` 与 `mypy` 步骤（可先 non-blocking 过渡），或从 README/AGENTS.md 删除相关声明 |

### P2 轻微

| # | 级别 | 文档出处 | 代码位置 | 问题 | 证据 | 建议修法 |
|---|---|---|---|---|---|---|
| 4 | P2 | backend/app/main.py:36 | backend/app/main.py:32-38 | `_HTTP_CODE_MAP` 将 405 映射到 `ErrorCode.VALIDATION_ERROR`(2001)。405 Method Not Allowed 语义为"方法不支持"，与"参数校验失败"不同。实测 `DELETE /api/auth/me` → HTTP 405 + code=2001，message="参数校验失败"——语义误导 | `curl -X DELETE http://127.0.0.1:8005/api/auth/me` → `{"code":2001,"message":"参数校验失败"}` HTTP 405 | 增加 `ErrorCode.METHOD_NOT_ALLOWED = 2002`（或类似），或 405 映射到 NOT_FOUND(3001) 更合理 |
| 5 | P2 | backend/app/main.py:86-99 | backend/app/main.py:86-99 | `_HTTP_CODE_MAP` 仅含 {401,403,404,405,429}。FastAPI 对未注册路径返回 404（经 StarletteHTTPException handler → code=3001 ✅），但其他 HTTP 异常（如 400/408/413/502/503）走 `code is None` 分支 → `code = exc.status_code`（裸 HTTP 状态码作为业务码），message="请求方法或资源不支持"——非标准 envelope | main.py:90-98：`code = exc.status_code; message = "请求方法或资源不支持"` | 扩展映射表或统一兜底为 SERVER_ERROR(500) |
| 6 | P2 | docs/split/05-API接口文档.md §8.2 | backend/app/schemas/common.py:15-55 | 05 文档列出 13 个业务码（0/1001/1002/2001/3001/4001/4002/5001/5002/5003/5004/6001/7001），但 **429(RATE_LIMITED) 与 500(SERVER_ERROR) 未在 §8.2 表格**。实际代码 ErrorCode 枚举含 15 个值 | `grep -c '=' backend/app/schemas/common.py` ErrorCode 段 → 15 个；05 文档 §8.2 表格 → 13 行 | 05 文档 §8.2 补充 RATE_LIMITED(429) 与 SERVER_ERROR(500) |
| 7 | P2 | docs/split/05-API接口文档.md §8.1 | backend/app/schemas/common.py:60-70 | 05 文档未明确说明 `errors` 字段类型（`Optional[dict[str, Any]]`）与 `request_id` 在失败响应中**始终存在**（非 null）。实测所有失败响应均含 `request_id`（非 null）和 `errors`（可为 null） | 实测 401/404/405/422/429 响应均含 `request_id` 字段 | 05 文档 §8.1 补充：errors 为可选 dict、request_id 在所有响应（含失败）中必现 |
| 8 | P2 | backend/tests/test_contract_consistency.py | backend/tests/test_contract_consistency.py | 契约一致性测试**仅比对路径+method 集合**，不校验 schema 字段（requestBody/response properties）。若 openapi.yaml 与后端实现仅在字段级别漂移（如新增/删除/改名某 response field），测试不会捕获 | `grep -i 'schema\|field\|property\|requestBody' backend/tests/test_contract_consistency.py` → 无匹配 | 增加 schema 字段级比对断言（至少对核心接口如 auth/login、order/create） |
| 9 | P2 | ruff 274 errors | backend/ 全目录 | ruff 存量 274 errors（B008/UP045/I001 等），CI 以 `|| echo "::warning::"` 静默。数量过多已形成"破窗效应"——新引入的真实问题被淹没 | `ruff check .` → `Found 274 errors. [*] 99 fixable` | 分批修复（优先 `ruff check --fix --unsafe-fixes`），设回归上限（如 ≤200），CI 超限时阻断 |
| 10 | P2 | black 39 files | backend/ 全目录 | 39 文件 black 不过，CI 无 black 步骤。代码格式完全无约束 | `black --check .` → `39 files would be reformatted` | 一次性 `black .` 全量格式化 + CI 增加 `black --check` |
| 11 | P2 | .github/workflows/ci.yml | .github/workflows/ci.yml | CI **无 mypy/type-check 步骤**：AGENTS.md §7.3 声称"ruff + black + pytest + mypy"四重门禁，CI 实际仅 ruff + pytest | `grep -i 'mypy\|type' .github/workflows/ci.yml` → 无匹配 | CI 增加 mypy 步骤，或修正 AGENTS.md 声明 |

### P3 建议

| # | 级别 | 文档出处 | 代码位置 | 问题 | 证据 | 建议修法 |
|---|---|---|---|---|---|---|
| 12 | P3 | backend/app/core/idempotency.py:47-49 | backend/app/core/idempotency.py:47-49 | 幂等 identity fingerprint 用 `Authorization` 头全文 sha256 前 16 字符。JWT token 含 `.` 分隔符，不同 token 格式（如 Bearer vs Token）会生成不同指纹——但实际只有 Bearer 一种，影响可忽略。更值得关注的是：fingerprint 截断至 16 hex chars（64 bit），碰撞概率极低但非零 | idempotency.py:48-49: `hashlib.sha256(auth.encode()).hexdigest()[:16]` | 可保持现状；若追求完美可扩至 32 chars |

---

## 4. 已验证一致的部分

### A. 契约四方对齐

- ✅ **openapi.yaml = 后端实际注册路由**：`curl /openapi.json` 导出 72 paths / 78 ops，与 `contracts/openapi.yaml` 的 72 paths / 78 ops **完全一致**（diff 为空）
- ✅ **mock 覆盖全部 78 ops**：`node -e "import {routes} from ..."` 解析得 78 个唯一 (method, path) 对，与 openapi 差集为空
- ✅ **test_contract_consistency.py 全绿**：pytest 实跑通过，证明 4 类门禁（backend↔contract paths/methods、TS byte-identical、mock 全覆盖、$ref 无悬空）当前有效

### B. 限流实测（Redis 7.4.11 db5 真实可用）

- ✅ **Redis 路径**：21 次 AI 请求后 `redis-cli -n 5 keys 'ratelimit:*'` → `ratelimit:ai:user:<sub>`（值=22，TTL=60）
- ✅ **第 21 次 AI 请求返回 429**（limit=20/min）
- ✅ **Admin 登录 5/min 档**：第 6 次 `/api/admin/login` → code=429（IS-007 落地）
- ✅ **Redis 不可用时进程内兜底**：shutdown Redis 后连续请求 AI 端点，第 21 次仍 429（进程内字典计数生效）
- ✅ **Redis 版本探测**：rate_limit.py:35-51 `_check_redis_version()` 检查 major<7 打 warning，Redis 7.4.11 下无告警
- ✅ **IS-004 SET NX EX + INCR 兼容方案**：rate_limit.py:65-68 pipeline 原子执行，Redis 7 下无静默降级

### C. 幂等实测

- ✅ **同身份同 key 重放 → 409/4002**：首次 POST /api/steps/sync（带 Idempotency-Key: uuid-final-test）→ 200；同 key 重放 → `{"code":4002,"message":"重复请求（已拦截重放）","idempotency_replayed":true}` HTTP 409
- ✅ **不同 key → 各自成功**：uuid-final-test-2 → 200
- ✅ **不带 Idempotency-Key → 行为不变**：无 key 请求 → 200（中间件完全跳过）
- ✅ **不同身份同 key → 互不影响**：User A 与 User B 用同一 Idempotency-Key，Redis 出现 2 个独立 key（`idem:/api/steps/sync:a0c1a2...:shared-key-final` 与 `idem:/api/steps/sync:a23478...:shared-key-final`），指纹不同
- ✅ **失败释放**：422 响应（schema 错误）后同 key 可重试（idempotency.py:118 `status_code >= 400 → _release`）
- ✅ **Redis TTL = 300s**：与 `IDEMPOTENCY_TTL_SECONDS` 配置一致

### D. 错误码与 envelope

- ✅ **13 个业务码 + 429/500**：ErrorCode 枚举 15 值（含 OK=0、RATE_LIMITED=429、SERVER_ERROR=500）
- ✅ **request_id 始终存在**：实测 401/404/405/422/429 响应均含非 null `request_id`
- ✅ **errors 字段**：422 含 `errors.detail[]`（loc/msg/type 数组）；其他错误 `errors: null`
- ✅ **401 实测**：无 token → code=1001；无效 token → code=1001
- ✅ **404 实测**：`/api/nonexistent/path` → code=3001
- ✅ **422 实测**：schema 不匹配 → code=2001 + errors.detail
- ✅ **429 实测**：限流触发 → code=429 + Retry-After header

### E. 鉴权

- ✅ **JWT 双 token**：access 2h（exp-iat=7200s）、refresh 7d（exp-iat=604800s），HS256 算法
- ✅ **Refresh 流程**：POST /api/auth/refresh + `{"refresh_token":"..."}` → 新 access + 新 refresh
- ✅ **Token 域隔离**：admin token 含 `dom:"admin"` claim，decode_token 校验 `expected_dom`
- ✅ **Wechat mock 确定性**：WECHAT_APPID/SECRET 为空时，openid = `"mock-" + md5(code)[:16]`，同 code → 同 openid
- ✅ **config.py JWT_SECRET 默认值**：64 字符（48 字节熵），≥32 字节消除 PyJWT InsecureKeyLengthWarning

### F. 契约一致性测试

- ✅ **test_contract_consistency.py 覆盖 4 类断言**：
  1. backend↔contract 路径+method 双向一致（逐路径参数化）
  2. 冻结基线 72 paths / 78 ops
  3. TS 双副本 byte-identical
  4. mock 覆盖全部 contract ops + $ref 无悬空
- ✅ **pytest 实跑全绿**：496 passed

### G. CI

- ✅ **CI 覆盖**：backend（ruff + pytest + 真实 PG/Redis + seed）+ frontend（type-check + build:h5 + build:mp-weixin）+ admin（build）
- ✅ **ruff non-blocking**：`|| echo "::warning::"` 不阻断 CI
- ✅ **TS 副本一致**：`diff contracts/ts/api.d.ts miniapp/src/types/api.d.ts` → exit=0

---

## 5. 未验证 / 待确认

| 项 | 原因 | 验证方法 |
|---|---|---|
| **403 实测** | admin_user 表在 ai_coach_s4 为空（003_phase3_admin_seed.sql 未被 load_seeds.py 调用），手动 seed 后密码 hash 不正确无法登录。403 在测试套件中已验证（test_admin.py:171/306、test_community.py:222、test_orders.py:552、test_pay_wechat.py:148） | 完整 seed 后 curl admin 端点验证 |
| **500 实测** | 未找到触发未处理异常的简单路径。main.py:101-107 unhandled_handler 逻辑清晰，测试套件有覆盖 | 构造 service 层异常验证 |
| **admin 登录 422 问题** | admin_user 表为空时，login 查无用户 → 1001（非 422）。之前测试出现 422 是因为 Redis 限流 key 残留导致后续请求被 429，而非 schema 错误 | 清空 Redis 后重试 |
| **CI black 门禁历史** | 无法确认 black 是否曾被加入 CI 后移除，或从未加入 | git log .github/workflows/ci.yml 查看历史 |

---

## 6. 附录：关键命令输出

### 限流 Redis key 验证
```
$ redis-cli -n 5 keys 'ratelimit:*'
1) "ratelimit:ai:user:2"
2) "ratelimit:auth:ip:127.0.0.1"
$ redis-cli -n 5 ttl ratelimit:ai:user:2
(integer) 60
$ redis-cli -n 5 get ratelimit:ai:user:2
"22"
```

### 幂等 Redis key 验证
```
$ redis-cli -n 5 keys 'idem:*'
1) "idem:/api/steps/sync:64a7d9d898f65ef4:uuid-final-test-2"
2) "idem:/api/steps/sync:64a7d9d898f65ef4:uuid-final-test"
$ redis-cli -n 5 ttl idem:/api/steps/sync:64a7d9d898f65ef4:uuid-final-test
(integer) 300
```

### 不同身份同 key 验证
```
$ redis-cli -n 5 keys 'idem:*'
1) "idem:/api/steps/sync:a0c1a2a2415701cb:shared-key-final"
2) "idem:/api/steps/sync:a2347849f68ca0ab:shared-key-final"
```
（指纹 `a0c1a2...` ≠ `a23478...`，证明不同 Authorization 头生成不同 identity fingerprint）

### JWT token 解码
```json
// access token payload
{
  "sub": "6",
  "typ": "access",
  "iat": 1790754390,
  "exp": 1790761590,  // exp-iat = 7200s = 2h ✅
  "openid": "mock-226b8eededadb675"
}
// refresh token payload
{
  "sub": "6",
  "typ": "refresh",
  "iat": 1790754390,
  "exp": 1791359190,  // exp-iat = 604800s = 7d ✅
  "openid": "mock-226b8eededadb675"
}
```
