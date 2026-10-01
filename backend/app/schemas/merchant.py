"""商家域 schema（openapi: /api/merchant/list、/api/merchant/{id}、/api/sku/catalog）。"""

from typing import Optional

from pydantic import BaseModel, ConfigDict

from .common import PageMeta


class MerchantBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str  # 轻食/便利店/健身房等
    distance_m: Optional[int] = None
    rating: float
    cover_url: Optional[str] = None
    status: int  # 1营业 0停业
    partner_level: int = 0  # 合作层级：0普通 1优选合作 2战略合作（§6.3.4，R-01）


class SkuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    price: float  # 元
    stock: int = -1  # -1 表示不限量


class MerchantDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    address: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    phone: Optional[str] = None
    rating: float
    status: int  # 1营业 0停业
    distance_m: Optional[int] = None
    partner_level: int = 0  # 合作层级：0普通 1优选合作 2战略合作（§6.3.4，R-01）
    skus: list[SkuOut] = []


class MerchantPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[MerchantBrief]
    page: PageMeta


class CatalogItem(BaseModel):
    """标准目录（平台运营维护，商家定价须落在 min_price~max_price 区间）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str  # FD-001
    name: str
    category: Optional[str] = None
    calories_low: Optional[int] = None
    calories_high: Optional[int] = None
    base_price: float
    min_price: float
    max_price: float
    unit: Optional[str] = None  # 份/盒


class CatalogData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[CatalogItem]
