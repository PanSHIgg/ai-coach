# 05 · API 接口文档

> 拆分自《AI 饮食管控教练 · 全栈开发交付文档》第八部分，内容为原文。

## 8.1 统一响应

成功：`{"code": 0, "message": "ok", "data": {...}, "request_id": "..."}`
失败：`{"code": <非0>, "message": "错误描述", "data": null, "errors": {...}}`

HTTP 状态码：参数错 422、未认证 401、无权限 403、资源不存在 404、业务错 409、限流 429、服务错 500。

## 8.2 通用错误码

| code | 含义             |
| ---- | -------------- |
| 0    | 成功             |
| 1001 | 未登录/Token 失效   |
| 1002 | 无权限            |
| 2001 | 参数校验失败         |
| 3001 | 资源不存在          |
| 4001 | 余额/次数不足        |
| 5001 | 商家停业           |
| 5002 | 券不可用（过期/不满足门槛） |
| 5003 | 订单已超时          |
| 5004 | 核销码已使用         |
| 6001 | AI 服务暂不可用      |
| 7001 | 邀请已达上限         |

## 8.3 接口列表（30 个核心接口）

| #   | 方法     | 路径                         | 说明              |
| --- | ------ | -------------------------- | --------------- |
| 1   | POST   | /api/auth/login            | 微信登录，code换token |
| 2   | GET    | /api/auth/me               | 当前用户            |
| 3   | POST   | /api/body-profile          | 创建/更新身体档案       |
| 4   | GET    | /api/body-profile          | 查档案             |
| 5   | GET    | /api/account/today         | 今日热量账户          |
| 6   | GET    | /api/account/trend         | 账户趋势（按日）        |
| 7   | POST   | /api/food/search           | 食物搜索            |
| 8   | POST   | /api/meal/recognize        | 拍照识别食物          |
| 9   | POST   | /api/meal                  | 新增饮食记录          |
| 10  | PUT    | /api/meal/{id}             | 编辑              |
| 11  | DELETE | /api/meal/{id}             | 删除              |
| 12  | GET    | /api/meal/list             | 饮食记录列表          |
| 13  | POST   | /api/sport                 | 新增运动记录          |
| 14  | GET    | /api/sport/list            | 运动记录列表          |
| 15  | POST   | /api/steps/sync            | 同步步数            |
| 16  | POST   | /api/ai/chat               | AI 对话（流式可选）     |
| 17  | GET    | /api/ai/times              | 查询剩余对话次数        |
| 18  | POST   | /api/ai/recommend          | 饭点决策推荐          |
| 19  | GET    | /api/merchant/list         | 商家列表（LBS）       |
| 20  | GET    | /api/merchant/{id}         | 商家详情            |
| 21  | GET    | /api/sku/catalog           | 标准目录            |
| 22  | POST   | /api/order                 | 创建订单            |
| 23  | POST   | /api/order/{id}/pay        | 微信支付预下单         |
| 24  | POST   | /api/order/notify          | 微信支付回调          |
| 25  | POST   | /api/order/{id}/redeem     | 核销              |
| 26  | GET    | /api/order/list            | 我的订单            |
| 27  | GET    | /api/coupon/list           | 我的券             |
| 28  | POST   | /api/invite                | 创建邀请/绑定         |
| 29  | GET    | /api/invite/progress       | 邀请进度与权益         |
| 30  | GET    | /api/community/post/list   | 社区动态列表          |
| 31  | POST   | /api/community/post        | 发动态             |
| 32  | GET    | /api/community/battle/list | 约战列表            |
| 33  | POST   | /api/community/battle/join | 加入约战            |
| 34  | GET    | /api/admin/dashboard       | 运营看板            |

## 8.4 关键接口示例

### 8.4.1 微信登录

**POST /api/auth/login**
请求：`{"code": "wx_code", "encrypted_data": "...", "iv": "..."}`
返回：

```json
{
  "code": 0,
  "data": {
    "token": "eyJhbGc...",
    "refresh_token": "...",
    "is_new": true,
    "need_profile": true,
    "user": {"id": 1001, "nickname": "减友A", "avatar_url": "..."}
  }
}
```

### 8.4.2 拍照识别

**POST /api/meal/recognize**
请求：`multipart/form-data` 字段 `image`（文件）
返回：

