"""schemas 包：统一导出（openapi.yaml 契约的 pydantic 实现，P0-d）。"""

from .common import (
    ActivityLevel,
    CouponScope,
    CouponStatus,
    CouponType,
    Envelope,
    ErrorCode,
    Gender,
    MealType,
    OrderStatus,
    PageMeta,
    PageParams,
    PageResult,
    RecordSource,
    TargetType,
    fail,
    ok,
)

from .admin import DashboardData
from .ai import AiChatData, AiChatIn, AiRecommendData, AiRecommendIn, AiTimesData, RecommendOption
from .auth import LoginData, LoginRequest, UserBrief
from .community import (
    BattleJoinData,
    BattleJoinIn,
    BattleItem,
    BenefitInfo,
    CommunityPostIn,
    CommunityPostOut,
    InviteData,
    InviteIn,
    InviteProgressData,
    NextTier,
)
from .coupon import CouponOut
from .merchant import CatalogItem, MerchantBrief, MerchantDetail, SkuOut
from .order import OrderBrief, OrderCreateIn, OrderCreatedData, OrderItemIn, PayData, RedeemData, RedeemIn
from .profile import BodyProfileIn, BodyProfileOut
from .record import (
    FoodItem,
    FoodSearchIn,
    MealCreateIn,
    MealCreatedData,
    MealRecordOut,
    MealUpdateIn,
    RecognizedItem,
    RecognizeData,
    SportIn,
    SportRecordOut,
    StepsSyncIn,
    StepsSyncData,
)
from .user import UserBenefit, UserDetail
from .weight import WeightRecordIn, WeightRecordOut

__all__ = [
    "ActivityLevel", "AiChatData", "AiChatIn", "AiRecommendData", "AiRecommendIn", "AiTimesData",
    "BattleJoinData", "BattleJoinIn", "BattleItem", "BenefitInfo", "BodyProfileIn", "BodyProfileOut",
    "CatalogItem", "CommunityPostIn", "CommunityPostOut", "CouponOut", "CouponScope", "CouponStatus",
    "CouponType", "DashboardData", "Envelope", "ErrorCode", "FoodItem", "FoodSearchIn",
    "Gender", "InviteData", "InviteIn", "InviteProgressData", "LoginData", "LoginRequest",
    "MealCreateIn", "MealCreatedData", "MealRecordOut", "MealType", "MealUpdateIn", "MerchantBrief",
    "MerchantDetail", "NextTier", "OrderBrief", "OrderCreateIn", "OrderCreatedData", "OrderItemIn",
    "OrderStatus", "PageMeta", "PageParams", "PageResult", "PayData", "RecognizeData",
    "RecognizedItem", "RecordSource", "RedeemData", "RedeemIn", "RecommendOption", "SkuOut",
    "StepsSyncData", "StepsSyncIn", "SportIn", "SportRecordOut", "TargetType", "UserBenefit",
    "UserBrief", "UserDetail", "WeightRecordIn", "WeightRecordOut", "fail", "ok",
]
