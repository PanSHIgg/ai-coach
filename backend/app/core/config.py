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
    # 默认值：一次性生成的高熵随机串（secrets.token_urlsafe(48)，64 字符，
    # token_urlsafe(48)=48 字节熵），≥32 字节以消除 PyJWT InsecureKeyLengthWarning；
    # 生产必须用 .env 覆盖。
    JWT_SECRET: str = "GJ_r6g6PMb6JAOQp5CM_qI2c_ODwoj8S_9r7XsWNhtOh-ai3_4Tvn23rABonp0ia"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_HOURS: int = 2  # access 2h
    JWT_REFRESH_EXPIRE_DAYS: int = 7  # refresh 7d

    # ---- 微信小程序/支付 ----
    WECHAT_APPID: str = ""
    WECHAT_SECRET: str = ""  # 与 APPID 任一为空 → code2session 明确 1001 失败（不再走 mock）
    WECHAT_MCH_ID: str = ""
    WECHAT_PAY_KEY: str = ""
    PAY_MOCK_MODE: bool = False  # 沙箱支付：pay 即推进支付成功（生产必须 false）

    # ---- 微信订阅消息（F-06 AI 主动介入推送）----
    # 复用上方 WECHAT_APPID/WECHAT_SECRET 作为凭证；以下两项为订阅消息专属。
    # 总开关：默认 False → 一律降级为日志记录，绝不静默伪造发送成功。
    WECHAT_SUBSCRIBE_ENABLED: bool = False
    # 模板 ID 映射（占位）：逗号分隔 "template_type:template_id"，如 "1:TPL_xx,2:TPL_yy"；
    # 留空/未覆盖的场景回落 notification_service.SCENE_TEMPLATES 的占位 ID（判定为未配置）。
    WECHAT_SUBSCRIBE_TEMPLATE_IDS: str = ""

    # ---- 微信运动步数解密（F-09）----
    # 主路径：session_key 由 code2session 在登录时取得，按用户存 Redis（见
    #   app/services/auth_service.store_session_key，TTL 24h），解密时按当前用户读取；
    #   原因：session_key 每次 wx.login 都会轮换、只对"该用户本次登录"有效，静态配置无法承载。
    # 本键**仅作本地调试兜底**：Redis 无该用户 key 时才读它，且整进程只 warning 一次。
    #   正常部署请留空——填了又忘了清，等于用一个早已过期的会话密钥去解密。
    # 三者皆不可用时明确降级（不伪造步数：前端回退传 0 → 后端按 PAL 估算 NEAT）。
    WECHAT_STEPS_SESSION_KEY: str = ""

    # ---- 腾讯云 COS（公开读 / 私有写；小程序直传）----
    # 桶策略：公开读（对象经 COS_BASE_URL 或 bucket 域名可读）；私有写（写需后端签发的
    # STS 临时密钥，限本场景对象键前缀 + PutObject）。三者任一为空 → 上传凭证明确降级。
    COS_SECRET_ID: str = ""
    COS_SECRET_KEY: str = ""
    COS_BUCKET: str = ""
    COS_REGION: str = "ap-guangzhou"
    COS_BASE_URL: str = ""  # 自定义域名/CDN；留空回落 https://{bucket}.cos.{region}.myqcloud.com
    COS_STS_DURATION: int = 1800  # STS 临时密钥有效期（秒），腾讯云下限 900

    # ---- AI（D-09：LLM 与 VLM 统一走 OpenAI 兼容协议 /v1/chat/completions）----
    # OpenAI 兼容端点（DeepSeek/通义/ModelScope/混元等均提供），换厂商只改 env，
    # 连接与模型信息使用时由下方 env 设置；base_url/api_key 未配置 → 明确降级（Mock/模板），不崩。
    # LLM_*：对话（ai/chat、ai/recommend 润色、周点评）；VLM_*：拍照识别（meal/recognize）。
    LLM_BASE_URL: str = ""  # 如 https://api.deepseek.com/v1（须含 /v1）
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""  # 如 deepseek-chat / qwen-plus / Qwen/Qwen3.8-Flash-Next
    # 推理模型的思考链开关（OpenAI 兼容扩展参数 enable_thinking）。默认 False：
    # 营养问答不需要思考链，而它是延迟主因（实测 4433ms → 1122ms，4 倍）。
    # 开着则文档 §9.4「AI 对话 P95 < 3s」不达标。非推理模型不认此参数，多传无害。
    LLM_ENABLE_THINKING: bool = False
    VLM_BASE_URL: str = ""
    VLM_API_KEY: str = ""
    VLM_MODEL: str = ""

    # ---- AI 通用 ----
    # AI 调用超时（秒）：AI P95<3s，超时上限 5s 留余量，超时降级预置 FAQ（6001）
    AI_TIMEOUT: float = 5.0
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
    RATE_LIMIT_ADMIN_LOGIN_PER_MIN: int = 5  # IS-007: admin 登录严格档

    # ---- DB 连接池（Phase 5 F5：默认走真实池，替代全程 NullPool）----
    DB_POOL_SIZE: int = 10
    DB_POOL_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_DISABLED: bool = False  # True → 回退 NullPool（跨事件循环复用 engine 的场景）

    # ---- 幂等 / 防重放（Phase 5 F6）----
    IDEMPOTENCY_ENABLED: bool = True
    IDEMPOTENCY_TTL_SECONDS: int = 300  # 同 Idempotency-Key 的去重窗口（秒）


@lru_cache
def get_settings() -> Settings:
    """进程级单例（lru_cache）。"""
    return Settings()
