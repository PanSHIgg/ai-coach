/**
 * AI 饮食管控教练 · 前端 TS 契约类型（手写版）
 *
 * - 与 contracts/openapi.yaml (OpenAPI 3.1) 对齐；字段名 snake_case 与后端一致。
 * - 真源为 contracts/ts/api.d.ts，本文件为其副本；变更由主 Agent 单点同步（两份须逐字一致）。
 * - 再生成命令：bash contracts/gen-ts.sh（优先 npx openapi-typescript → ts/openapi.gen.ts；
 *   离线/失败时以手写文件为准）。
 * - 统一 envelope：成功 {code:0,message:"ok",data,request_id}；失败 data:null、errors 可选。
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
  today_left: number; // 环形图「还能吃」= BMR×PAL − 摄入 + 运动 − TEF
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
  food_id: number | null; // 未匹配到食物库时为 null（此时 need_confirm=true）
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
  title?: string | null;
  post_type?: 1 | 2 | 3; // 1普通 2经验 3打卡
}

export interface CommunityPostCreated {
  id: number;
  audit_status: number; // 0待审 1通过
}

export interface CommunityPostOut {
  id: number;
  user: UserBrief;
  title?: string | null;
  content: string;
  images: string[];
  post_type: number;
  like_count: number;
  comment_count: number;
  anonymous: boolean;
  liked: boolean;
  created_at: string;
}

export type PostPageData = PageData<CommunityPostOut>;

export interface PostDeleteData {
  id: number;
  deleted: true;
}

export interface LikeData {
  post_id: number;
  liked: boolean;
  like_count: number;
}

export interface CommunityCommentIn {
  content: string;
  anonymous?: boolean;
}

export interface CommunityCommentOut {
  id: number;
  user: UserBrief;
  content: string;
  anonymous: boolean;
  created_at: string;
}

export type CommentPageData = PageData<CommunityCommentOut>;

export interface ExperienceItem {
  id: number;
  user: UserBrief;
  title?: string | null;
  content: string;
  like_count: number;
  created_at: string;
}

export type ExperiencePageData = PageData<ExperienceItem>;

export interface SuperviseOut {
  id: number;
  partner: UserBrief;
  status: number; // 1生效 0解除
  days: number;
  created_at: string;
}

export interface SuperviseMatchIn {
  partner_id?: number | null;
}

export interface SuperviseRemindData {
  supervise_id: number;
  reminded: true;
  message: string;
}

export interface SuperviseRecordItem {
  date: string;
  intake: number;
  steps: number;
  deficit: number; // 负值为缺口
}

export interface SuperviseRecordsData {
  supervise_id: number;
  partner: UserBrief;
  items: SuperviseRecordItem[];
}

export interface GroupItem {
  id: number;
  name: string;
  category?: string | null;
  member_count: number;
  city?: string | null;
  created_at: string;
}

export type GroupPageData = PageData<GroupItem>;

export interface GroupJoinData {
  group_id: number;
  joined: true;
  member_count: number;
}

export interface GroupCheckinData {
  group_id: number;
  checked: true;
  checkin_days: number;
  post_id?: number | null;
}

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
  creator_id?: number | null;
}

export type BattlePageData = PageData<BattleItem>;

export interface BattleCreateIn {
  title: string;
  sport_name?: string | null;
  merchant_id?: number | null;
  city?: string | null;
  lat?: number | null;
  lng?: number | null;
  meet_at: string;
  need_count?: number;
}

export interface BattleJoinIn {
  battle_id: number;
}

export interface BattleJoinData {
  battle_id: number;
  joined: true;
  join_count: number;
}

export interface ChallengeItem {
  id: number;
  title: string;
  start_at?: string | null;
  end_at?: string | null;
  badge_image?: string | null;
  join_count: number;
  status: number; // 1进行中 2结束
  joined: boolean;
}

export type ChallengePageData = PageData<ChallengeItem>;

export interface ChallengeJoinData {
  challenge_id: number;
  joined: true;
  join_count: number;
}

export interface LeaderboardEntry {
  rank: number;
  user: UserBrief;
  score: number;
}

export interface ChallengeLeaderboardData {
  challenge_id: number;
  items: LeaderboardEntry[];
}

export interface LeaderboardData {
  period_type: number; // 1日榜 2周榜 3月榜
  period_key: string;
  items: LeaderboardEntry[];
}

export interface WeeklyCommentIn {
  week?: string | null;
}

export interface WeeklyCommentData {
  week: string;
  content: string;
  highlights: string[];
  references: string[];
}

export interface AdminAuditItem {
  id: number;
  target_type: number; // 1动态 2评论 3图片 4商家入驻
  target_id: number;
  user_id?: number | null;
  nickname?: string | null;
  content_snapshot?: string | null;
  sec_check_result?: number | null; // 1通过 2可疑 3不通过
  status: number; // 0待审 1通过 2驳回
  reject_reason?: string | null;
  reviewer_id?: number | null;
  reviewed_at?: string | null;
  created_at: string;
}

export type AdminAuditPageData = PageData<AdminAuditItem>;

export interface AdminReviewIn {
  status: 1 | 2;
  reason?: string | null;
}

export interface AdminReviewData {
  id: number;
  target_type: number;
  target_id: number;
  status: number;
  reject_reason?: string | null;
  reviewed_at?: string | null;
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

/* ---------- Phase 1 新增：体重 / 订阅 / 刷新 token（openapi.yaml 已同步）---------- */

export interface RefreshIn {
  refresh_token: string;
}

export interface RefreshData {
  token: string;
  refresh_token: string;
}

export interface WeightRecordIn {
  weight: number; // kg
  record_at?: string; // YYYY-MM-DD
  source?: number; // 1手动 2智能秤
  note?: string | null;
}

export interface WeightRecordOut {
  id: number;
  weight: number;
  record_at: string;
  source?: number | null;
  note?: string | null;
  created_at: string;
}

export interface WeightPageData {
  items: WeightRecordOut[];
  page: PageMeta;
}

export interface WeightDeleteData {
  id: number;
  deleted: boolean;
}

export interface WeightTrendItem {
  date: string;
  weight: number;
}

export interface WeightTrendData {
  items: WeightTrendItem[];
  start_weight?: number | null;
  latest_weight?: number | null;
  change?: number | null;
}

export type SubscriptionTemplateType = 1 | 2 | 3 | 4;

export interface SubscriptionIn {
  template_type: SubscriptionTemplateType;
}

export interface SubscriptionItem {
  template_type: number;
  status: number; // 1已订阅 0已退订
  subscribe_count: number;
  last_subscribe_at?: string | null;
}

export interface SubscriptionData {
  items: SubscriptionItem[];
}

export interface SubscriptionOut {
  template_type: number;
  status: number;
  subscribe_count: number;
  last_subscribe_at?: string | null;
}

/* ---------- 埋点（F3） ---------- */

export interface TrackEventIn {
  event: string; // 如 login/meal_photo/ai_chat/order_pay/scan_in
  properties?: Record<string, unknown>;
  occurred_at?: string | null; // 缺省用服务端时间
}

export interface TrackIn {
  events: TrackEventIn[]; // 1-50 条
  device_id?: string | null;
  platform?: 1 | 2 | 3; // 1小程序 2H5 3admin后台
}

export interface TrackData {
  accepted: number;
}

/* ---------- 退款（F1） ---------- */

export interface RefundIn {
  reason?: string | null;
}

export interface RefundData {
  order_id: number;
  status: 1 | 2 | 3 | 4 | 5; // 5已退款
  refunded: boolean;
}
