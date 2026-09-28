/**
 * AI 饮食管控教练 · 前端 TS 契约类型（miniapp 副本）
 *
 * 复制自 contracts/ts/api.d.ts，真源在契约库，再生成命令见 contracts/README.md。
 */

/* ---------- 统一 envelope 与分页 ---------- */

export interface Envelope<T = unknown> {
  code: number; // 0 成功；非 0 见 05 文档 §8.2
  message: string;
  data: T | null;
  request_id?: string;
  errors?: Record<string, unknown>;
}

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
}

export interface PageData<T> {
  items: T[];
  page: PageMeta;
}

/** 统一错误码（与 openapi components.responses 对应） */
export const ErrorCode = {
  OK: 0,
  UNAUTHORIZED: 1001,
  FORBIDDEN: 1002,
  VALIDATION: 2001,
  NOT_FOUND: 3001,
  QUOTA: 4001,
  MERCHANT_CLOSED: 5001,
  COUPON_INVALID: 5002,
  ORDER_TIMEOUT: 5003,
  REDEEM_USED: 5004,
  AI_UNAVAILABLE: 6001,
  INVITE_LIMIT: 7001,
} as const;

/* ---------- 认证 / 用户 ---------- */

export interface UserBrief {
  id: number;
  nickname: string;
  avatar_url?: string | null;
}

export interface LoginRequest {
  code: string; // wx.login code
  encrypted_data?: string | null;
  iv?: string | null;
}

export interface LoginData {
  token: string;
  refresh_token: string;
  is_new: boolean;
  need_profile: boolean;
  user: UserBrief;
}

export interface UserBenefit {
  tier: number; // 0基础 1进阶 2高级 3终身
  ai_times_left: number;
}

export interface UserDetail {
  id: number;
  nickname: string;
  avatar_url?: string | null;
  gender?: number | null; // 0未知 1男 2女
  benefit?: UserBenefit | null;
}

/* ---------- 身体档案 ---------- */

export interface BodyProfileIn {
  gender: 1 | 2; // 1男 2女
  height_cm: number;
  birth_year?: number | null;
  current_weight: number; // kg
  target_weight?: number | null;
  target_type: 1 | 2 | 3; // 1减脂 2增肌 3维持
  activity_level: 1 | 2 | 3 | 4 | 5;
  goal_pace?: number | null; // 每周目标 kg 档位
}

export interface BodyProfileOut extends BodyProfileIn {
  id: number;
  bmr: number; // 基础代谢 kcal
  target_calories: number;
  created_at?: string | null;
  updated_at?: string | null;
}

/* ---------- 热量账户 ---------- */

export interface MealSummary {
  meal_type: 1 | 2 | 3 | 4; // 1早餐 2午餐 3晚餐 4加餐
  name: string;
  calories: number;
}

export interface DailyAccount {
  date: string; // YYYY-MM-DD
  bmr: number;
  pal: number;
  neat: number;
  eat?: number | null;
  tef: number;
  tee: number;
  intake: number;
  deficit: number; // 负值为缺口
  steps: number;
  calories_burnt: number;
  calibration_used: boolean;
  meals: MealSummary[];
}

export interface DailyTrendItem {
  date: string;
  intake: number;
  tee: number;
  deficit: number;
  steps: number;
  calories_burnt: number;
}

export interface AccountTrendData {
  items: DailyTrendItem[];
}

/* ---------- 记录：食物/识别/饮食/运动/步数 ---------- */

export interface FoodSearchIn {
  keyword: string;
  limit?: number;
}

export interface FoodItem {
  id: number;
  name: string;
  calories_100g: number;
  protein_100g?: number | null;
  fat_100g?: number | null;
  carb_100g?: number | null;
  gi?: number | null;
}

export interface FoodSearchData {
  items: FoodItem[];
  total: number;
}

export interface RecognizedItem {
  food_id: number;
  name: string;
  confidence: number; // <0.7 需确认
  amount_g: number;
  calories: number;
}

export interface RecognizeData {
  request_id: string;
  items: RecognizedItem[];
  need_confirm: boolean;
}

export interface MealCreateIn {
  meal_type: 1 | 2 | 3 | 4;
  food_id: number;
  amount_g: number;
  source: 1 | 2 | 3 | 4; // 1拍照 2语音 3手动 4AI推荐
  image_url?: string | null;
}

export type MealUpdateIn = Partial<MealCreateIn>;

export interface MealCreatedData {
  id: number;
  calories: number;
  today_intake: number;
  today_left: number;
}

export interface MealDeleteData {
  id: number;
  deleted: true;
}

export interface MealRecordOut {
  id: number;
  meal_type: 1 | 2 | 3 | 4;
  food_id?: number | null;
  food_name: string;
  amount_g: number;
  calories: number;
  protein?: number | null;
  fat?: number | null;
  carb?: number | null;
  confidence?: number | null;
  source: 1 | 2 | 3 | 4;
  image_url?: string | null;
  record_date: string;
  created_at: string;
}

export type MealPageData = PageData<MealRecordOut>;

export interface SportIn {
  sport_name?: string | null;
  met?: number | null;
  duration_min: number;
  record_at?: string | null;
}

export interface SportCreatedData {
  id: number;
  calories: number;
  today_burnt?: number;
}

export interface SportRecordOut {
  id: number;
  sport_name?: string | null;
  met?: number | null;
  duration_min: number;
  calories: number;
  record_at: string;
  created_at: string;
}

export type SportPageData = PageData<SportRecordOut>;

