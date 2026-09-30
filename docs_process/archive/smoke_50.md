# F8 · 冒烟 50 条用例清单（发布级端到端）

> ⚠️ **已过期归档**（2026-09-30 迁入 `docs_process/archive/`）：本清单及 2026-09-29 实测结果（61 passed）为 Phase 5 交付时点记录，本文不再更新。**现行自动化真源：`backend/tests/smoke/test_smoke_50.py`；口径真源：`docs/split/07-测试方案.md` §9.7**；最新门禁基线见仓库根 `AGENTS.md` §7.1（2026-09-30 全量核对见 `docs_process/archive/review_20260930_summary.md`）。本文仅留档。

> 真源：`docs/split/07-测试方案.md` §9.7「冒烟用例 50 条全部通过」；`docs/split/09-排期与验收交付.md`
> §11.3 里程碑验收（M1–M4）与 §12.1 功能验收项；`plan.md` §11 F8。
> 自动化载体：`backend/tests/smoke/test_smoke_50.py`（实测 **61 条**，见文末）。
> 本轮实测：`61 passed`（2026-09-29 16:41 UTC，库 `ai_coach`）。

## 一、为什么单开冒烟文件（AGENTS §2.9 强制说明）

本清单是**发布级端到端冒烟**：验证「登录→建档→记餐→查账户→AI→商家→下单支付核销→社区→
内容审核→管理后台」等**跨模块串联链路可跑通**，而**非**模块内分支/边界的正确性——后者已由
`backend/tests/test_*.py` 各域单元/接口测试逐条覆盖。因此冒烟断言刻意**粗粒度**
（envelope `code==0` / 状态字段流转 / 资源可见性），**不复用**既有文件的细节断言，也不与之重复；
它填的是「现有测试文件都不做：把多个模块在一次请求序列里串起来」这一空白。

## 二、类型说明

全部为「**端到端闭环 · 跨模块串联**」：单条用例内按真实用户旅程顺序调用 ≥2 个模块的接口，
以「链路能跑通 + 关键状态正确」为通过标准。前置默认：库 `ai_coach`；已建表 + 种子
（`sku_catalog` / `ai_knowledge` 常驻）；`authed`（预置登录用户）或登录接口取 token；AI 无 Key
自动落 mock；`PAY_MOCK_MODE=false` 故支付推进走 `/api/order/notify` 回调。

## 三、50 条清单

