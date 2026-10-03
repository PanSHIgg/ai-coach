"""API v1 路由聚合（挂 /api 前缀后即 openapi.yaml 全部接口）。"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    account,
    admin,
    ai,
    auth,
    coach,  # G1 真人教练工单
    community,
    coupons,
    merchants,
    notification,
    orders,
    plan,  # G2 平台自营会员订阅付费
    privacy,
    recommend,
    records,
    report,
    steps,
    task,
    track,
    upload,  # COS 直传临时凭证
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
    recommend,
    merchants,
    orders,
    coupons,
    community,
    admin,
    track,
    upload,  # COS 直传临时凭证（/api/upload/credential）
    coach,  # 真人教练工单
    plan,  # G2 平台自营会员订阅付费（路径族 /api/plan，不复用 order/subscription）
    task,  # 任务中心 / 每日签到 / 积分（Wave A 地基）
    privacy,  # 隐私设置（Wave A 地基）
    report,  # 报告导出 / 周报（Wave A 地基）
):
    api_router.include_router(module.router)
