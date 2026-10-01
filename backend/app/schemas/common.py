"""公共 schema：统一 envelope、错误码、分页、共享枚举。

与 code/contracts/openapi.yaml 的 components.schemas.Envelope / PageMeta 及 05 文档 §8.2 错误码表一一对应。
【假设】限流(429)与服务错(500)的业务 code 复用 HTTP 状态码（05 文档错误码表未定义）。
"""

from enum import IntEnum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorCode(IntEnum):
    """统一业务错误码（05-API接口文档.md §8.2）。"""

    OK = 0
    UNAUTHORIZED = 1001  # 未登录/Token 失效
    FORBIDDEN = 1002  # 无权限
    VALIDATION_ERROR = 2001  # 参数校验失败
    NOT_FOUND = 3001  # 资源不存在
    QUOTA_EXCEEDED = 4001  # 余额/次数不足
    DUPLICATE_REQUEST = 4002  # 幂等拦截：同 Idempotency-Key 的重复请求（HTTP 409）
    MERCHANT_CLOSED = 5001  # 商家停业
    COUPON_UNAVAILABLE = 5002  # 券不可用（过期/不满足门槛）
    ORDER_TIMEOUT = 5003  # 订单已超时
    REDEEM_CODE_USED = 5004  # 核销码已使用
    AI_UNAVAILABLE = 6001  # AI 服务暂不可用
    INVITE_LIMIT = 7001  # 邀请已达上限
    INVITE_ABUSE = 4102  # 防刷拦截——同设备只计 1 次
    RATE_LIMITED = 429  # 【假设】复用 HTTP 429
    SERVER_ERROR = 500  # 【假设】复用 HTTP 500

    @classmethod
    def message(cls, code: "ErrorCode | int") -> str:
        return {
            cls.OK: "ok",
            cls.UNAUTHORIZED: "未登录或 Token 已失效",
            cls.FORBIDDEN: "无权限",
            cls.VALIDATION_ERROR: "参数校验失败",
            cls.NOT_FOUND: "资源不存在",
            cls.QUOTA_EXCEEDED: "余额/次数不足",
            cls.DUPLICATE_REQUEST: "重复请求（已拦截重放）",
            cls.MERCHANT_CLOSED: "商家停业",
            cls.COUPON_UNAVAILABLE: "券不可用（过期/不满足门槛）",
            cls.ORDER_TIMEOUT: "订单已超时",
            cls.REDEEM_CODE_USED: "核销码已使用",
            cls.AI_UNAVAILABLE: "AI 服务暂不可用",
            cls.INVITE_LIMIT: "邀请已达上限",
            cls.INVITE_ABUSE: "邀请异常：同设备仅可绑定一次",
            cls.RATE_LIMITED: "请求过于频繁",
            cls.SERVER_ERROR: "服务错误",
        }.get(int(code), "未知错误")


class Envelope(BaseModel, Generic[T]):
    """统一响应 envelope：成功 {code:0, message:"ok", data, request_id}；失败 data=None、errors 可选。"""

    model_config = ConfigDict(from_attributes=True)

    code: int = 0
    message: str = "ok"
    data: Optional[T] = None
    request_id: Optional[str] = None
    errors: Optional[dict[str, Any]] = None


class PageParams(BaseModel):
    """列表分页入参（默认按 created_at DESC，每页 20，上限 100）。"""

    model_config = ConfigDict(from_attributes=True)

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PageMeta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page: int
    page_size: int
    total: int


class PageResult(BaseModel, Generic[T]):
    """统一分页结构 data: {items, page}。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    page: PageMeta


# ---- 共享枚举（与 openapi.yaml components.schemas 一一对应）----

Gender = int  # 1男 2女（openapi enum [1,2]）
MealType = int  # 1早餐 2午餐 3晚餐 4加餐
RecordSource = int  # 1拍照 2语音 3手动 4AI推荐
TargetType = int  # 1减脂 2增肌 3维持
ActivityLevel = int  # 1卧床 2久坐 3轻度 4中度 5高度
OrderStatus = int  # 1待支付 2已支付待核销 3已完成 4已取消 5已退款
CouponStatus = int  # 1未用 2已用 3过期 4作废
CouponType = int  # 1满减 2折扣 3免费 4体验
CouponScope = int  # 1吃 2动 3异业 4通用


def ok(data: Any = None, request_id: str | None = None) -> dict[str, Any]:
    """构造成功 envelope（P0-e 统一响应中间件可直接复用）。"""
    return {"code": 0, "message": "ok", "data": data, "request_id": request_id}


def fail(
    code: int,
    message: str | None = None,
    errors: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """构造失败 envelope；message 缺省时按错误码表取默认文案。"""
    return {
        "code": int(code),
        "message": message or ErrorCode.message(code),
        "data": None,
        "request_id": request_id,
        "errors": errors,
    }