| 编号 | 用例名 | 类型 | 前置 | 步骤 | 期望 | 是否自动化 |
| --- | --- | --- | --- | --- | --- | --- |
| SMK-01 | 登录→建档→首页账户闭环 | 端到端闭环·跨模块串联 | 无 token | 登录 → /auth/me → 建档 → /account/today | code=0；me.id 一致；bmr/target>0；date=今日 | ✅ |
| SMK-02 | Token 刷新轮换 | 端到端闭环·跨模块串联 | 已登录 | 登录 → /auth/refresh → 新 token 访问 /auth/me | code=0；新 token 同用户 | ✅ |
| SMK-03 | 未建档查询返回空 | 端到端闭环·跨模块串联 | 新登录 | 登录 → GET /body-profile | code=0；data=null | ✅ |
| SMK-04 | 建档→记餐→账户→列表 | 端到端闭环·跨模块串联 | 已登录 | 建档 → 记餐 → /account/today → /meal/list | 摄入=记餐重算值>0；列表含该餐（食物名快照） | ✅ |
| SMK-05 | 饮食 CRUD 全链路 | 端到端闭环·跨模块串联 | 已登录 | 记餐 → PUT 编辑 → DELETE → /meal/list | 编辑后热量变；删除后列表回空 | ✅ |
| SMK-06 | 食物搜索→直接记餐 | 端到端闭环·跨模块串联 | 已登录+建档 | /food/search → 用命中 food_id 记餐 | code=0；热量=搜索项对应值 | ✅ |
| SMK-07 | 运动→账户消耗→列表 | 端到端闭环·跨模块串联 | 已登录+建档 | 新增运动 → /account/today → /sport/list | calories>0；账户 calories_burnt 同步；列表 1 条 | ✅ |
| SMK-08 | 步数同步→NEAT 校准 | 端到端闭环·跨模块串联 | 已登录+建档 | /steps/sync 12000 → /account/today | neat_calibrated>0；steps=12000；calibration_used=true | ✅ |
| SMK-09 | 记餐后账户趋势 | 端到端闭环·跨模块串联 | 已登录+建档 | 记餐 → /account/trend | code=0；items 非空 | ✅ |
| SMK-10 | 体重 CRUD + 趋势 | 端到端闭环·跨模块串联 | 已登录 | 新增 → 列表 → 趋势 → 删除 → 列表 | 新增可见；latest=68.5；删除后列表回空 | ✅ |
| SMK-11 | 订阅提醒订阅/取消 | 端到端闭环·跨模块串联 | 已登录 | 订阅 → 列表 → 取消 | status 1→列表含→0 | ✅ |
| SMK-12 | 拍照识别→记餐 | 端到端闭环·跨模块串联 | 已登录+建档 | /meal/recognize(multipart) → 用识别分量记餐 | 识别 items 非空；记餐 code=0 | ✅ |
| SMK-13 | AI 对话→剩余次数 | 端到端闭环·跨模块串联 | 已登录 | /ai/times → /ai/chat → /ai/times | reply 非空；次数 -1 | ✅ |
| SMK-14 | 饭点决策推荐 | 端到端闭环·跨模块串联 | 已登录+主食候选 | /ai/recommend(meal_type=2) | code=0；options 非空（含理由） | ✅ |
| SMK-15 | AI 周点评 | 端到端闭环·跨模块串联 | 已登录+快照 | /ai/weekly-comment | content/highlights 非空 | ✅ |
| SMK-16 | AI 次数用尽 4001 | 端到端闭环·跨模块串联 | 已登录、余额置 0 | /ai/chat | HTTP 409 / code=4001 | ✅ |
| SMK-17 | 商家列表→详情→目录 | 端到端闭环·跨模块串联 | 已登录+商家种子 | /merchant/list → /merchant/{id} → /sku/catalog | 列表含商家；详情含 skus；目录 ≥5 行 | ✅ |
| SMK-18 | 下单→订单列表可见 | 端到端闭环·跨模块串联 | 已登录+商家/SKU | /order → /order/list | 列表可见该单，status=1 | ✅ |
| SMK-19 | 下单→pay→notify→列表 | 端到端闭环·跨模块串联 | 已登录+商家/SKU | /order → /order/{id}/pay → /order/notify → 列表过滤 status=2 | 含该单（已支付待核销） | ✅ |
| SMK-20 | 下单→支付→核销闭环 | 端到端闭环·跨模块串联 | 已登录+商家/SKU | /order → notify → 取核销码 → /order/{id}/redeem → 列表 status=3 | redeemed；列表含（已完成） | ✅ |
| SMK-21 | 带券下单抵扣 | 端到端闭环·跨模块串联 | 已登录+商家/SKU+券 | /order(coupon_id) → /coupon/list | discount=5、pay=total-5；券 status=2 | ✅ |
| SMK-22 | 订单超时支付 5003 | 端到端闭环·跨模块串联 | 已登录+过期单 | 下单 → 改 expire_at 过去 → /order/{id}/pay | HTTP 409 / code=5003 | ✅ |
| SMK-23 | 他人订单支付 3001 | 端到端闭环·跨模块串联 | A 下单、B token | B → A 的 /order/{id}/pay | HTTP 404 / code=3001 | ✅ |
| SMK-24 | 重复核销 5004 | 端到端闭环·跨模块串联 | 已支付单 | 核销 → 再次核销 | 二次 HTTP 409 / code=5004 | ✅ |
| SMK-25 | 退款链路 2→5 | 端到端闭环·跨模块串联 | 已支付待核销单 | /order/{id}/refund → 列表过滤 status=5 | refunded=true、status=5、列表含 | ✅ |
| SMK-26 | 订单行级隔离 | 端到端闭环·跨模块串联 | A 下单、B token | B → /order/list | B 列表 total=0 | ✅ |
| SMK-27 | 停业商家下单 5001 | 端到端闭环·跨模块串联 | 已登录+停业商家 | /order | HTTP 409 / code=5001 | ✅ |
| SMK-28 | 下单非法组合（4 变体） | 端到端闭环·跨模块串联 | 已登录+商家/SKU | 商家不存在/SKU 非本店/SKU 下架/库存不足 | 3001/404、2001/422（参数化 4 条） | ✅ |
| SMK-29 | 回调坏签名 422 | 端到端闭环·跨模块串联 | 已登录+待支付单 | /order/notify（sign 伪造） | HTTP 422 / code=2001 | ✅ |
| SMK-30 | 券列表行级隔离 | 端到端闭环·跨模块串联 | 两用户各持券 | /coupon/list | 仅本人券 total=1 | ✅ |
| SMK-31 | 发帖→列表→详情 | 端到端闭环·跨模块串联 | 已登录 | /community/post → /list → /{id} | 列表含；详情正文一致 | ✅ |
| SMK-32 | 点赞→取消赞 | 端到端闭环·跨模块串联 | 已登录+动态 | POST like → DELETE like | liked true→false；like_count 回 0 | ✅ |
| SMK-33 | 评论→列表→计数 | 端到端闭环·跨模块串联 | 已登录+动态 | 评论 → /comment/list → /{id} | 评论可见；comment_count=1 | ✅ |
| SMK-34 | 删除动态 | 端到端闭环·跨模块串联 | 已登录+动态 | DELETE /community/post/{id} → /list | deleted=true；列表回空 | ✅ |
| SMK-35 | 监督搭子匹配→提醒→记录 | 端到端闭环·跨模块串联 | 两用户 | match → remind → /records | 关系建立；reminded=true；记录含搭子 | ✅ |
| SMK-36 | 社群加入→打卡→动态 | 端到端闭环·跨模块串联 | 已登录+社群 | /group/{id}/join → /checkin → /post/list?post_type=3 | 成员+1；打卡沉淀动态在列表 | ✅ |
| SMK-37 | 约战发起→加入→列表 | 端到端闭环·跨模块串联 | 已登录 | /battle → /battle/join → /battle/list | join_count=2；列表含 | ✅ |
| SMK-38 | 挑战赛参加→详情→榜单 | 端到端闭环·跨模块串联 | 已登录+挑战赛 | /challenge/{id}/join → /{id} → /leaderboard | joined=true；详情/榜单 code=0 | ✅ |
| SMK-39 | 热量控制榜（快照聚合） | 端到端闭环·跨模块串联 | 两用户快照 | /community/leaderboard?period_type=1 | 缺口更大者排第 1 | ✅ |
| SMK-40 | 邀请裂变绑定→进度 | 端到端闭环·跨模块串联 | 两用户 | /invite 生成码 → 他人绑定 → /invite/progress | bound=true；invitee_count=1 | ✅ |
| SMK-41 | 同款减友经验列表 | 端到端闭环·跨模块串联 | 已登录 | 发 post_type=2 + 普通帖 → /experience/list | 仅经验贴入列表 | ✅ |
| SMK-42 | 匿名发帖隐藏身份 | 端到端闭环·跨模块串联 | 已登录 | 匿名发帖 → /post/list | anonymous=true | ✅ |
| SMK-43 | 非作者删除 403 | 端到端闭环·跨模块串联 | A 发帖、B token | B → DELETE 该帖 | HTTP 403 / code=1002 | ✅ |
| SMK-44 | 管理员登录→商家审核 | 端到端闭环·跨模块串联 | 超管账号 | /admin/login → /admin/merchants/{id}/audit → 列表 | audit_status=1；列表 code=0 | ✅ |
| SMK-45 | 后台选品定价 | 端到端闭环·跨模块串联 | 超管+商家 | /admin/merchant-skus（区间内）→（越界） | 通过；越界 HTTP 422/2001 | ✅ |
| SMK-46 | 券池→发放→C 端可见 | 端到端闭环·跨模块串联 | 超管+用户 | /admin/coupon-pools → /{id}/grant → /coupon/list | granted_count≥1；用户券列表≥1 | ✅ |
| SMK-47 | 后台订单监控+看板 | 端到端闭环·跨模块串联 | 超管+下单用户 | 下单 → /admin/orders → /admin/dashboard | 订单 total≥1；看板 code=0 | ✅ |
| SMK-48 | 内容审核：违规帖→通过 | 端到端闭环·跨模块串联 | 用户+超管 | 发违规帖（audit=0）→ /admin/audit/list → /review(通过) → /post/list | 审核后帖对外可见 | ✅ |
| SMK-49 | 内容审核：违规评论→驳回 | 端到端闭环·跨模块串联 | 用户+超管 | 评论违规词→入队→/review(驳回) → /comment/list | 评论不展示 | ✅ |
| SMK-50 | 埋点匿名+带 token 上报 | 端到端闭环·跨模块串联 | 无 / 已登录 | /track 匿名 2 条；带 token 1 条 | accepted=2 / 1；关联用户 | ✅ |