export interface StepsSyncIn {
  date: string;
  steps: number;
  hourly?: Record<string, number>; // 键 0-23
}

export interface StepsSyncData {
  neat_calibrated: number;
  met: number;
  delta_calories: number;
}

/* ---------- AI ---------- */

export interface AiChatIn {
  session_id: string; // uuid
  message: string;
}

export interface AiChatData {
  reply: string;
  intent?: string | null; // 如 hunger_rescue
  times_left: number;
  references?: string[];
}

export interface AiTimesData {
  times_left: number;
}

export interface GeoLocation {
  lat: number;
  lng: number;
}

export interface AiRecommendIn {
  meal_type: 1 | 2 | 3 | 4;
  location?: GeoLocation;
  budget?: number | null; // 元
}

export interface RecommendOption {
  food_id?: number | null;
  name: string;
  calories: number;
  reason: string;
  merchant_id?: number | null;
}

export interface AiRecommendData {
  options: RecommendOption[];
}

/* ---------- 商家 ---------- */

export interface MerchantBrief {
  id: number;
  name: string;
  category: string;
  distance_m?: number | null;
  rating: number;
  cover_url?: string | null;
  status: number; // 1营业 0停业
}

export interface SkuOut {
  id: number;
  name: string;
  price: number; // 元
  stock: number; // -1 不限量
}

export interface MerchantDetail extends MerchantBrief {
  address: string;
  lat?: number | null;
  lng?: number | null;
  phone?: string | null;
  distance_m?: number | null;
  skus: SkuOut[];
}

export type MerchantPageData = PageData<MerchantBrief>;

export interface CatalogItem {
  id: number;
  code: string; // FD-001
  name: string;
  category?: string | null;
  calories_low?: number | null;
  calories_high?: number | null;
  base_price: number;
  min_price: number;
  max_price: number;
  unit?: string | null; // 份/盒
}

export interface CatalogData {
  items: CatalogItem[];
}

/* ---------- 订单 / 支付 / 核销 ---------- */

export interface OrderItemIn {
  sku_id: number;
  qty: number;
}

export interface OrderCreateIn {
  merchant_id: number;
  items: OrderItemIn[];
  coupon_id?: number | null;
}

export interface OrderCreatedData {
  order_id: number;
  order_no: string;
  total_amount: number;
  discount_amount: number;
  pay_amount: number; // 服务端重算
  expire_at: string; // 支付截止 ISO8601
}

export interface PayData {
  order_id: number;
  status: 1 | 2 | 3 | 4 | 5; // 1待支付 2已支付待核销 3已完成 4已取消 5已退款
  pay_params: Record<string, unknown>; // 微信拉起支付参数
}

export interface RedeemIn {
  redeem_code: string;
  merchant_id: number;
}

export interface RedeemData {
  status: 'redeemed';
  redeemed_at: string;
}

export interface OrderBrief {
  id: number;
  order_no: string;
  merchant_id: number;
  merchant_name?: string | null;
  total_amount: number;
  discount_amount: number;
  pay_amount: number;
  status: 1 | 2 | 3 | 4 | 5;
  redeem_code?: string | null;
  expire_at?: string | null;
  created_at: string;
}

export type OrderPageData = PageData<OrderBrief>;

/* ---------- 券 ---------- */

export interface CouponOut {
  id: number;
  code: string;
  type: 1 | 2 | 3 | 4; // 1满减 2折扣 3免费 4体验
  scope: 1 | 2 | 3 | 4; // 1吃 2动 3异业 4通用
  amount: number;
  discount_rate?: number | null;
  min_spend: number;
  merchant_id?: number | null;
  status: 1 | 2 | 3 | 4; // 1未用 2已用 3过期 4作废
  valid_from?: string | null;
  valid_to?: string | null;
}

export type CouponPageData = PageData<CouponOut>;

/* ---------- 社区：邀请 / 动态 / 约战 ---------- */

export interface InviteIn {
  invite_code?: string | null; // 缺省=创建邀请码；带值=绑定
}

export interface InviteData {
  bound: boolean;
  invite_code?: string | null;
  poster_url?: string | null;
}

export interface NextTier {
  need: number; // 距下一档还差人数
  reward: string;
}

export interface BenefitInfo {
  tier: number;
  valid_to?: string | null;
}

export interface InviteProgressData {
  invitee_count: number;
  next_tier: NextTier;
  benefit: BenefitInfo;
  poster_url?: string | null;
}

export interface CommunityPostIn {
  content: string;
  images?: string[];
  anonymous?: boolean;
}

export interface CommunityPostCreated {
  id: number;
}

export interface CommunityPostOut {
  id: number;
  user: UserBrief;
  content: string;
  images: string[];
  like_count: number;
  comment_count: number;
  created_at: string;
}

export type PostPageData = PageData<CommunityPostOut>;

export interface BattleItem {
  id: number;
  title: string;
  sport_name?: string | null;
  merchant_id?: number | null;
  city?: string | null;
  meet_at: string;
  need_count: number;
  join_count: number;
  status: 1 | 2 | 3 | 4; // 1招募中 2满员 3进行中 4结束
}

export type BattlePageData = PageData<BattleItem>;

export interface BattleJoinIn {
  battle_id: number;
}

export interface BattleJoinData {
  battle_id: number;
  joined: true;
  join_count: number;
}

/* ---------- 运营看板 ---------- */

export interface DashboardData {
  date: string;
  user_count: number;
  active_users_today: number;
  meal_records_today: number;
  orders_today: number;
  gmv_today: number;
  ai_calls_today: number;
}
