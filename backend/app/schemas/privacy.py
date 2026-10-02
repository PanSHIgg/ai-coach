"""隐私设置 schema（openapi: /api/privacy GET / PUT）。

PrivacyIn 为部分字段更新入参（仅更新传递的开关）；PrivacyData 为 GET/PUT 返回的完整结构。
"""

from pydantic import BaseModel, ConfigDict


class PrivacyIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    anonymous: bool | None = None  # 社区/榜单匿名
    mask_share: bool | None = None  # 分享海报打码
    visibility_leaderboard: bool | None = None  # 榜单向他人可见
    visibility_community: bool | None = None  # 社区资料可见
    allow_data_export: bool | None = None  # 允许数据导出


class PrivacyData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    anonymous: bool
    mask_share: bool
    visibility_leaderboard: bool
    visibility_community: bool
    allow_data_export: bool