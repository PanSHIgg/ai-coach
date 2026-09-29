"""应用配置（pydantic-settings）。

字段命名与仓库根 .env.example 一一对应（环境变量命名真源）；
新增字段（API_PREFIX/RATE_LIMIT_*/CORS_ALLOW_ORIGINS）为后端运行所需补充。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 应用 ----
    APP_NAME: str = "AI 饮食管控教练 API"
    ENV: str = "dev"
    DEBUG: bool = False
    API_PREFIX: str = "/api"
    API_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    CORS_ALLOW_ORIGINS: str = "*"  # 逗号分隔；* 表示全放行（开发期）

    # ---- PostgreSQL ----
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/ai_coach"

    # ---- Redis ----
    REDIS_URL: str = "redis://redis:6379/0"

    # ---- JWT ----
    JWT_SECRET: str = "change-me-to-a-random-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_HOURS: int = 2  # access 2h
    JWT_REFRESH_EXPIRE_DAYS: int = 7  # refresh 7d

    # ---- 微信小程序/支付 ----
    WECHAT_APPID: str = ""
    WECHAT_SECRET: str = ""  # 为空时 code2session 走 mock（P0）
    WECHAT_MCH_ID: str = ""
    WECHAT_PAY_KEY: str = ""
    PAY_MOCK_MODE: bool = True  # 沙箱支付：pay 即推进支付成功（演示默认开；生产 .env 可关）

    # ---- 腾讯云 COS ----
    COS_SECRET_ID: str = ""
    COS_SECRET_KEY: str = ""
    COS_BUCKET: str = ""
    COS_REGION: str = "ap-guangzhou"
    COS_BASE_URL: str = ""

    # ---- AI Provider ----
    AI_LLM_PROVIDER: str = "deepseek"
    AI_VISION_PROVIDER: str = "tencent"
    AI_API_KEY: str = ""
    AI_LLM_API_KEY: str = ""
    AI_VISION_API_KEY: str = ""
    AI_BASE_URL: str = ""
    AI_LLM_BASE_URL: str = ""
    AI_VISION_BASE_URL: str = ""
    AI_LLM_MODEL: str = "deepseek-chat"

    # ---- ModelScope / Qwen（ai_api.md：Qwen3.8-Flash-Next，自带视觉，对话+VLM 统一）----
    MS_API_KEY: str = ""
    MS_BASE_URL: str = "https://api-inference.modelscope.cn/v1"
    MS_MODEL: str = "Qwen/Qwen3.8-Flash-Next"
    MS_ENABLE_THINKING: bool = False  # 对话场景关闭思考，省 token、降延迟
    MS_MAX_TOKENS: int = 1024
    MS_TIMEOUT: float = 20.0  # 对齐 plan.md：AI P95 < 3s，超时降级预置 FAQ

    # ---- AI 通用 ----
    # 识别置信度低于该值 → need_confirm=true，须用户确认（06 文档 §六）
    AI_CONFIDENCE_THRESHOLD: float = 0.7
    # 每日 AI 对话次数配额（user_benefit.ai_times_left 初始值）
    AI_DAILY_TIMES: int = 10

    # ---- 管理后台初始账号 ----
    ADMIN_INIT_USERNAME: str = "admin"
    ADMIN_INIT_PASSWORD: str = "admin123456"

    # ---- 限流（04 文档 §6.3.6：全局 100/min/IP，AI 对话 20/min/用户，登录 10/min/IP）----
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_GLOBAL_PER_MIN: int = 100
    RATE_LIMIT_AI_PER_MIN: int = 20
    RATE_LIMIT_AUTH_PER_MIN: int = 10


@lru_cache
def get_settings() -> Settings:
    """进程级单例（lru_cache）。"""
    return Settings()
