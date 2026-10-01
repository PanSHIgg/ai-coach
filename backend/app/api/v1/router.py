"""API v1 路由聚合（挂 /api 前缀后即 openapi.yaml 全部接口）。"""

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
    recommend,
    records,
    steps,
    track,
    users,
    weight,
    coach,  # G1 真人教练工单
    plan,  # G2 平台自营会员订阅付费
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
    recommend,
    merchants,
    orders,
    coupons,
    community,
    admin,
    track,
    coach,  # G1 真人教练工单（current.md §2.1）
    plan,  # G2 平台自营会员订阅付费（路径族 /api/plan，不复用 order/subscription）
):
    api_router.include_router(module.router)