```json
{
  "code": 0,
  "data": {
    "request_id": "r-xxx",
    "items": [
      {"food_id": 208, "name": "清蒸鱼", "confidence": 0.92, "amount_g": 150, "calories": 180},
      {"food_id": 512, "name": "红烧肉", "confidence": 0.61, "amount_g": 100, "calories": 320}
    ],
    "need_confirm": true
  }
}
```

### 8.4.3 新增饮食记录

**POST /api/meal**
请求：`{"meal_type": 2, "food_id": 208, "amount_g": 150, "source": 1, "image_url": "..."}`
返回：`{"code": 0, "data": {"id": 9001, "calories": 180, "today_intake": 1418, "today_left": 682}}`

### 8.4.4 今日热量账户

**GET /api/account/today**
返回：

```json
{
  "code": 0,
  "data": {
    "date": "2026-09-28",
    "bmr": 1406,
    "pal": 1.4,
    "neat": 1644,
    "eat": 274,
    "tef": 150,
    "tee": 2392,
    "intake": 1418,
    "deficit": -974,
    "steps": 12000,
    "calories_burnt": 320,
    "calibration_used": true,
    "meals": [
      {"meal_type": 1, "name": "早餐", "calories": 380},
      {"meal_type": 2, "name": "午餐", "calories": 620}
    ]
  }
}
```

### 8.4.5 同步步数

**POST /api/steps/sync**
请求：`{"date": "2026-09-28", "steps": 12000, "hourly": {"8": 1200, "9": 1500}}`
返回：`{"code": 0, "data": {"neat_calibrated": 520, "met": 3.8, "delta_calories": 80}}`

### 8.4.6 AI 对话

**POST /api/ai/chat**
请求：`{"session_id": "uuid", "message": "下午饿了能吃什么"}`
返回（流式 SSE 或普通 JSON）：

```json
{
  "code": 0,
  "data": {
    "reply": "建议先喝一杯水，15分钟还不饱再吃个水煮蛋或黄瓜，热量低还顶饱。",
    "intent": "hunger_rescue",
    "times_left": 9,
    "references": ["knowledge:1203"]
  }
}
```

若次数用尽，返回 `code: 4001`，`message: "今日对话次数已用完，邀请好友可解锁更多"`，前端展示邀请入口。

### 8.4.7 创建订单

**POST /api/order**
请求：`{"merchant_id": 88, "items": [{"sku_id": 12, "qty": 1}], "coupon_id": 3051}`
返回：`{"code": 0, "data": {"order_id": 66001, "order_no": "DD2026...", "total_amount": 28, "discount_amount": 3, "pay_amount": 25, "expire_at": "2026-09-28T15:30:00+08:00"}}`

### 8.4.8 核销

**POST /api/order/{id}/redeem**
请求：`{"redeem_code": "RD-ABC123", "merchant_id": 88}`
返回：`{"code": 0, "data": {"status": "redeemed", "redeemed_at": "2026-09-28T13:00:00+08:00"}}`
若重复核销返回 `code: 5004`。

### 8.4.9 邀请进度

**GET /api/invite/progress**
返回：

```json
{
  "code": 0,
  "data": {
    "invitee_count": 1,
    "next_tier": {"need": 2, "reward": "进阶版90天"},
    "benefit": {"tier": 0, "valid_to": null},
    "poster_url": "https://cos.../invite/1001.png"
  }
}
```

## 8.5 鉴权与限流

请求头 `Authorization: Bearer <token>`。未带返回 1001。AI 对话额外校验 `user_benefit.ai_times_left`，不足返回 4001。全部写接口做参数校验（pydantic），金额类字段服务端重算。

## 8.6 订单库存语义说明

**下单阶段（POST /api/order）**：校验库存充足性（`qty <= stock` 或 `stock=-1` 不限量），但不预占、不扣减。目的是允许用户创建待支付订单而不立即锁定库存。

**支付阶段（POST /api/order/{id}/pay 或 notify 回调）**：使用 `SELECT ... FOR UPDATE` 行级锁扣减库存，保证并发安全。若库存不足则支付失败（返回 4001）。

**超时释放**：待支付订单 15 分钟后自动取消（`expire_at` 字段），取消时不恢复库存（因为从未扣减）。

**设计考量**：该策略避免"下单即锁库存"导致的库存浪费（用户下单后不支付），同时通过支付时的行级锁保证不超卖。实测 10 并发支付 stock=3 → 恰好 3 成功，无超卖。
