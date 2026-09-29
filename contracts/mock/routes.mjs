// 路由表：method + 路径模板 → canned envelope data（覆盖 openapi.yaml 全部 34 接口）。
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
      date: today(), bmr: 1406, pal: 1.4, neat: 1644, eat: 274, tef: 150, tee: 2392,
      intake: 1418, deficit: -974, steps: 12000, calories_burnt: 274, calibration_used: true,
      today_left: 674, // = BMR×PAL − intake + eat − tef = 1968.4 − 1418 + 274 − 150（eat 与 calories_burnt 同值）
      meals: [
        { meal_type: 1, name: '早餐', calories: 380 },
        { meal_type: 2, name: '午餐', calories: 620 },
      ],
    },
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
      items: [{ id: 88, name: '轻食一号店', category: '轻食', distance_m: 350, rating: 4.8, cover_url: 'https://cos.example.com/m/88.png', status: 1 }],
      page,
    },
  },
  {
    m: 'GET', p: '/api/merchant/{id}',
    d: {
      id: 88, name: '轻食一号店', category: '轻食', address: 'XX路1号', lat: 31.2304, lng: 121.4737,
      phone: '021-0000000', rating: 4.8, status: 1, distance_m: 350,
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
  { m: 'POST', p: '/api/invite', d: { bound: false, invite_code: 'INV-1001-XYZ', poster_url: 'https://cos.example.com/invite/1001.png' } },
  {
    m: 'GET', p: '/api/invite/progress',
    d: {
      invitee_count: 1,
      next_tier: { need: 2, reward: '进阶版90天' },
      benefit: { tier: 0, valid_to: null },
      poster_url: 'https://cos.example.com/invite/1001.png',
    },
  },
  {
    m: 'GET', p: '/api/community/post/list',
    d: {
      items: [{ id: 1, user: { id: 1002, nickname: '减友B', avatar_url: null }, content: '今天午餐打卡清蒸鱼', images: [], like_count: 3, comment_count: 1, created_at: now() }],
      page,
    },
  },
  { m: 'POST', p: '/api/community/post', d: { id: 2 } },
  {
    m: 'GET', p: '/api/community/battle/list',
    d: {
      items: [{ id: 1, title: '轻食约战·第1期', sport_name: '轻食', merchant_id: 88, city: '上海', meet_at: '2026-10-01T12:00:00+08:00', need_count: 2, join_count: 1, status: 1 }],
      page,
    },
  },
  { m: 'POST', p: '/api/community/battle/join', d: { battle_id: 1, joined: true, join_count: 2 } },

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
    m: 'GET', p: '/api/admin/dashboard',
    d: { date: today(), user_count: 1200, active_users_today: 356, meal_records_today: 980, orders_today: 120, gmv_today: 3360.0, ai_calls_today: 2100 },
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
