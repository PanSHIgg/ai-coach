// 路由表：method + 路径模板 → canned envelope data（覆盖 openapi.yaml 全部 116 接口）。
// 匹配规则（宽松）：/api 前缀可有可无、结尾斜杠与多斜杠忽略、{param} 匹配任意单段。
// 零依赖：仅用标准 JS，供 server.mjs 消费。

const now = () => new Date().toISOString();
const today = () => new Date().toISOString().slice(0, 10);

const user = { id: 1001, nickname: '减友A', avatar_url: 'https://cos.example.com/avatar/1001.png' };
const profile = {
  id: 1, gender: 1, height_cm: 175.0, birth_year: 1995, current_weight: 75.5,
  target_weight: 70.0, target_type: 1, activity_level: 2, goal_pace: 1,
  bmr: 1644.0, target_calories: 2300, created_at: now(), updated_at: now(),
};
const page = { page: 1, page_size: 20, total: 1 };

export const routes = [
  // ---- 认证 ----
  { m: 'POST', p: '/api/auth/login', d: { token: 'mock-jwt-token', refresh_token: 'mock-refresh-token', is_new: false, need_profile: false, user } },
  { m: 'GET', p: '/api/auth/me', d: { id: 1001, nickname: '减友A', avatar_url: user.avatar_url, gender: 1, benefit: { tier: 0, ai_times_left: 9 } } },

  // ---- 用户档案 ----
  { m: 'POST', p: '/api/body-profile', d: profile },
  { m: 'GET', p: '/api/body-profile', d: profile },

  // ---- 热量账户 ----
  {
    m: 'GET', p: '/api/account/today',
    d: {
      // TEF = 摄入 × 10% = 141.8；TEE = BMR×PAL + EAT + TEF = 2384.2 → 2384
      date: today(), bmr: 1406, pal: 1.4, neat: 1644, eat: 274, tef: 141.8, tee: 2384,
      intake: 1418, deficit: -966, steps: 12000, calories_burnt: 274, calibration_used: true,
      // today_left = BMR×PAL − intake + eat − tef = 1968.4 − 1418 + 274 − 141.8 = 682.6 → 682（对齐 05 §8.4.3 示例）
      today_left: 682,
      // 当日已选状态（F-01）：null=未选，前端据此决定是否弹「今天什么状态」
      activity_level: 2,
      meals: [
        { meal_type: 1, name: '早餐', calories: 380 },
        { meal_type: 2, name: '午餐', calories: 620 },
      ],
    },
  },
  // 写入当日状态（F-01）：回显入参 activity_level，其余同 GET today canned
  {
    m: 'POST', p: '/api/account/today-status',
    d: (ctx) => ({
      date: today(), bmr: 1406, pal: 1.4, neat: 1644, eat: 274, tef: 141.8, tee: 2384,
      intake: 1418, deficit: -966, steps: 12000, calories_burnt: 274, calibration_used: true,
      today_left: 682,
      activity_level: Number(ctx?.body?.activity_level) || null,
      meals: [
        { meal_type: 1, name: '早餐', calories: 380 },
        { meal_type: 2, name: '午餐', calories: 620 },
      ],
    }),
  },
  {
    m: 'GET', p: '/api/account/trend',
    d: {
      items: [
        { date: '2026-09-27', intake: 1900, tee: 2392, deficit: -492, steps: 10000, calories_burnt: 300 },
        { date: today(), intake: 1418, tee: 2392, deficit: -974, steps: 12000, calories_burnt: 320 },
      ],
    },
  },

  // ---- 记录 ----
  { m: 'POST', p: '/api/food/search', d: { items: [{ id: 208, name: '清蒸鱼', calories_100g: 120.0, protein_100g: 18.2, fat_100g: 4.5, carb_100g: 1.2, gi: 0 }], total: 1 } },
  { m: 'POST', p: '/api/food/custom', d: { id: 9001, name: '自制沙拉', calories_100g: 88.0, audit_status: 0 } },
  {
    m: 'POST', p: '/api/meal/recognize',
    d: {
      request_id: 'r-mock-001',
      items: [
        { food_id: 208, name: '清蒸鱼', confidence: 0.92, amount_g: 150, calories: 180 },
        { food_id: 512, name: '红烧肉', confidence: 0.61, amount_g: 100, calories: 320 },
      ],
      need_confirm: true,
    },
  },
  { m: 'POST', p: '/api/meal', d: { id: 9001, calories: 180, today_intake: 1418, today_left: 682 } },
  { m: 'PUT', p: '/api/meal/{id}', d: { id: 9001, calories: 200, today_intake: 1438, today_left: 662 } },
  { m: 'DELETE', p: '/api/meal/{id}', d: { id: 9001, deleted: true } },
  {
    m: 'GET', p: '/api/meal/list',
    d: {
      items: [{ id: 9001, meal_type: 2, food_id: 208, food_name: '清蒸鱼', amount_g: 150, calories: 180, source: 1, image_url: null, record_date: today(), created_at: now() }],
      page,
    },
  },
  { m: 'POST', p: '/api/sport', d: { id: 3001, calories: 320, today_burnt: 320 } },
  {
    m: 'GET', p: '/api/sport/list',
    d: { items: [{ id: 3001, sport_name: '慢跑', met: 8.0, duration_min: 30, calories: 320, record_at: now(), created_at: now() }], page },
  },
  { m: 'POST', p: '/api/steps/sync', d: { neat_calibrated: 520, met: 3.8, delta_calories: 80 } },

  // ---- Phase 1 新增：刷新 / 体重 / 订阅 ----
  { m: 'POST', p: '/api/auth/refresh', d: { token: 'mock-access-token', refresh_token: 'mock-refresh-token' } },
  {
    m: 'GET', p: '/api/weight/list',
    d: {
      items: [{ id: 1, weight: 68.5, record_at: today(), source: 1, note: null, created_at: now() }],
      page,
    },
  },
  {
    m: 'POST', p: '/api/weight',
    d: { id: 1, weight: 68.5, record_at: today(), source: 1, note: null, created_at: now() },
  },
  { m: 'DELETE', p: '/api/weight/{id}', d: { id: 1, deleted: true } },
  {
    m: 'GET', p: '/api/weight/trend',
    d: {
      items: [
        { date: '2026-09-22', weight: 69.2 },
        { date: '2026-09-25', weight: 68.8 },
        { date: today(), weight: 68.5 },
      ],
      start_weight: 69.2, latest_weight: 68.5, change: -0.7,
    },
  },
  {
    m: 'GET', p: '/api/subscription',
    d: {
      items: [
        { template_type: 1, status: 1, subscribe_count: 2, last_subscribe_at: now() },
        { template_type: 3, status: 0, subscribe_count: 1, last_subscribe_at: null },
      ],
    },
  },
  { m: 'POST', p: '/api/subscription', d: { template_type: 1, status: 1, subscribe_count: 1, last_subscribe_at: now() } },
  { m: 'POST', p: '/api/subscription/cancel', d: { template_type: 1, status: 0, subscribe_count: 1, last_subscribe_at: now() } },

  // ---- AI ----
  {
    m: 'POST', p: '/api/ai/chat',
    d: {
      reply: '建议先喝一杯水，15分钟还不饱再吃个水煮蛋或黄瓜，热量低还顶饱。',
      intent: 'hunger_rescue', times_left: 9, references: ['knowledge:1203'],
    },
  },
  { m: 'GET', p: '/api/ai/times', d: { times_left: 9 } },
  {
    m: 'POST', p: '/api/ai/recommend',
    d: { options: [{ food_id: 208, name: '清蒸鱼+杂粮饭', calories: 450, reason: '高蛋白低GI，剩余额度充足', merchant_id: 88 }] },
  },

  // ---- 商家 ----
  {
    m: 'GET', p: '/api/merchant/list',
    d: {
      items: [{ id: 88, name: '轻食一号店', category: '轻食', distance_m: 350, rating: 4.8, cover_url: 'https://cos.example.com/m/88.png', status: 1, partner_level: 2 }],
      page,
    },
  },
  {
    m: 'GET', p: '/api/merchant/{id}',
    d: {
      id: 88, name: '轻食一号店', category: '轻食', address: 'XX路1号', lat: 31.2304, lng: 121.4737,
      phone: '021-0000000', rating: 4.8, status: 1, distance_m: 350, partner_level: 2,
      skus: [{ id: 12, name: '鸡胸肉沙拉', price: 28.0, stock: 99 }],
    },
  },
  {
    m: 'GET', p: '/api/sku/catalog',
    d: { items: [{ id: 1, code: 'FD-001', name: '鸡胸肉沙拉', category: '轻食', calories_low: 300, calories_high: 500, base_price: 28.0, min_price: 20.0, max_price: 40.0, unit: '份' }] },
  },

  // ---- 订单 ----
  {
    m: 'POST', p: '/api/order',
    d: {
      order_id: 66001, order_no: 'DD202609280001', total_amount: 28.0,
      discount_amount: 3.0, pay_amount: 25.0, expire_at: '2026-09-28T15:30:00+08:00',
    },
  },
  {
    m: 'POST', p: '/api/order/{id}/pay',
    d: { order_id: 66001, status: 1, pay_params: { timeStamp: '1790000000', nonceStr: 'mock', package: 'prepay_id=mock', paySign: 'mock' } },
  },
  { m: 'POST', p: '/api/order/notify', d: { result: 'ok' } },
  { m: 'POST', p: '/api/order/{id}/redeem', d: { status: 'redeemed', redeemed_at: '2026-09-28T13:00:00+08:00' } },
  { m: 'POST', p: '/api/order/{id}/refund', d: { order_id: 66001, status: 5, refunded: true } },
  {
    m: 'GET', p: '/api/order/list',
    d: {
      items: [{
        id: 66001, order_no: 'DD202609280001', merchant_id: 88, merchant_name: '轻食一号店',
        total_amount: 28.0, discount_amount: 3.0, pay_amount: 25.0, status: 2,
        redeem_code: 'RD-ABC123', expire_at: '2026-09-28T15:30:00+08:00', created_at: now(),
      }],
      page,
    },
  },

  // ---- 券 ----
  {
    m: 'GET', p: '/api/coupon/list',
    d: {
      items: [{ id: 3051, code: 'CP-3051', type: 1, scope: 1, amount: 3.0, discount_rate: null, min_spend: 20.0, merchant_id: 88, status: 1, valid_from: now(), valid_to: '2026-10-28T23:59:59+08:00' }],
      page,
    },
  },

  // ---- 社区 ----
  { m: 'POST', p: '/api/invite', d: { bound: false, invite_code: 'INV-1001', poster_url: 'https://cos.example.com/invite/1001.png' } },
  {
    m: 'GET', p: '/api/invite/progress',
    d: {
      invitee_count: 1,
      next_tier: { need: 10, reward: '终身版不限次' },
      benefit: { tier: 1, valid_to: null },
      poster_url: 'https://cos.example.com/invite/1001.png',
    },
  },
  {
    m: 'GET', p: '/api/community/post/list',
    d: {
      items: [
        {
          id: 1, user: { id: 1002, nickname: '减友B', avatar_url: null }, title: null,
          content: '今天午餐打卡清蒸鱼', images: [], post_type: 1, like_count: 3,
          comment_count: 1, anonymous: false, liked: false, created_at: now(),
        },
      ],
      page,
    },
  },
  { m: 'POST', p: '/api/community/post', d: { id: 2, audit_status: 1 } },
  {
    m: 'GET', p: '/api/community/post/{id}',
    d: {
      id: 1, user: { id: 1002, nickname: '减友B', avatar_url: null }, title: null,
      content: '今天午餐打卡清蒸鱼', images: [], post_type: 1, like_count: 3,
      comment_count: 1, anonymous: false, liked: false, created_at: now(),
    },
  },
  { m: 'DELETE', p: '/api/community/post/{id}', d: { id: 1, deleted: true } },
  { m: 'POST', p: '/api/community/post/{id}/like', d: { post_id: 1, liked: true, like_count: 4 } },
  { m: 'DELETE', p: '/api/community/post/{id}/like', d: { post_id: 1, liked: false, like_count: 3 } },
  {
    m: 'GET', p: '/api/community/post/{id}/comment/list',
    d: {
      items: [{ id: 11, user: { id: 1003, nickname: '减友C', avatar_url: null }, content: '加油！', anonymous: false, created_at: now() }],
      page,
    },
  },
  {
    m: 'POST', p: '/api/community/post/{id}/comment',
    d: { id: 12, user: { id: 1001, nickname: '减友A', avatar_url: null }, content: '一起坚持', anonymous: false, created_at: now() },
  },
  {
    m: 'GET', p: '/api/community/experience/list',
    d: {
      items: [{ id: 21, user: { id: 1002, nickname: '减友B', avatar_url: null }, title: '我的减脂经验', content: '少油少盐，规律三餐', like_count: 6, created_at: now() }],
      page,
    },
  },
  { m: 'GET', p: '/api/community/supervise', d: { id: 1, partner: { id: 1002, nickname: '减友B', avatar_url: null }, status: 1, days: 7, created_at: now() } },
  { m: 'POST', p: '/api/community/supervise/match', d: { id: 2, partner: { id: 1003, nickname: '减友C', avatar_url: null }, status: 1, days: 0, created_at: now() } },
  { m: 'POST', p: '/api/community/supervise/{id}/remind', d: { supervise_id: 1, reminded: true, message: '已提醒 减友B 打卡' } },
  {
    m: 'GET', p: '/api/community/supervise/{id}/records',
    d: {
      supervise_id: 1, partner: { id: 1002, nickname: '减友B', avatar_url: null },
      items: [{ date: today(), intake: 1500, steps: 8000, deficit: -500 }],
    },
  },
  {
    m: 'GET', p: '/api/community/group/list',
    d: {
      items: [{ id: 1, name: '减脂餐交流社', category: '减脂', member_count: 2340, city: '上海', created_at: now() }],
      page,
    },
  },
  { m: 'GET', p: '/api/community/group/{id}', d: { id: 1, name: '减脂餐交流社', category: '减脂', member_count: 2340, city: '上海', created_at: now() } },
  { m: 'POST', p: '/api/community/group/{id}/join', d: { group_id: 1, joined: true, member_count: 2341 } },
  { m: 'POST', p: '/api/community/group/{id}/checkin', d: { group_id: 1, checked: true, checkin_days: 7, post_id: 31 } },
  {
    m: 'POST', p: '/api/community/battle',
    d: { id: 2, title: '今晚7点天河羽毛球', sport_name: '羽毛球', merchant_id: 88, city: '广州', meet_at: '2026-10-01T19:00:00+08:00', need_count: 2, join_count: 1, status: 1, creator_id: 1001 },
  },
  {
    m: 'GET', p: '/api/community/battle/list',
    d: {
      items: [{ id: 1, title: '轻食约战·第1期', sport_name: '轻食', merchant_id: 88, city: '上海', meet_at: '2026-10-01T12:00:00+08:00', need_count: 2, join_count: 1, status: 1, creator_id: 1002 }],
      page,
    },
  },
  { m: 'POST', p: '/api/community/battle/join', d: { battle_id: 1, joined: true, join_count: 2 } },
  {
    m: 'GET', p: '/api/community/challenge/list',
    d: {
      items: [{ id: 1, title: '21天不饿肚子挑战赛', start_at: '2026-09-20T00:00:00+08:00', end_at: '2026-10-10T23:59:59+08:00', badge_image: 'https://cos.example.com/badge/1.png', join_count: 12840, status: 1, joined: true }],
      page,
    },
  },
  { m: 'GET', p: '/api/community/challenge/{id}', d: { id: 1, title: '21天不饿肚子挑战赛', start_at: '2026-09-20T00:00:00+08:00', end_at: '2026-10-10T23:59:59+08:00', badge_image: null, join_count: 12840, status: 1, joined: true } },
  { m: 'POST', p: '/api/community/challenge/{id}/join', d: { challenge_id: 1, joined: true, join_count: 12841 } },
  {
    m: 'GET', p: '/api/community/challenge/{id}/leaderboard',
    d: { challenge_id: 1, items: [{ rank: 1, user: { id: 1002, nickname: '减友B', avatar_url: null }, score: 95.0 }] },
  },
  {
    m: 'GET', p: '/api/community/leaderboard',
    d: {
      period_type: 2, period_key: '2026-W40',
      items: [
        { rank: 1, user: { id: 1002, nickname: '小A', avatar_url: null }, score: 92.0 },
        { rank: 2, user: { id: 1001, nickname: '减友A', avatar_url: null }, score: 85.0 },
      ],
    },
  },
  { m: 'POST', p: '/api/ai/weekly-comment', d: { week: '2026-W40', content: '本周你记录了 5 天，热量缺口约 1800 kcal，保持不错。（AI 输出仅供参考，具体请遵医嘱）', highlights: ['打卡天数 5 天', '缺口 1800 kcal'], references: [] } },

  // ---- 管理 ----
  {
    m: 'POST', p: '/api/admin/login',
    d: { token: 'mock-admin-token', role: 1, merchant_id: null, username: 'admin' },
  },
  {
    m: 'GET', p: '/api/admin/merchants',
    d: {
      items: [
        {
          id: 88, name: '轻食一号店', category: '轻食', address: 'XX路1号', phone: '021-0000000',
          lat: 31.2304, lng: 121.4737, rating: 4.8, cover_url: 'https://cos.example.com/m/88.png',
          status: 1, audit_status: 1, audit_reason: null, owner_user_id: 1001, created_at: now(),
        },
      ],
      page,
    },
  },
  {
    m: 'POST', p: '/api/admin/merchants/{id}/audit',
    d: {
      id: 88, name: '轻食一号店', category: '轻食', address: 'XX路1号', phone: '021-0000000',
      lat: 31.2304, lng: 121.4737, rating: 4.8, cover_url: 'https://cos.example.com/m/88.png',
      status: 1, audit_status: 1, audit_reason: null, owner_user_id: 1001, created_at: now(),
    },
  },
  {
    m: 'POST', p: '/api/admin/merchant-skus',
    d: {
      id: 12, merchant_id: 88, merchant_name: '轻食一号店', catalog_id: 1, catalog_code: 'FD-001',
      catalog_name: '鸡胸肉沙拉', price: 28.0, min_price: 20.0, max_price: 40.0, stock: 99, status: 1, updated_at: null,
    },
  },
  {
    m: 'POST', p: '/api/admin/merchant-skus/{id}/status',
    d: {
      id: 12, merchant_id: 88, merchant_name: '轻食一号店', catalog_id: 1, catalog_code: 'FD-001',
      catalog_name: '鸡胸肉沙拉', price: 28.0, min_price: 20.0, max_price: 40.0, stock: 99, status: 1, updated_at: null,
    },
  },
  {
    m: 'GET', p: '/api/admin/coupon-pools',
    d: {
      items: [
        {
          id: 1, name: '新用户满减券', type: 1, scope: 1, amount: 5.0, discount_rate: null, min_spend: 20.0,
          merchant_id: null, total_count: 100, granted_count: 10, valid_from: now(), valid_to: '2026-12-31T23:59:59+08:00', created_at: now(),
        },
      ],
      page,
    },
  },
  {
    m: 'POST', p: '/api/admin/coupon-pools',
    d: {
      id: 2, name: '平台补贴券', type: 1, scope: 4, amount: 10.0, discount_rate: null, min_spend: 50.0,
      merchant_id: null, total_count: 50, granted_count: 0, valid_from: now(), valid_to: '2026-12-31T23:59:59+08:00', created_at: now(),
    },
  },
  {
    m: 'POST', p: '/api/admin/coupon-pools/{id}/grant',
    d: {
      granted_count: 15, pool_id: 1, user_id: 1001,
      coupons: [
        { id: 101, code: 'CP-ABC12345', type: 1, scope: 1, amount: 5.0, discount_rate: null, min_spend: 20.0, merchant_id: null, status: 1, valid_from: now(), valid_to: '2026-12-31T23:59:59+08:00' },
      ],
    },
  },
  {
    m: 'GET', p: '/api/admin/orders',
    d: {
      items: [
        {
          id: 66001, order_no: 'DD202609280001', merchant_id: 88, merchant_name: '轻食一号店',
          total_amount: 28.0, discount_amount: 3.0, pay_amount: 25.0, status: 2,
          redeem_code: 'RDW2MKC4NTCG', expire_at: '2026-09-28T15:30:00+08:00', created_at: now(),
        },
      ],
      page,
    },
  },
  {
    m: 'GET', p: '/api/admin/sku-catalog',
    d: { items: [{ id: 1, code: 'FD-001', name: '鸡胸肉沙拉', category: '轻食', calories_low: 300, calories_high: 500, base_price: 28.0, min_price: 20.0, max_price: 40.0, unit: '份' }] },
  },
  {
    m: 'POST', p: '/api/admin/sku-catalog',
    d: { id: 6, code: 'FD-006', name: '藜麦轻食碗', category: '轻食', calories_low: 320, calories_high: 480, base_price: 30.0, min_price: 24.0, max_price: 40.0, unit: '份' },
  },
  {
    m: 'PUT', p: '/api/admin/sku-catalog/{id}',
    d: { id: 1, code: 'FD-001', name: '鸡胸肉沙拉', category: '轻食', calories_low: 300, calories_high: 500, base_price: 28.0, min_price: 20.0, max_price: 40.0, unit: '份' },
  },
  {
    m: 'GET', p: '/api/admin/dashboard',
    d: { date: today(), user_count: 1200, active_users_today: 356, meal_records_today: 980, orders_today: 120, gmv_today: 3360.0, ai_calls_today: 2100 },
  },
  {
    m: 'GET', p: '/api/admin/audit/list',
    d: {
      items: [
        {
          id: 1, target_type: 1, target_id: 2, user_id: 1001, nickname: '减友A',
          content_snapshot: '这是违规词内容', sec_check_result: 3, status: 0,
          reject_reason: null, reviewer_id: null, reviewed_at: null, created_at: now(),
        },
      ],
      page,
    },
  },
  {
    m: 'POST', p: '/api/admin/audit/{id}/review',
    d: { id: 1, target_type: 1, target_id: 2, status: 2, reject_reason: '内容不合规', reviewed_at: now() },
  },

  // ---- G1 真人教练工单 / 专家问诊 ----
  {
    m: 'POST', p: '/api/coach/login',
    d: { access_token: 'mock-coach-jwt-token', refresh_token: 'mock-coach-refresh-token' },
  },
  {
    m: 'POST', p: '/api/coach/ticket',
    d: { ticket_id: 99001, status: 1, created_at: now() },
  },
  {
    m: 'GET', p: '/api/coach/tickets',
    d: {
      items: [{
        id: 99001, user_id: 1001, coach_id: 7001, title: '减脂期晚餐怎么配？',
        status: 1, created_at: now(), updated_at: now(),
      }],
      page,
    },
  },
  {
    m: 'GET', p: '/api/coach/ticket/{id}',
    d: {
      ticket: {
        id: 99001, user_id: 1001, coach_id: 7001, title: '减脂期晚餐怎么配？',
        status: 2, created_at: now(), updated_at: now(),
      },
      messages: [
        { id: 1, ticket_id: 99001, sender_role: 1, user_id: 1001, coach_id: null, content: '减脂期晚餐怎么配？', created_at: now() },
        { id: 2, ticket_id: 99001, sender_role: 2, user_id: null, coach_id: 7001, content: '晚餐蛋白质 30g + 蔬菜 300g，主食减半。', created_at: now() },
      ],
    },
  },
  {
    m: 'POST', p: '/api/coach/ticket/{id}/message',
    d: { message_id: 2 },
  },
  {
    m: 'GET', p: '/api/coach/assigned-users',
    d: {
      items: [{
        user,
        profile: { gender: 1, height_cm: 175.0, current_weight: 75.5, target_weight: 70.0, target_calories: 2300 },
        recent_records: [
          { date: today(), intake: 1418, deficit: -966, steps: 12000 },
          { date: '2026-09-30', intake: 1720, deficit: -664, steps: 9000 },
        ],
      }],
      page,
    },
  },
  {
    m: 'GET', p: '/api/coach/assigned-tickets',
    d: {
      items: [{
        id: 99001, user_id: 1001, coach_id: 7001, title: '减脂期晚餐怎么配？',
        status: 1, created_at: now(), updated_at: now(),
      }],
    },
  },
  {
    m: 'POST', p: '/api/coach/ticket/{id}/reply',
    d: { message_id: 2, status: 2 },
  },

  // ---- G2 平台自营会员订阅付费（/api/plan） ----
  {
    m: 'GET', p: '/api/plan/list',
    d: {
      items: [
        { tier: 1, name: '进阶会员', price: 29.0, valid_days: 30, ai_times: 30, coach_times: 5, description: '扩容 AI 次数 + 每月真人教练问诊额度' },
        { tier: 2, name: '高级会员', price: 59.0, valid_days: 30, ai_times: 60, coach_times: 15, description: '更高 AI 次数 + 更多真人教练问诊额度' },
        // 【假设】终身档价格文档未给，先取 199.00
        { tier: 3, name: '终身会员', price: 199.0, valid_days: null, ai_times: 200, coach_times: 60, description: '终身不限期' },
      ],
    },
  },
  {
    m: 'GET', p: '/api/plan/benefit',
    d: { tier: 0, ai_times_left: 9, coach_times_left: 0, valid_to: null, expired: false },
  },
  {
    m: 'POST', p: '/api/plan/order',
    d: (ctx) => {
      const tier = Number(ctx?.body?.tier) || 1;
      const price = { 1: 29.0, 2: 59.0, 3: 199.0 }[tier] ?? 29.0;
      return {
        order_id: 77001, order_no: 'PL2026100200001', tier, pay_amount: price,
        expire_at: '2026-10-02T15:30:00+08:00',
      };
    },
  },
  {
    m: 'POST', p: '/api/plan/order/{id}/pay',
    d: { order_id: 77001, status: 2, pay_params: {} },
  },
  { m: 'POST', p: '/api/plan/notify', d: { result: 'ok' } },
  {
    m: 'GET', p: '/api/plan/orders',
    d: {
      items: [{
        id: 77001, order_no: 'PL2026100200001', tier: 1, pay_amount: 29.0, status: 2,
        expire_at: '2026-10-02T15:30:00+08:00', paid_at: now(), created_at: now(),
      }],
      page,
    },
  },

  // ---- 埋点（F3，允许匿名） ----
  // accepted 按请求体 events.length 回显（对齐后端实现）
  {
    m: 'POST',
    p: '/api/track',
    d: (ctx) => ({ accepted: Array.isArray(ctx?.body?.events) ? ctx.body.events.length : 0 }),
  },

  // ---- 本轮新增（Wave A 地基）：任务/积分 · 隐私 · 报告 · 语音 · 商家比价/自助 ----
  {
    m: 'GET', p: '/api/task/list',
    d: {
      items: [
        { code: 'daily_checkin', name: '每日签到', reward_points: 5, reward_desc: '连续签到积分递增', status: 1, progress: 7 },
        { code: 'complete_profile', name: '完善档案', reward_points: 20, reward_desc: '补齐身高体重目标', status: 1, progress: 100 },
        { code: 'first_ai_check', name: '首次 AI 检测', reward_points: 10, reward_desc: '完成一次 AI 饮食检测', status: 0, progress: 0 },
      ],
    },
  },
  { m: 'POST', p: '/api/task/checkin', d: { points_added: 5, total_points: 125, streak: 7 } },
  {
    m: 'GET', p: '/api/points',
    d: {
      balance: 125, total_earned: 260,
      thresholds: [
        { points: 100, reward_desc: '兑换 3 元吃券' },
        { points: 300, reward_desc: '兑换会员体验券' },
      ],
    },
  },
  {
    m: 'GET', p: '/api/points/list',
    d: {
      items: [
        { change: 5, reason: '每日签到', created_at: now() },
        { change: 20, reason: '完善档案', created_at: '2026-09-30T09:00:00+08:00' },
        { change: -100, reason: '兑换 3 元吃券', created_at: '2026-09-29T12:00:00+08:00' },
      ],
      page,
    },
  },
  {
    m: 'GET', p: '/api/privacy',
    d: { anonymous: false, mask_share: true, visibility_leaderboard: true, visibility_community: true, allow_data_export: true },
  },
  {
    m: 'PUT', p: '/api/privacy',
    d: (ctx) => ({
      anonymous: false, mask_share: true, visibility_leaderboard: true,
      visibility_community: true, allow_data_export: true,
      ...(ctx?.body || {}),
    }),
  },
  {
    m: 'GET', p: '/api/coupon/exclusive',
    d: {
      items: [
        { id: 4101, code: 'CP-EX-4101', type: 1, scope: 3, amount: 5.0, discount_rate: null, min_spend: 30.0, merchant_id: 88, status: 1, valid_from: now(), valid_to: '2026-12-31T23:59:59+08:00' },
      ],
    },
  },
  {
    m: 'POST', p: '/api/report/export',
    d: (ctx) => ({
      filename: `${ctx?.body?.report_type || 'weight'}-report.csv`,
      mime: 'text/csv',
      content: 'date,weight\n2026-09-30,68.8\n2026-10-02,68.5\n',
    }),
  },
  {
    m: 'GET', p: '/api/report/weekly',
    d: {
      period: { start: '2026-09-26', end: '2026-10-02' },
      intake_avg: 1650, deficit_avg: -480, steps_avg: 9800, weight_change: -0.7,
      comment: '本周记录 5 天，日均缺口约 480 kcal，节奏平稳。（AI 输出仅供参考，具体请遵医嘱）',
      days: [
        { date: '2026-09-26', intake: 1700, deficit: -520, steps: 9000, weight: 69.2 },
        { date: '2026-10-02', intake: 1418, deficit: -966, steps: 12000, weight: 68.5 },
      ],
    },
  },
  {
    m: 'POST', p: '/api/ai/voice-transcribe',
    d: { text: '今天中午吃了鸡胸肉沙拉', provider: 'local-fallback' },
  },
  {
    m: 'GET', p: '/api/merchant/compare',
    d: {
      items: [
        { merchant_id: 88, name: '轻食一号店', distance: 350, rating: 4.8, price: 28.0, coupon_amount: 5.0, sku_name: '鸡胸肉沙拉' },
        { merchant_id: 92, name: '轻食二号店', distance: 820, rating: 4.6, price: 26.0, coupon_amount: 3.0, sku_name: '鸡胸肉沙拉' },
      ],
    },
  },
  { m: 'DELETE', p: '/api/account', d: { deleted: true } },

  // ---- 商家自助（商家 token） ----
  {
    m: 'POST', p: '/api/merchant/login',
    d: { token: 'mock-merchant-token', merchant_id: 88, name: '轻食一号店', expires_in: 7200 },
  },
  {
    m: 'GET', p: '/api/merchant/me',
    d: { id: 88, name: '轻食一号店', category: '轻食', address: 'XX路1号', phone: '021-0000000', rating: 4.8, status: 1, audit_status: 1, partner_level: 2 },
  },
  {
    m: 'GET', p: '/api/merchant/skus',
    d: {
      items: [
        { sku_id: 12, catalog_id: 1, catalog_code: 'FD-001', catalog_name: '鸡胸肉沙拉', price: 28.0, min_price: 20.0, max_price: 40.0, stock: 99, status: 1 },
      ],
    },
  },
  {
    m: 'PUT', p: '/api/merchant/skus',
    d: {
      items: [
        { sku_id: 12, catalog_id: 1, catalog_code: 'FD-001', catalog_name: '鸡胸肉沙拉', price: 26.0, min_price: 20.0, max_price: 40.0, stock: 99, status: 1 },
      ],
    },
  },
  { m: 'POST', p: '/api/merchant/sku/{id}/toggle', d: { sku_id: 12, status: 0 } },
  {
    m: 'GET', p: '/api/merchant/orders',
    d: {
      items: [
        { id: 66001, order_no: 'DD202609280001', user_id: 1001, total_amount: 28.0, pay_amount: 25.0, status: 2, redeem_code: 'RD-ABC123', redeemed_at: null, created_at: now() },
      ],
      page,
    },
  },
  { m: 'POST', p: '/api/merchant/order/{id}/redeem', d: { order_id: 66001, status: 3, redeemed_at: now() } },
  {
    m: 'GET', p: '/api/merchant/stats',
    d: { merchant_id: 88, order_count: 120, redeem_count: 96, gmv: 3360.0, sku_count: 1, contribution_points: 96 },
  },
];

/** 宽松匹配：/api 前缀可有可无、结尾/重复斜杠忽略；{param} 匹配任意单段。 */
export function match(method, rawPath) {
  const upper = String(method || 'GET').toUpperCase();
  const segs = String(rawPath || '').split('?')[0].split('/').filter(Boolean);
  if (segs[0] === 'api') segs.shift(); // /api 前缀宽松处理

  for (const r of routes) {
    if (r.m !== upper) continue;
    const parts = r.p.split('/').filter(Boolean);
    if (parts[0] === 'api') parts.shift();
    if (parts.length !== segs.length) continue;
    let hit = true;
    for (let i = 0; i < parts.length; i++) {
      if (parts[i].startsWith('{') && parts[i].endsWith('}')) continue; // 路径参数
      if (parts[i] !== segs[i]) { hit = false; break; }
    }
    if (hit) return r;
  }
  return null;
}
