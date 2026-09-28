"""API v1 路由聚合（挂 /api 前缀后即 openapi.yaml 全部 34 接口）。"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    account,
    admin,
    ai,
    auth,
    community,
    coupons,
    merchants,
    notification,
    orders,
    records,
    steps,
    users,
    weight,
)

api_router = APIRouter()
for module in (
    auth,
    users,
    account,
    records,
    steps,
    weight,
    notification,
    ai,
    merchants,
    orders,
    coupons,
    community,
    admin,
):
    api_router.include_router(module.router)
