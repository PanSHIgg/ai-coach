"""报告 schema（openapi: /api/report/export、/api/report/weekly）。

导出首期仅 csv，content 为文本内容（前端落盘）；周报聚合缺口/步数/体重 + AI 点评。
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ReportExportIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_type: Literal["weight", "weekly"]  # 导出内容：体重记录 / 周报
    format: Literal["csv"]  # 导出格式（首期仅 csv）


class ReportExportData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    filename: str
    mime: str
    content: str  # CSV 文本内容


class WeeklyReportDay(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    intake: Optional[float] = None
    deficit: Optional[float] = None
    steps: Optional[int] = None
    weight: Optional[float] = None


class WeeklyReportPeriod(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: date
    end: date


class WeeklyReportData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period: WeeklyReportPeriod
    intake_avg: float  # 日均摄入 kcal
    deficit_avg: float  # 日均缺口 kcal
    steps_avg: int  # 日均步数
    weight_change: Optional[float] = None  # 周内体重变化 kg
    comment: str  # AI 周点评（含免责声明）
    days: list[WeeklyReportDay]