## 四、补充用例（SMK-51 ~ SMK-55，计入 61 条总量）

| 编号 | 用例名 | 类型 | 步骤 | 期望 | 是否自动化 |
| --- | --- | --- | --- | --- | --- |
| SMK-51 | 核心接口需鉴权（4 端点） | 端到端闭环·跨模块串联 | 无 token 访问 /order、/community/post、/account/today、/order/list | HTTP 401 / code=1001（参数化 4 条） | ✅ |
| SMK-52 | 建档参数越界 422 | 端到端闭环·跨模块串联 | 身高=999 建档 | HTTP 422 / code=2001 | ✅ |
| SMK-53 | 编辑不存在记录 404 | 端到端闭环·跨模块串联 | PUT /meal/999999 | HTTP 404 / code=3001 | ✅ |
| SMK-54 | 埋点空事件 422 | 端到端闭环·跨模块串联 | POST /track events=[] | HTTP 422 / code=2001 | ✅ |
| SMK-55 | 全链路一气呵成 | 端到端闭环·跨模块串联 | 登录→建档→记餐→查账户→浏览商家→下单→支付→核销 | 各步 code=0；核销 redeemed | ✅ |

> 说明：SMK-28 与 SMK-51 为参数化用例，各展开 4 条；故 `test_smoke_50.py` **实际收集 61 条**，
> 覆盖清单 50 条主用例 + 5 条补充用例（≥50 达标）。

## 五、实跑结果

| 命令 | 结果 | 时刻 |
| --- | --- | --- |
| `cd backend && DATABASE_URL=…ai_coach $PY -m pytest tests/smoke -q` | **61 passed** | 2026-09-29 16:41 UTC |
| `…pytest tests/test_contract_consistency.py tests/smoke -q` | **138 passed**（77 契约 + 61 冒烟） | 2026-09-29 16:41 UTC |
