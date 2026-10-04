"""运营看板 schema（openapi: /api/admin/dashboard）。"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import PageMeta
from .coupon import CouponOut


class DashboardData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    user_count: int
    active_users_today: int
    meal_records_today: int
    orders_today: int
    gmv_today: float  # 元
    ai_calls_today: int


# ---- Phase 3（BE9 管理后台，openapi components.schemas Admin*）----


class AdminLoginIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class AdminLoginData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str  # JWT，含 role/merchant_id 声明
    role: int  # 1超管 2运营 3商家
    merchant_id: Optional[int] = None  # 商家角色绑定的商家 ID
    username: str


class AdminMerchantOut(BaseModel):
    """管理侧商家完整视图（含审核状态）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    address: str
    phone: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    rating: float
    cover_url: Optional[str] = None  # 【假设】模型无此列，恒为 None
    status: int  # 1营业 0停业
    audit_status: int  # 0待审 1通过 2驳回
    audit_reason: Optional[str] = None  # 【假设】模型无此列，仅审核响应内存回显
    owner_user_id: Optional[int] = None
    created_at: datetime


class AdminMerchantPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[AdminMerchantOut]
    page: PageMeta


class AdminAuditIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_status: Literal[1, 2]  # 1通过 2驳回
    reason: Optional[str] = Field(default=None, max_length=200)


class AdminMerchantSkuIn(BaseModel):
    """商家选品定价；已存在 (merchant_id, catalog_id) 则更新。"""

    model_config = ConfigDict(from_attributes=True)

    merchant_id: int
    catalog_id: int
    price: float = Field(ge=0)  # 元；越出目录区间 -> 2001
    stock: int = Field(default=-1, ge=-1)  # -1 表示不限量
    status: Literal[0, 1] = 1  # 1上架 0下架


class AdminMerchantSkuData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    merchant_name: Optional[str] = None
    catalog_id: int
    catalog_code: str
    catalog_name: str
    price: float
    min_price: float  # 目录区间下限（回显）
    max_price: float  # 目录区间上限（回显）
    stock: int
    status: int  # 1上架 0下架
    updated_at: Optional[datetime] = None  # 【假设】merchant_sku 无 updated_at 列，恒为 None


class AdminSkuStatusIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Literal[0, 1]  # 1上架 0下架


class AdminSkuCatalogIn(BaseModel):
    """标准目录维护入参（F-05：平台运营维护，商家只选不建）。"""

    model_config = ConfigDict(from_attributes=True)

    code: str = Field(min_length=1, max_length=32)  # FD-001
    name: str = Field(min_length=1, max_length=128)
    category: str | None = Field(default=None, max_length=64)
    calories_low: int | None = Field(default=None, ge=0)
    calories_high: int | None = Field(default=None, ge=0)
    base_price: float = Field(ge=0)  # 元，基准价
    min_price: float = Field(ge=0)  # 元，限价下限
    max_price: float = Field(ge=0)  # 元，限价上限
    unit: str | None = Field(default=None, max_length=32)  # 份/盒

    @model_validator(mode="after")
    def _check_price_range(self) -> "AdminSkuCatalogIn":
        if not (self.min_price <= self.base_price <= self.max_price):
            raise ValueError("价格区间需满足 min_price <= base_price <= max_price")
        return self


class AdminCouponPoolIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(max_length=64)
    type: Literal[1, 2, 3, 4]  # 1满减 2折扣 3免费 4体验
    scope: Literal[1, 2, 3, 4]  # 1吃 2动 3异业 4通用
    amount: float = Field(default=0, ge=0)  # 满减/体验券减免金额（元）；折扣券为 0
    discount_rate: Optional[float] = Field(default=None, gt=0, le=1)  # 折扣率，如 0.8
    min_spend: float = Field(default=0, ge=0)  # 门槛金额（元）
    merchant_id: Optional[int] = None  # 异业券指定商家
    total_count: int = Field(ge=-1)  # -1 不限量（与 service 发放余量校验语义对齐）
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

    @field_validator("total_count")
    @classmethod
    def _total_count_nonzero(cls, v: int) -> int:
        if v == 0:  # 0 张无意义：要么正数限量，要么 -1 不限量
            raise ValueError("total_count 不能为 0（-1 表示不限量）")
        return v


class AdminCouponPoolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: int
    scope: int
    amount: float
    discount_rate: Optional[float] = None
    min_spend: float
    merchant_id: Optional[int] = None
    total_count: int
    granted_count: int  # 已发放数，剩余 = total - granted
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: datetime


class AdminCouponPoolPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[AdminCouponPoolOut]
    page: PageMeta


class AdminGrantIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pool_id: int
    user_id: int
    count: int = Field(default=1, ge=1, le=10)


class AdminGrantData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    granted_count: int  # 【假设】发放后券池累计已发放量
    pool_id: int
    user_id: int
    coupons: list[CouponOut]


# ---- Phase 4 ADM：内容审核队列（openapi /api/admin/audit/*）----


class AdminAuditItem(BaseModel):
    """审核队列条目（review 表）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    target_type: int  # 1动态 2评论 3图片 4商家入驻
    target_id: int
    user_id: Optional[int] = None
    nickname: Optional[str] = None  # 内容提交者昵称
    content_snapshot: Optional[str] = None
    sec_check_result: Optional[int] = None  # 1通过 2可疑 3不通过
    status: int  # 0待审 1通过 2驳回
    reject_reason: Optional[str] = None
    reviewer_id: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime


class AdminAuditPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[AdminAuditItem]
    page: PageMeta


class AdminReviewIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Literal[1, 2]  # 1通过 2驳回
    reason: Optional[str] = Field(default=None, max_length=200)


class AdminReviewData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_type: int
    target_id: int
    status: int  # 1通过 2驳回
    reject_reason: Optional[str] = None
    reviewed_at: Optional[datetime] = None


# ---- 账号管理（超管/运营开通后台账号；openapi components.schemas Admin*）----


class AdminAccountOut(BaseModel):
    """后台账号视图（不含密码哈希）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: int  # 1超管 2运营 3商家 4教练
    merchant_id: Optional[int] = None  # role=3 绑定的商家 ID
    created_at: datetime


class AdminAccountPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[AdminAccountOut]
    page: PageMeta


class AdminAccountIn(BaseModel):
    """创建后台账号；role=1/2 仅超管可建，role=3 必须绑定商家。

    `role` 用白名单枚举 [1,2,3] 而非 ge/le 区间：语义即「1超管 / 2运营 / 3商家」，
    4教练（走 G1 教练端）与 0/负数/超大值一并被 Pydantic 拦在入库之前，
    统一走框架的 422 + 2001 校验错误路径，不会漏到 DB CHECK 约束撞出500。
    服务层 `_ensure_account_create_allowed` 另有一道白名单（不依赖本字段约束，
    防内部调用方绕过 schema 校验）。
    """

    model_config = ConfigDict(from_attributes=True)

    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=12, max_length=128)
    role: Literal[1, 2, 3]  # 1超管 2运营 3商家；4教练走 G1 教练端，不经此接口
    merchant_id: Optional[int] = None  # role=3 必填


class AdminPasswordResetIn(BaseModel):
    """重置后台账号密码（超管重置任意账号，运营仅可重置商家账号）。"""

    model_config = ConfigDict(from_attributes=True)

    new_password: str = Field(min_length=12, max_length=128)
